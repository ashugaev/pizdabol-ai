import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from scripts import backfill_profile


def _page(page_id: str) -> dict:
    return {"id": page_id, "properties": {}}


class BatchGeneratorTests(unittest.TestCase):
    def test_batch_splits_on_count(self):
        entries = [f"entry-{i}" for i in range(5)]
        batches = list(backfill_profile._batch(entries, batch_size=2, max_chars=10_000))
        self.assertEqual(len(batches), 3)
        self.assertEqual(batches[0].count("entry-"), 2)
        self.assertEqual(batches[-1].count("entry-"), 1)

    def test_batch_splits_on_char_cap(self):
        entries = ["a" * 100, "b" * 100, "c" * 100]
        batches = list(backfill_profile._batch(entries, batch_size=10, max_chars=150))
        # Each entry alone is under the cap, but two together exceed it.
        self.assertEqual(len(batches), 3)

    def test_batch_keeps_oversized_entry_alone(self):
        entries = ["x" * 500]
        batches = list(backfill_profile._batch(entries, batch_size=5, max_chars=100))
        self.assertEqual(batches, ["x" * 500])


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, num_entries, batch_size=5, max_chars=6000, reset=False, dry_run=False, existing=None):
        pages = [_page(f"p{i}") for i in range(num_entries)]

        async def fake_extract(text, points):
            return list(points) + ["p"]

        with (
            patch.object(backfill_profile.notion, "get_diary_pages", new=AsyncMock(return_value=pages)),
            patch.object(backfill_profile.notion, "extract_page_title", side_effect=lambda page: f"title-{page['id']}"),
            patch.object(backfill_profile.notion, "get_page_text", new=AsyncMock(side_effect=lambda pid: f"body-{pid}")),
            patch.object(backfill_profile.roast, "extract_profile_points", new=AsyncMock(side_effect=fake_extract)) as extract,
            patch.object(backfill_profile.state_store, "get_profile_points", return_value=list(existing or [])),
            patch.object(backfill_profile.state_store, "set_profile_points", new=Mock()) as setter,
        ):
            result = await backfill_profile.backfill(
                batch_size=batch_size,
                max_chars=max_chars,
                reset=reset,
                dry_run=dry_run,
            )
        return result, extract, setter

    async def test_batch_count_matches_entries(self):
        _, extract, _ = await self._run(num_entries=12, batch_size=5)
        # 12 entries / batch size 5 -> 3 batches -> 3 extraction calls.
        self.assertEqual(extract.await_count, 3)

    async def test_accumulated_points_passed_to_next_batch(self):
        _, extract, _ = await self._run(num_entries=10, batch_size=5)
        first_call_points = extract.await_args_list[0].args[1]
        second_call_points = extract.await_args_list[1].args[1]
        self.assertEqual(first_call_points, [])
        self.assertEqual(second_call_points, ["p"])

    async def test_dry_run_does_not_persist(self):
        _, _, setter = await self._run(num_entries=5, batch_size=5, dry_run=True)
        setter.assert_not_called()

    async def test_persists_after_each_batch(self):
        _, _, setter = await self._run(num_entries=10, batch_size=5)
        self.assertEqual(setter.call_count, 2)

    async def test_reset_starts_from_empty(self):
        _, extract, _ = await self._run(num_entries=5, batch_size=5, reset=True, existing=["old"])
        self.assertEqual(extract.await_args_list[0].args[1], [])

    async def test_merge_uses_existing_profile(self):
        _, extract, _ = await self._run(num_entries=5, batch_size=5, existing=["old"])
        self.assertEqual(extract.await_args_list[0].args[1], ["old"])


if __name__ == "__main__":
    unittest.main()
