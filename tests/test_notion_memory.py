import os
import unittest

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import notion_memory

PARENT_PAGE_ID = "parent-page"
AUTHOR_PAGE_ID = "author-page"


def _bullet(*parts: str) -> dict:
    return {
        "id": f"block-{parts[0]}",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"plain_text": part} for part in parts]},
    }


def _header_block(text: str = "Updated 2026-01-01 00:00 UTC · 1 facts") -> dict:
    return {
        "id": "block-header",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"plain_text": text}]},
    }


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.is_success = True
        self.status_code = 200
        self.text = ""

    def json(self) -> dict:
        return self.payload


class FakeNotionHttp:
    """Routes the handful of endpoints the memory mirror touches.

    `database_parent` is what GET /databases returns, `children` maps a block id
    to the blocks it holds. Missing ids answer with an empty child list, which is
    what Notion does for a page with no content.
    """

    def __init__(self, database_parent: dict | None = None, children: dict | None = None):
        self.database_parent = database_parent or {"type": "page_id", "page_id": PARENT_PAGE_ID}
        self.children = children or {}
        self.post_calls = []
        self.patch_calls = []
        self.delete_calls = []

    async def get(self, url, headers):
        if "/databases/" in url:
            return FakeResponse({"parent": self.database_parent})
        block_id = url.split("/blocks/")[1].split("/children")[0]
        return FakeResponse({
            "results": self.children.get(block_id, []),
            "has_more": False,
            "next_cursor": None,
        })

    async def post(self, url, headers, json):
        self.post_calls.append({"url": url, "json": json})
        return FakeResponse({"id": "created-page"})

    async def patch(self, url, headers, json):
        self.patch_calls.append({"url": url, "json": json})
        return FakeResponse({})

    async def delete(self, url, headers):
        self.delete_calls.append(url)
        return FakeResponse({})


def _child_page(page_id: str, title: str) -> dict:
    return {"id": page_id, "type": "child_page", "child_page": {"title": title}}


def _bullets_written(patch_calls: list[dict]) -> list[str]:
    return [
        "".join(part["text"]["content"] for part in block["bulleted_list_item"]["rich_text"])
        for call in patch_calls
        for block in call["json"]["children"]
        if block["type"] == "bulleted_list_item"
    ]


class MemoryPageBlockTests(unittest.TestCase):
    def test_body_starts_with_a_header_then_one_bullet_per_item(self):
        blocks = notion_memory._memory_blocks(["first fact", "second fact"], "facts")

        self.assertEqual([block["type"] for block in blocks],
                         ["paragraph", "bulleted_list_item", "bulleted_list_item"])
        header = blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
        self.assertTrue(header.startswith("Updated "))
        self.assertTrue(header.endswith("· 2 facts"))
        self.assertEqual(_bullets_written([{"json": {"children": blocks}}]),
                         ["first fact", "second fact"])

    def test_empty_memory_is_a_header_only(self):
        blocks = notion_memory._memory_blocks([], "rules")

        self.assertEqual([block["type"] for block in blocks], ["paragraph"])
        self.assertTrue(blocks[0]["paragraph"]["rich_text"][0]["text"]["content"].endswith("· 0 rules"))

    def test_listed_items_joins_split_rich_text_and_ignores_the_header(self):
        blocks = [_header_block(), _bullet("long ", "fact"), _bullet("short")]

        self.assertEqual(notion_memory._listed_items(blocks), ["long fact", "short"])


class MemoryParentTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_is_the_page_holding_the_diary_database(self):
        http = FakeNotionHttp()

        self.assertEqual(await notion_memory._memory_parent_page_id(http), PARENT_PAGE_ID)

    async def test_database_outside_a_page_is_a_clear_error(self):
        http = FakeNotionHttp(database_parent={"type": "workspace", "workspace": True})

        with self.assertRaisesRegex(RuntimeError, "inside a page"):
            await notion_memory._memory_parent_page_id(http)


class SyncMemoryPageTests(unittest.IsolatedAsyncioTestCase):
    def _http(self, page_children: list[dict], title: str = "Memory — Author profile"):
        return FakeNotionHttp(children={
            PARENT_PAGE_ID: [_child_page(AUTHOR_PAGE_ID, title)],
            AUTHOR_PAGE_ID: page_children,
        })

    async def _sync(self, http, items, title="Memory — Author profile"):
        return await notion_memory._sync_memory_page(http, title, items, "facts")

    async def test_unchanged_memory_is_not_rewritten(self):
        http = self._http([_header_block(), _bullet("kept fact")])

        self.assertFalse(await self._sync(http, ["kept fact"]))
        self.assertEqual(http.delete_calls, [])
        self.assertEqual(http.patch_calls, [])
        self.assertEqual(http.post_calls, [])

    async def test_changed_memory_replaces_the_whole_body(self):
        http = self._http([_header_block(), _bullet("stale fact")])

        self.assertTrue(await self._sync(http, ["fresh fact", "another fact"]))
        self.assertEqual(http.delete_calls, [
            f"{notion_memory.API}/blocks/block-header",
            f"{notion_memory.API}/blocks/block-stale fact",
        ])
        self.assertEqual(len(http.patch_calls), 1)
        self.assertEqual(http.patch_calls[0]["url"],
                         f"{notion_memory.API}/blocks/{AUTHOR_PAGE_ID}/children")
        self.assertEqual(_bullets_written(http.patch_calls), ["fresh fact", "another fact"])

    async def test_reordered_memory_counts_as_changed(self):
        http = self._http([_bullet("a"), _bullet("b")])

        self.assertTrue(await self._sync(http, ["b", "a"]))

    async def test_emptied_memory_leaves_a_header_only_page(self):
        http = self._http([_header_block(), _bullet("gone")])

        self.assertTrue(await self._sync(http, []))
        self.assertEqual(_bullets_written(http.patch_calls), [])
        self.assertEqual([block["type"] for block in http.patch_calls[0]["json"]["children"]],
                         ["paragraph"])

    async def test_long_memory_is_written_in_notion_sized_chunks(self):
        items = [f"fact {index}" for index in range(150)]
        http = self._http([])

        self.assertTrue(await self._sync(http, items))
        self.assertEqual([len(call["json"]["children"]) for call in http.patch_calls], [100, 51])
        self.assertEqual(_bullets_written(http.patch_calls), items)

    async def test_missing_page_is_created_next_to_the_database(self):
        http = FakeNotionHttp(children={PARENT_PAGE_ID: [_child_page("db-block", "Diary")]})

        self.assertTrue(await self._sync(http, ["first fact"]))
        self.assertEqual(len(http.post_calls), 1)
        created = http.post_calls[0]
        self.assertEqual(created["url"], f"{notion_memory.API}/pages")
        self.assertEqual(created["json"]["parent"], {"page_id": PARENT_PAGE_ID})
        self.assertEqual(
            created["json"]["properties"]["title"]["title"][0]["text"]["content"],
            "Memory — Author profile",
        )
        # A fresh page starts empty, so the body is appended, never deleted.
        self.assertEqual(http.delete_calls, [])
        self.assertEqual(_bullets_written(http.patch_calls), ["first fact"])


class EnsureMemoryPagesTests(unittest.IsolatedAsyncioTestCase):
    async def _ensure(self, http) -> list[str]:
        class FakeClient:
            def __init__(self, timeout=None):
                pass

            async def __aenter__(self):
                return http

            async def __aexit__(self, *args):
                return False

        original = notion_memory.httpx.AsyncClient
        notion_memory.httpx.AsyncClient = FakeClient
        try:
            return await notion_memory.ensure_memory_pages()
        finally:
            notion_memory.httpx.AsyncClient = original

    async def test_both_pages_are_created_when_missing(self):
        http = FakeNotionHttp(children={PARENT_PAGE_ID: []})

        page_ids = await self._ensure(http)

        self.assertEqual(page_ids, ["created-page", "created-page"])
        titles = [
            call["json"]["properties"]["title"]["title"][0]["text"]["content"]
            for call in http.post_calls
        ]
        self.assertEqual(titles, ["Memory — Author profile", "Memory — Bot rules"])
        # Seeded with a header so a page never looks broken before its first sync.
        labels = [
            call["json"]["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
            for call in http.post_calls
        ]
        self.assertTrue(labels[0].endswith("· 0 facts"))
        self.assertTrue(labels[1].endswith("· 0 rules"))

    async def test_existing_pages_are_reused_and_their_content_untouched(self):
        http = FakeNotionHttp(children={
            PARENT_PAGE_ID: [
                _child_page("author-1", notion_memory.AUTHOR_MEMORY_PAGE_TITLE),
                _child_page("bot-1", notion_memory.BOT_MEMORY_PAGE_TITLE),
            ],
        })

        self.assertEqual(await self._ensure(http), ["author-1", "bot-1"])
        self.assertEqual(http.post_calls, [])
        self.assertEqual(http.patch_calls, [])
        self.assertEqual(http.delete_calls, [])


if __name__ == "__main__":
    unittest.main()
