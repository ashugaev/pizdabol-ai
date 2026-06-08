import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import state_store as state_store_module
from services.state_store import StateStore


class StateStoreTests(unittest.TestCase):
    def test_records_messages_statuses_and_drafts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")

            key = store.record_voice(
                123,
                10,
                "file-1",
                "2026-06-04T10:00:00+00:00",
                file_unique_id="voice-unique",
                duration=42,
                file_size=1000,
            )
            duplicate_key = store.record_voice(123, 10, "file-2", None)
            store.mark_message_processing(key)
            store.mark_message_drafted(key, "entry-1")
            store.save_draft({"id": "entry-1", "title": "Title", "tags": ["work"]})

            self.assertEqual(key, "123:10")
            self.assertEqual(duplicate_key, key)
            message = store.get_message(key)
            self.assertEqual(message["file_id"], "file-1")
            self.assertEqual(message["file_unique_id"], "voice-unique")
            self.assertEqual(message["duration"], 42)
            self.assertEqual(message["file_size"], 1000)
            self.assertEqual(message["status"], "drafted")
            self.assertEqual(message["entry_id"], "entry-1")

            draft = store.get_draft("entry-1")
            draft["title"] = "Changed"
            self.assertEqual(store.get_draft("entry-1")["title"], "Title")

            store.mark_message_saved(key)
            self.assertEqual(store.get_message(key)["status"], "saved")

            store.mark_message_cancelled(key)
            self.assertEqual(store.get_message(key)["status"], "cancelled")
            store.remove_draft("entry-1")
            self.assertIsNone(store.get_draft("entry-1"))

    def test_recent_unprocessed_messages_returns_oldest_to_newest_within_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")
            old_key = store.record_text(123, 1, "old", "2026-06-01T10:00:00+00:00")
            newest_key = store.record_text(123, 3, "newest", "2026-06-03T10:00:00+00:00")
            middle_key = store.record_text(123, 2, "middle", "2026-06-02T10:00:00+00:00")
            store.mark_message_saved(old_key)

            recent = store.recent_unprocessed_messages(limit=2)

            self.assertEqual([message["key"] for message in recent], [middle_key, newest_key])

    def test_prunes_old_messages_when_limit_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_limit = state_store_module.MAX_RETAINED_MESSAGES
            state_store_module.MAX_RETAINED_MESSAGES = 2
            try:
                store = StateStore(Path(tmpdir) / "state.json")
                store.record_text(123, 1, "one", "2026-06-01T10:00:00+00:00")
                store.record_text(123, 2, "two", "2026-06-02T10:00:00+00:00")
                store.record_text(123, 3, "three", "2026-06-03T10:00:00+00:00")
            finally:
                state_store_module.MAX_RETAINED_MESSAGES = original_limit

            self.assertIsNone(store.get_message("123:1"))
            self.assertIsNotNone(store.get_message("123:2"))
            self.assertIsNotNone(store.get_message("123:3"))
