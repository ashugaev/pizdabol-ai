import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import profile_rebuild


def _page(page_id: str, title: str = "", created: str = "") -> dict:
    properties = {}
    if title:
        properties["Name"] = {"type": "title", "title": [{"plain_text": title}]}
    if created:
        properties[profile_rebuild.CREATED_PROPERTY] = {"date": {"start": created}}
    return {"id": page_id, "properties": properties}


class ProgressBarTests(unittest.TestCase):
    def test_bar_renders_share_percent_and_counts(self):
        bar = profile_rebuild.render_progress_bar(3, 12)

        self.assertEqual(bar.count(profile_rebuild.PROGRESS_BAR_FILLED), 3)
        self.assertEqual(bar.count(profile_rebuild.PROGRESS_BAR_EMPTY), 9)
        self.assertIn("25%", bar)
        self.assertIn("3/12 notes", bar)

    def test_bar_is_full_when_all_notes_handled(self):
        bar = profile_rebuild.render_progress_bar(7, 7)

        self.assertEqual(
            bar.count(profile_rebuild.PROGRESS_BAR_FILLED),
            profile_rebuild.PROGRESS_BAR_WIDTH,
        )
        self.assertIn("100%", bar)

    def test_bar_handles_empty_and_out_of_range_totals(self):
        self.assertIn("0/0 notes", profile_rebuild.render_progress_bar(0, 0))
        self.assertIn("100%", profile_rebuild.render_progress_bar(9, 5))


class NoteTextTests(unittest.TestCase):
    def test_note_text_prepends_date_and_title(self):
        note = profile_rebuild._note_text(_page("p1", "Long day", "2026-07-01"), "  body text  ")

        self.assertEqual(note, "2026-07-01 · Long day\n\nbody text")

    def test_note_text_is_empty_for_blank_body(self):
        self.assertEqual(profile_rebuild._note_text(_page("p1", "Title"), "   "), "")

    def test_note_text_survives_pages_without_title_or_date(self):
        self.assertEqual(profile_rebuild._note_text(_page("p1"), "body"), "body")


class RebuildProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pages = [
            _page("p1", "First", "2026-06-01"),
            _page("p2", "Second", "2026-06-02"),
            _page("p3", "Third", "2026-06-03"),
        ]

    def _mocks(self, stack, page_text=None, extract=None):
        """Patch every boundary the pass touches: Notion, the AI provider, the pause."""
        mocks = SimpleNamespace(
            page_text=page_text or AsyncMock(return_value="note"),
            extract=extract or AsyncMock(return_value=["a"]),
            pause=AsyncMock(),
        )
        stack.enter_context(
            patch.object(profile_rebuild, "get_diary_pages", AsyncMock(return_value=self.pages))
        )
        stack.enter_context(patch.object(profile_rebuild, "get_page_text", mocks.page_text))
        stack.enter_context(
            patch.object(profile_rebuild.roast, "extract_profile_points", mocks.extract)
        )
        stack.enter_context(patch.object(profile_rebuild, "_pause", mocks.pause))
        return mocks

    async def test_walk_is_sequential_and_accumulates_points(self):
        with ExitStack() as stack:
            mocks = self._mocks(
                stack,
                page_text=AsyncMock(side_effect=["note one", "note two", "note three"]),
                extract=AsyncMock(side_effect=[["a"], ["a", "b"], ["a", "b", "c"]]),
            )
            result = await profile_rebuild.rebuild_profile("keep work", [], None)

        self.assertEqual(result.processed, 3)
        self.assertEqual(result.total, 3)
        self.assertEqual(result.points, ["a", "b", "c"])
        self.assertIsNone(result.aborted_reason)

        # Notes are read oldest-first, one page at a time.
        self.assertEqual(
            [call.args[0] for call in mocks.page_text.await_args_list],
            ["p1", "p2", "p3"],
        )
        # Each step feeds the previous step's output back in, and the focus rides along.
        self.assertEqual(
            [call.args[1] for call in mocks.extract.await_args_list],
            [[], ["a"], ["a", "b"]],
        )
        for call in mocks.extract.await_args_list:
            self.assertEqual(call.kwargs["focus"], "keep work")
        # One breather between notes, never before the first one.
        self.assertEqual(mocks.pause.await_count, 2)

    async def test_existing_points_seed_the_pass(self):
        with ExitStack() as stack:
            mocks = self._mocks(stack, extract=AsyncMock(return_value=["known", "fresh"]))
            result = await profile_rebuild.rebuild_profile(None, ["known"], None)

        self.assertEqual(mocks.extract.await_args_list[0].args[1], ["known"])
        self.assertEqual(result.points, ["known", "fresh"])

    async def test_focus_is_omitted_when_not_given(self):
        with ExitStack() as stack:
            mocks = self._mocks(stack)
            await profile_rebuild.rebuild_profile(None, [], None)

        for call in mocks.extract.await_args_list:
            self.assertIsNone(call.kwargs["focus"])

    async def test_empty_notes_are_skipped_without_an_ai_request(self):
        with ExitStack() as stack:
            mocks = self._mocks(
                stack,
                page_text=AsyncMock(side_effect=["", "note two", "   "]),
                extract=AsyncMock(return_value=["b"]),
            )
            result = await profile_rebuild.rebuild_profile(None, [], None)

        self.assertEqual(mocks.extract.await_count, 1)
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.skipped, 2)
        self.assertEqual(result.handled, 3)

    async def test_single_failure_keeps_points_and_continues(self):
        with ExitStack() as stack:
            mocks = self._mocks(
                stack,
                page_text=AsyncMock(side_effect=["one", "two", "three"]),
                extract=AsyncMock(side_effect=[["a"], RuntimeError("boom"), ["a", "c"]]),
            )
            result = await profile_rebuild.rebuild_profile(None, [], None)

        self.assertEqual(result.processed, 2)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.points, ["a", "c"])
        self.assertIsNone(result.aborted_reason)
        # The failed note did not corrupt the accumulator handed to the next step.
        self.assertEqual(mocks.extract.await_args_list[2].args[1], ["a"])

    async def test_unreadable_page_counts_as_failure_and_skips_extraction(self):
        with ExitStack() as stack:
            mocks = self._mocks(
                stack,
                page_text=AsyncMock(side_effect=[RuntimeError("notion down"), "two", "three"]),
                extract=AsyncMock(side_effect=[["b"], ["b", "c"]]),
            )
            result = await profile_rebuild.rebuild_profile(None, [], None)

        self.assertEqual(mocks.extract.await_count, 2)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.processed, 2)

    async def test_consecutive_failures_abort_the_pass(self):
        self.pages = [_page(f"p{index}") for index in range(10)]
        with ExitStack() as stack:
            mocks = self._mocks(stack, extract=AsyncMock(side_effect=RuntimeError("bad key")))
            result = await profile_rebuild.rebuild_profile(None, ["kept"], None)

        self.assertEqual(mocks.extract.await_count, profile_rebuild.MAX_CONSECUTIVE_FAILURES)
        self.assertEqual(result.failed, profile_rebuild.MAX_CONSECUTIVE_FAILURES)
        self.assertIn("in a row failed", result.aborted_reason)
        self.assertEqual(result.points, ["kept"])

    async def test_failures_spread_apart_do_not_abort(self):
        self.pages = [_page(f"p{index}") for index in range(6)]
        with ExitStack() as stack:
            self._mocks(stack, extract=AsyncMock(side_effect=[
                RuntimeError("x"), ["a"],
                RuntimeError("x"), ["a", "b"],
                RuntimeError("x"), ["a", "b", "c"],
            ]))
            result = await profile_rebuild.rebuild_profile(None, [], None)

        self.assertIsNone(result.aborted_reason)
        self.assertEqual(result.failed, 3)
        self.assertEqual(result.processed, 3)

    async def test_progress_is_reported_before_the_walk_and_after_every_note(self):
        seen = []

        async def on_progress(progress):
            seen.append((progress.handled, list(progress.points)))

        with ExitStack() as stack:
            self._mocks(stack, extract=AsyncMock(side_effect=[["a"], ["a", "b"], ["a", "b", "c"]]))
            await profile_rebuild.rebuild_profile(None, [], on_progress)

        self.assertEqual(seen, [(0, []), (1, ["a"]), (2, ["a", "b"]), (3, ["a", "b", "c"])])

    async def test_progress_snapshots_are_isolated_from_later_steps(self):
        seen = []

        async def on_progress(progress):
            seen.append(progress.points)

        with ExitStack() as stack:
            self._mocks(stack, extract=AsyncMock(side_effect=[["a"], ["a", "b"], ["a", "b", "c"]]))
            await profile_rebuild.rebuild_profile(None, [], on_progress)

        # Each snapshot keeps its own copy — a later step never mutates an earlier one.
        self.assertEqual(seen[1], ["a"])
        self.assertEqual(seen[2], ["a", "b"])

    async def test_progress_callback_failure_does_not_break_the_pass(self):
        async def on_progress(progress):
            raise RuntimeError("telegram down")

        with ExitStack() as stack:
            self._mocks(stack)
            result = await profile_rebuild.rebuild_profile(None, [], on_progress)

        self.assertEqual(result.processed, 3)
        self.assertEqual(result.points, ["a"])

    async def test_empty_database_returns_an_empty_pass(self):
        self.pages = []
        with ExitStack() as stack:
            mocks = self._mocks(stack)
            result = await profile_rebuild.rebuild_profile(None, ["kept"], None)

        self.assertEqual((result.total, result.handled), (0, 0))
        self.assertEqual(result.points, ["kept"])
        mocks.extract.assert_not_awaited()

    async def test_second_run_is_rejected_while_one_is_in_flight(self):
        async def extract_and_reenter(*args, **kwargs):
            self.assertTrue(profile_rebuild.is_running())
            with self.assertRaises(profile_rebuild.RebuildAlreadyRunning):
                await profile_rebuild.rebuild_profile(None, [], None)
            return ["a"]

        with ExitStack() as stack:
            self._mocks(stack, extract=AsyncMock(side_effect=extract_and_reenter))
            result = await profile_rebuild.rebuild_profile(None, [], None)

        self.assertEqual(result.processed, 3)
        self.assertFalse(profile_rebuild.is_running())

    async def test_lock_is_released_when_the_pass_raises(self):
        with patch.object(
            profile_rebuild, "get_diary_pages", AsyncMock(side_effect=RuntimeError("notion down"))
        ):
            with self.assertRaisesRegex(RuntimeError, "notion down"):
                await profile_rebuild.rebuild_profile(None, [], None)

        self.assertFalse(profile_rebuild.is_running())


if __name__ == "__main__":
    unittest.main()
