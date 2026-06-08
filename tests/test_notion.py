import os
import unittest

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import notion


class NotionHelpersTests(unittest.TestCase):
    def test_extract_page_title_uses_known_or_fallback_title_property(self):
        page = {
            "properties": {
                "Custom title": {
                    "type": "title",
                    "title": [{"plain_text": "Daily page"}],
                }
            }
        }

        self.assertEqual(notion.extract_page_title(page), "Daily page")

    def test_find_database_property_prefers_candidate_then_type_fallback(self):
        properties = {
            "Name": {"type": "rich_text"},
            "Actual title": {"type": "title"},
        }

        self.assertEqual(
            notion._find_database_property(properties, "title", ("Name",)),
            "Actual title",
        )

    def test_combine_tags_uses_configured_tags_property_and_deduplicates(self):
        page = {
            "properties": {
                "Labels": {
                    "multi_select": [
                        {"name": "Daily"},
                        {"name": "work"},
                    ]
                }
            }
        }

        self.assertEqual(
            notion._combine_tags(page, ["work", "health"], "Labels"),
            [{"name": "Daily"}, {"name": "work"}, {"name": "health"}],
        )


class NotionSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_database_schema_adds_missing_created_and_tags_properties(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
        })

        result = await notion.ensure_database_schema(http)

        self.assertEqual(result, ("Name", "Created", "Tags", "Day"))
        self.assertEqual(len(http.patch_calls), 1)
        self.assertEqual(
            http.patch_calls[0]["json"],
            {
                "properties": {
                    "Created": {"date": {}},
                    "Tags": {"multi_select": {}},
                    "Day": {"select": {}},
                }
            },
        )

    async def test_ensure_database_schema_rejects_wrong_created_type(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
            "Created": {"type": "rich_text"},
            "Tags": {"type": "multi_select"},
            "Day": {"type": "select"},
        })

        with self.assertRaisesRegex(RuntimeError, 'property "Created" must be a date'):
            await notion.ensure_database_schema(http)

    async def test_ensure_database_schema_rejects_wrong_day_type(self):
        http = FakeNotionHttp({
            "Name": {"type": "title"},
            "Created": {"type": "date"},
            "Tags": {"type": "multi_select"},
            "Day": {"type": "rich_text"},
        })

        with self.assertRaisesRegex(RuntimeError, 'property "Day" must be a select'):
            await notion.ensure_database_schema(http)

    async def test_save_entry_creates_a_new_page_for_each_entry(self):
        calls = []

        async def fake_create_page(entry_title, entry_text, entry_tags):
            calls.append((entry_title, entry_text, entry_tags))
            return "page-1"

        original_create_page = notion.create_page
        notion.create_page = fake_create_page
        try:
            result = await notion.save_entry("Title", "Text", ["work"])
        finally:
            notion.create_page = original_create_page

        self.assertEqual(result, "page-1")
        self.assertEqual(calls, [("Title", "Text", ["work"])])

    async def test_request_with_retry_retries_transient_notion_errors(self):
        http = FakeRetryHttp([
            FakeResponse({}, is_success=False, status_code=503, text="unavailable"),
            FakeResponse({"ok": True}),
        ])
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        original_sleep = notion.asyncio.sleep
        notion.asyncio.sleep = fake_sleep
        try:
            resp = await notion._request_with_retry(http, "get", "https://notion.test")
        finally:
            notion.asyncio.sleep = original_sleep

        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(http.get_calls, 2)
        self.assertEqual(sleeps, [notion.NOTION_RETRY_DELAY])

    async def test_create_page_verifies_created_page_before_returning_success(self):
        http = FakeCreatePageHttp()
        original_client = notion.httpx.AsyncClient
        notion.httpx.AsyncClient = lambda timeout: http
        try:
            page_id = await notion.create_page("Title", "Text", ["work"])
        finally:
            notion.httpx.AsyncClient = original_client

        self.assertEqual(page_id, "page-1")
        self.assertEqual(http.created_pages, 1)
        self.assertEqual(http.verified_pages, ["page-1"])


class FakeNotionHttp:
    def __init__(self, properties):
        self.properties = properties
        self.patch_calls = []

    async def get(self, url, headers):
        return FakeResponse({"properties": self.properties})

    async def patch(self, url, headers, json):
        self.patch_calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse({})


class FakeRetryHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.get_calls = 0

    async def get(self, url, headers):
        self.get_calls += 1
        return self.responses.pop(0)


class FakeCreatePageHttp:
    def __init__(self):
        self.created_pages = 0
        self.verified_pages = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers):
        if "/databases/" in url:
            return FakeResponse({
                "properties": {
                    "Name": {"type": "title"},
                    "Created": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                    "Day": {"type": "select"},
                }
            })
        page_id = url.rsplit("/", 1)[-1]
        self.verified_pages.append(page_id)
        return FakeResponse({"id": page_id, "archived": False})

    async def post(self, url, headers, json):
        self.created_pages += 1
        return FakeResponse({"id": "page-1"})


class FakeResponse:
    def __init__(self, payload, is_success=True, status_code=200, text=""):
        self.payload = payload
        self.is_success = is_success
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload
