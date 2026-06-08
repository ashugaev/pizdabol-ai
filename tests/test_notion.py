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

        original_create_page = notion.create_page
        notion.create_page = fake_create_page
        try:
            result = await notion.save_entry("Title", "Text", ["work"])
        finally:
            notion.create_page = original_create_page

        self.assertIsNone(result)
        self.assertEqual(calls, [("Title", "Text", ["work"])])


class FakeNotionHttp:
    def __init__(self, properties):
        self.properties = properties
        self.patch_calls = []

    async def get(self, url, headers):
        return FakeResponse({"properties": self.properties})

    async def patch(self, url, headers, json):
        self.patch_calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse({})


class FakeResponse:
    def __init__(self, payload, is_success=True):
        self.payload = payload
        self.is_success = is_success
        self.status_code = 200
        self.text = ""

    def json(self):
        return self.payload
