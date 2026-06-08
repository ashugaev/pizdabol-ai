import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import bot


class PreviewRenderingTests(unittest.TestCase):
    def test_preview_text_combines_title_body_and_tags_with_html_escaping(self):
        preview = bot._preview_text("Title <x>", "Body & notes", ["Daily", "work & life"])

        self.assertEqual(
            preview,
            "<b>Title &lt;x&gt;</b>\n\n"
            "Body &amp; notes\n\n"
            "<code>Daily</code> <code>work &amp; life</code>",
        )

    def test_preview_keyboard_scopes_every_callback_to_entry_id(self):
        keyboard = bot._preview_keyboard("entry-1", highlighted=True)
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(
            callback_data,
            [
                "edit_title:entry-1",
                "edit_text:entry-1",
                "edit_tags:entry-1",
                "toggle_highlight:entry-1",
                "save:entry-1",
                "cancel:entry-1",
            ],
        )

    def test_callback_payload_parses_action_and_entry_id(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="save:entry-1"))

        self.assertEqual(bot._callback_payload(update), ("save", "entry-1"))

    def test_callback_payload_rejects_unscoped_data(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="save"))

        self.assertEqual(bot._callback_payload(update), (None, None))

    def test_entry_metadata_uses_voice_file_facts_for_deduplication(self):
        metadata = bot._entry_metadata({
            "kind": "voice",
            "chat_id": 123,
            "message_id": 10,
            "file_unique_id": "voice-unique",
            "duration": 42,
            "file_size": 1000,
        }, "transcribed text")

        self.assertEqual(metadata, {
            "source": "voice",
            "telegram_chat_id": 123,
            "telegram_message_id": 10,
            "voice_file_unique_id": "voice-unique",
            "audio_duration": 42,
            "audio_file_size": 1000,
        })

    def test_entry_metadata_hashes_manual_text_for_exact_deduplication(self):
        metadata = bot._entry_metadata({
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
        }, "exact text")

        self.assertEqual(metadata["source"], "text")
        self.assertEqual(metadata["telegram_chat_id"], 123)
        self.assertEqual(metadata["telegram_message_id"], 10)
        self.assertEqual(metadata["source_text_hash"], bot._source_text_hash("exact text"))


class ReplyToSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_to_source_uses_reply_parameters_for_stored_message(self):
        fake_bot = FakeSendBot()
        message_ref = bot.StoredMessageRef(fake_bot, chat_id=123, message_id=456)

        message = await bot._reply_to_source(message_ref, "Processing", parse_mode="HTML")

        self.assertEqual(message.message_id, 999)
        self.assertEqual(fake_bot.sent_messages[0]["chat_id"], 123)
        self.assertEqual(fake_bot.sent_messages[0]["text"], "Processing")
        self.assertEqual(fake_bot.sent_messages[0]["parse_mode"], "HTML")
        reply_parameters = fake_bot.sent_messages[0]["reply_parameters"]
        self.assertEqual(reply_parameters.message_id, 456)
        self.assertTrue(reply_parameters.allow_sending_without_reply)


class CreatePreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_preview_edits_existing_processing_reply_and_persists_draft(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        source_message = SimpleNamespace(chat_id=123, message_id=10)
        processing_message = SimpleNamespace(chat_id=123, message_id=20)
        fake_state_store.messages["123:10"] = {
            "kind": "voice",
            "chat_id": 123,
            "message_id": 10,
            "file_unique_id": "voice-unique",
            "duration": 12,
            "file_size": 345,
        }

        with (
            patch.object(bot, "format_entry", new=AsyncMock(return_value=("Title", "Body", ["work"]))),
            patch.object(bot, "_new_entry_id", return_value="entry-1"),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._create_preview(
                source_message,
                fake_context,
                "raw transcription",
                message_key="123:10",
                preview_message=processing_message,
            )

        self.assertEqual(len(fake_context.bot.edits), 1)
        edit = fake_context.bot.edits[0]
        self.assertEqual(edit["chat_id"], 123)
        self.assertEqual(edit["message_id"], 20)
        self.assertEqual(edit["text"], bot._preview_text("Title", "Body", ["work"]))
        self.assertEqual(edit["parse_mode"], "HTML")
        self.assertEqual(fake_state_store.marked_drafted, [("123:10", "entry-1")])
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_msg_id"], 20)
        self.assertEqual(fake_state_store.saved_drafts[0]["metadata"]["voice_file_unique_id"], "voice-unique")
        self.assertIn("entry-1", fake_context.user_data[bot.DRAFTS_KEY])

    async def test_create_preview_sends_new_reply_when_no_processing_message_exists(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeSendBot(), user_data={})
        source_message = SimpleNamespace(
            chat_id=123,
            message_id=10,
            get_bot=lambda: fake_context.bot,
        )

        with (
            patch.object(bot, "format_entry", new=AsyncMock(return_value=("Title", "Body", []))),
            patch.object(bot, "_new_entry_id", return_value="entry-2"),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._create_preview(source_message, fake_context, "plain text")

        self.assertEqual(len(fake_context.bot.sent_messages), 1)
        reply_parameters = fake_context.bot.sent_messages[0]["reply_parameters"]
        self.assertEqual(reply_parameters.message_id, 10)
        self.assertTrue(reply_parameters.allow_sending_without_reply)
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_msg_id"], 999)


class CancelDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_draft_removes_persisted_and_in_memory_draft(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={
            bot.DRAFTS_KEY: {
                "entry-1": {
                    "id": "entry-1",
                    "message_key": "123:10",
                }
            }
        })
        draft = fake_context.user_data[bot.DRAFTS_KEY]["entry-1"]

        with patch.object(bot, "state_store", fake_state_store):
            await bot._cancel_draft(fake_query, fake_context, "entry-1", draft)

        self.assertNotIn("entry-1", fake_context.user_data[bot.DRAFTS_KEY])
        self.assertEqual(fake_state_store.marked_cancelled, ["123:10"])
        self.assertEqual(fake_state_store.removed_drafts, ["entry-1"])
        self.assertEqual(fake_query.edits[0]["text"], "Cancelled.")


class SaveDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_draft_keeps_draft_and_retry_button_when_notion_save_fails(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={bot.DRAFTS_KEY: {}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "message_key": "123:10",
            "saving": False,
        }

        async def failing_save_entry(title, text, tags, metadata=None):
            raise RuntimeError("notion timeout")

        with (
            patch.object(bot, "save_entry", new=failing_save_entry),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot.logger, "exception"),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertFalse(draft["saving"])
        self.assertEqual(fake_state_store.saved_drafts[-1]["id"], "entry-1")
        self.assertEqual(fake_query.edits[0]["text"], "Saving to Notion...")
        self.assertIn("Not saved to Notion: notion timeout", fake_query.edits[1]["text"])
        self.assertIn("Press Save to retry", fake_query.edits[1]["text"])
        self.assertIsNotNone(fake_query.edits[1].get("reply_markup"))


class FakeSendBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            message_id=999,
            get_bot=lambda: self,
        )


class FakeEditBot:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            message_id=kwargs["message_id"],
            get_bot=lambda: self,
        )


class FakeQuery:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, **kwargs})


class FakeStateStore:
    def __init__(self):
        self.messages = {}
        self.saved_drafts = []
        self.marked_drafted = []
        self.marked_cancelled = []
        self.removed_drafts = []

    def get_message(self, key):
        return self.messages.get(key)

    def save_draft(self, draft):
        self.saved_drafts.append(dict(draft))

    def mark_message_drafted(self, key, entry_id):
        self.marked_drafted.append((key, entry_id))

    def mark_message_cancelled(self, key):
        self.marked_cancelled.append(key)

    def remove_draft(self, entry_id):
        self.removed_drafts.append(entry_id)
