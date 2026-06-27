import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.ext import CommandHandler

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import bot


class ApplicationSetupTests(unittest.TestCase):
    def _build_defaults(self, silent):
        builder = FakeApplicationBuilder(FakePollingApplication())
        with patch.object(bot, "ApplicationBuilder", return_value=builder), \
                patch.object(bot.settings, "silent_notifications", silent):
            bot.main()
        return builder.defaults_value

    def test_main_wires_silent_notifications_into_defaults(self):
        defaults = self._build_defaults(True)
        self.assertTrue(defaults.disable_notification)

    def test_main_respects_disabled_silent_notifications(self):
        defaults = self._build_defaults(False)
        self.assertFalse(defaults.disable_notification)


class PreviewRenderingTests(unittest.TestCase):
    def test_preview_text_combines_title_body_and_tags_with_html_escaping(self):
        entry_date = bot._default_entry_date()
        preview = bot._preview_text("Title <x>", "Body & notes", ["Daily", "work & life"], entry_date)

        self.assertEqual(
            preview,
            "<b>Title &lt;x&gt;</b>\n\n"
            "Body &amp; notes\n\n"
            f"Date: <code>{bot._entry_date_label(entry_date)}</code>\n\n"
            "<code>Daily</code> <code>work &amp; life</code>",
        )

    def test_preview_text_truncates_body_to_telegram_message_limit(self):
        entry_date = bot._default_entry_date()
        body = "x" * (bot.TELEGRAM_MESSAGE_LIMIT + 500)

        preview = bot._preview_text("Long voice transcript", body, [], entry_date)

        self.assertLessEqual(len(preview), bot.TELEGRAM_MESSAGE_LIMIT)
        self.assertIn("Preview truncated", preview)
        self.assertIn("Page 1/", preview)
        self.assertIn("Full text is kept", preview)
        self.assertNotEqual(preview, body)

    def test_preview_text_can_render_later_truncated_pages(self):
        entry_date = bot._default_entry_date()
        body = "\n".join(f"line {i:03d} " + "x" * 80 for i in range(120))

        first_page = bot._render_preview("Long voice transcript", body, [], entry_date, page=0)
        second_page = bot._render_preview("Long voice transcript", body, [], entry_date, page=1)

        self.assertTrue(first_page.truncated)
        self.assertGreater(first_page.page_count, 1)
        self.assertEqual(second_page.page, 1)
        self.assertEqual(second_page.page_count, first_page.page_count)
        self.assertLessEqual(len(second_page.text), bot.TELEGRAM_MESSAGE_LIMIT)
        self.assertIn(f"Page 2/{second_page.page_count}", second_page.text)
        self.assertNotEqual(first_page.text, second_page.text)

    def test_preview_keyboard_scopes_every_callback_to_entry_id(self):
        keyboard = bot._preview_keyboard(
            "entry-1",
            highlighted=True,
            entry_date=bot._default_entry_date(),
            show_format=True,
        )
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
                "format:entry-1",
                "pick_date:entry-1",
                "toggle_highlight:entry-1",
                "save:entry-1",
                "cancel:entry-1",
            ],
        )

    def test_preview_keyboard_adds_top_pagination_row_only_when_truncated(self):
        keyboard = bot._preview_keyboard(
            "entry-1",
            entry_date=bot._default_entry_date(),
            show_pagination=True,
            preview_page=1,
            page_count=3,
        )
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(
            callback_data[:2],
            ["preview_page:entry-1:0", "preview_page:entry-1:2"],
        )

    def test_date_picker_keyboard_lists_last_seven_days_with_exit_paths(self):
        keyboard = bot._date_picker_keyboard("entry-1", selected_date=bot._default_entry_date())
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(
            [data for data in callback_data if data.startswith("set_date:entry-1:")],
            [f"set_date:entry-1:{entry_date}" for entry_date in bot._entry_date_options()],
        )
        self.assertEqual(callback_data[-2:], ["back_to_preview:entry-1", "cancel:entry-1"])

    def test_entry_date_options_use_configured_diary_day(self):
        with patch.object(bot, "diary_today", return_value=date(2026, 6, 21)):
            self.assertEqual(bot._default_entry_date(), "2026-06-21")
            self.assertEqual(
                bot._entry_date_options(),
                [
                    "2026-06-21",
                    "2026-06-20",
                    "2026-06-19",
                    "2026-06-18",
                    "2026-06-17",
                    "2026-06-16",
                    "2026-06-15",
                ],
            )

    def test_duplicate_voice_keyboard_scopes_actions_to_message_key(self):
        keyboard = bot._duplicate_voice_keyboard("123:10")
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(callback_data, ["add_duplicate:123:10", "cancel_duplicate:123:10"])

    def test_retry_processing_keyboard_scopes_action_to_message_key(self):
        keyboard = bot._retry_processing_keyboard("123:10")
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(callback_data, ["retry_process:123:10"])

    def test_callback_payload_parses_action_and_entry_id(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="save:entry-1"))

        self.assertEqual(bot._callback_payload(update), ("save", "entry-1"))

    def test_callback_payload_ignores_date_value_when_parsing_entry_id(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="set_date:entry-1:2026-06-08"))

        self.assertEqual(bot._callback_payload(update), ("set_date", "entry-1"))
        self.assertEqual(bot._callback_value(update), "2026-06-08")

    def test_callback_payload_rejects_unscoped_data(self):
        update = SimpleNamespace(callback_query=SimpleNamespace(data="save"))

        self.assertEqual(bot._callback_payload(update), (None, None))

    def test_telegram_message_url_prefers_native_message_link(self):
        message = SimpleNamespace(
            chat_id=-100123,
            message_id=10,
            link="https://t.me/c/123/10",
        )

        self.assertEqual(bot._telegram_message_url(message), "https://t.me/c/123/10")

    def test_telegram_message_url_builds_clickable_bot_deeplink_for_private_chat(self):
        message = SimpleNamespace(chat_id=123, message_id=10)

        self.assertEqual(
            bot._telegram_message_url(message, "diary_bot"),
            "https://t.me/diary_bot?start=src_123_10",
        )

    def test_telegram_message_url_falls_back_to_private_chat_protocol_link_without_bot_username(self):
        self.assertEqual(
            bot._telegram_message_url_from_ids(123, 10),
            "tg://openmessage?user_id=123&message_id=10",
        )

    def test_telegram_message_url_builds_private_supergroup_web_link_from_chat_id(self):
        self.assertEqual(
            bot._telegram_message_url_from_ids(-1009876543210, 77),
            "https://t.me/c/9876543210/77",
        )

    def test_entry_metadata_uses_voice_file_facts_for_deduplication(self):
        metadata = bot._entry_metadata({
            "kind": "voice",
            "chat_id": 123,
            "message_id": 10,
            "source_message_url": "tg://openmessage?user_id=123&message_id=10",
            "file_unique_id": "voice-unique",
            "duration": 42,
            "file_size": 1000,
        }, "transcribed text")

        self.assertEqual(metadata, {
            "source": "voice",
            "telegram_chat_id": 123,
            "telegram_message_id": 10,
            "source_message_url": "tg://openmessage?user_id=123&message_id=10",
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
        self.assertEqual(metadata["source_message_url"], "tg://openmessage?user_id=123&message_id=10")
        self.assertEqual(metadata["source_text_hash"], bot._source_text_hash("exact text"))

    def test_entry_metadata_uses_bot_deeplink_for_private_chat_when_username_is_available(self):
        metadata = bot._entry_metadata({
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
        }, "exact text", bot_username="@diary_bot")

        self.assertEqual(metadata["source_message_url"], "https://t.me/diary_bot?start=src_123_10")

    def test_entry_metadata_upgrades_stored_protocol_link_when_bot_username_is_available(self):
        metadata = bot._entry_metadata({
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
            "source_message_url": "tg://openmessage?user_id=123&message_id=10",
        }, "exact text", bot_username="diary_bot")

        self.assertEqual(metadata["source_message_url"], "https://t.me/diary_bot?start=src_123_10")


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

    async def test_start_source_deeplink_sends_reply_to_original_message(self):
        fake_bot = FakeSendBot()
        source_message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=source_message)
        fake_context = SimpleNamespace(bot=fake_bot, args=["src_123_456"])

        await bot.handle_start(update, fake_context)

        self.assertEqual(len(fake_bot.sent_messages), 1)
        sent = fake_bot.sent_messages[0]
        self.assertEqual(sent["chat_id"], 123)
        self.assertEqual(sent["text"], "Source message")
        self.assertEqual(sent["reply_parameters"].message_id, 456)
        self.assertFalse(sent["reply_parameters"].allow_sending_without_reply)
        source_message.reply_text.assert_not_awaited()


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

        fake_formatter = AsyncMock(return_value=("Title", "Body", ["work"]))
        with (
            patch.object(bot, "format_entry", new=fake_formatter),
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

        entry_date = bot._default_entry_date()
        fake_formatter.assert_awaited_once_with("raw transcription")
        self.assertEqual(len(fake_context.bot.edits), 1)
        edit = fake_context.bot.edits[0]
        self.assertEqual(edit["chat_id"], 123)
        self.assertEqual(edit["message_id"], 20)
        self.assertEqual(edit["text"], bot._preview_text("Title", "raw transcription", ["work"], entry_date))
        self.assertEqual(edit["parse_mode"], "HTML")
        self.assertEqual(fake_state_store.marked_drafted, [("123:10", "entry-1")])
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_msg_id"], 20)
        self.assertEqual(fake_state_store.saved_drafts[0]["entry_date"], entry_date)
        self.assertEqual(fake_state_store.saved_drafts[0]["raw_text"], "raw transcription")
        self.assertEqual(fake_state_store.saved_drafts[0]["formatted_text"], "Body")
        self.assertFalse(fake_state_store.saved_drafts[0]["formatted"])
        self.assertEqual(
            fake_state_store.saved_drafts[0]["metadata"]["source_message_url"],
            "https://t.me/diary_bot?start=src_123_10",
        )
        self.assertEqual(fake_state_store.saved_drafts[0]["metadata"]["voice_file_unique_id"], "voice-unique")
        self.assertFalse(fake_state_store.saved_drafts[0]["allow_duplicate"])
        self.assertIn("entry-1", fake_context.user_data[bot.DRAFTS_KEY])

    async def test_create_preview_sends_new_reply_when_no_processing_message_exists(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeSendBot(), user_data={})
        source_message = SimpleNamespace(
            chat_id=123,
            message_id=10,
            get_bot=lambda: fake_context.bot,
        )

        fake_formatter = AsyncMock(return_value=("Title", "Body", []))
        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-2"),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._create_preview(source_message, fake_context, "plain text")

        fake_formatter.assert_awaited_once_with("plain text")
        self.assertEqual(len(fake_context.bot.sent_messages), 1)
        reply_parameters = fake_context.bot.sent_messages[0]["reply_parameters"]
        self.assertEqual(reply_parameters.message_id, 10)
        self.assertTrue(reply_parameters.allow_sending_without_reply)
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_msg_id"], 999)

    async def test_create_preview_keeps_full_text_when_telegram_preview_is_truncated(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        source_message = SimpleNamespace(chat_id=123, message_id=10)
        processing_message = SimpleNamespace(chat_id=123, message_id=20)
        long_text = "x" * (bot.TELEGRAM_MESSAGE_LIMIT + 500)
        fake_formatter = AsyncMock(return_value=("Title", "Formatted", []))

        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-long"),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._create_preview(
                source_message,
                fake_context,
                long_text,
                message_key="123:10",
                preview_message=processing_message,
            )

        edit_text = fake_context.bot.edits[0]["text"]
        keyboard = fake_context.bot.edits[0]["reply_markup"]
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertLessEqual(len(edit_text), bot.TELEGRAM_MESSAGE_LIMIT)
        self.assertIn("Preview truncated", edit_text)
        self.assertIn("Page 1/", edit_text)
        self.assertEqual(callback_data[:2], ["preview_page:entry-long:0", "preview_page:entry-long:1"])
        self.assertEqual(fake_state_store.saved_drafts[0]["text"], long_text)
        self.assertEqual(fake_state_store.saved_drafts[0]["raw_text"], long_text)
        self.assertEqual(fake_state_store.saved_drafts[0]["formatted_text"], "Formatted")
        self.assertEqual(fake_state_store.saved_drafts[0]["preview_page"], 0)

    async def test_create_preview_hides_format_when_formatted_text_matches_raw_text(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        source_message = SimpleNamespace(chat_id=123, message_id=10)
        processing_message = SimpleNamespace(chat_id=123, message_id=20)
        fake_formatter = AsyncMock(return_value=("Title", "raw transcription", []))

        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "_new_entry_id", return_value="entry-raw"),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._create_preview(
                source_message,
                fake_context,
                "raw transcription",
                message_key="123:10",
                preview_message=processing_message,
            )

        keyboard = fake_context.bot.edits[0]["reply_markup"]
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertNotIn("format:entry-raw", callback_data)


class DuplicateVoiceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_voice_warns_and_waits_when_voice_was_already_saved(self):
        fake_state_store = FakeStateStore()
        fake_state_store.duplicate_voice = {"key": "123:10", "status": "saved"}
        fake_context = SimpleNamespace(
            bot=FakeSendBot(),
            application=FakeApplication(),
            user_data={},
        )
        voice = SimpleNamespace(
            file_id="file-2",
            file_unique_id="voice-unique",
            duration=42,
            file_size=1000,
        )
        message = SimpleNamespace(
            chat_id=123,
            message_id=11,
            voice=voice,
            date=None,
            get_bot=lambda: fake_context.bot,
        )
        update = SimpleNamespace(effective_message=message)

        with patch.object(bot, "state_store", fake_state_store):
            await bot.handle_voice(update, fake_context)

        self.assertEqual(fake_state_store.marked_duplicate_pending, [("123:11", "123:10")])
        self.assertEqual(fake_context.application.created_tasks, [])
        self.assertIn("already been added", fake_context.bot.sent_messages[0]["text"])
        keyboard = fake_context.bot.sent_messages[0]["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "add_duplicate:123:11")

    async def test_duplicate_callback_confirms_and_starts_processing(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:11"] = {
            "key": "123:11",
            "kind": "voice",
            "chat_id": 123,
            "message_id": 11,
        }
        fake_context = SimpleNamespace(
            bot=FakeSendBot(),
            application=FakeApplication(close_coroutines=True),
            user_data={},
        )
        fake_query = FakeQuery(data="add_duplicate:123:11")
        update = SimpleNamespace(callback_query=fake_query)

        with (
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_process_message_record", new=AsyncMock()),
        ):
            await bot.duplicate_callback(update, fake_context)

        self.assertEqual(fake_state_store.marked_duplicate_confirmed, ["123:11"])
        self.assertEqual(fake_query.edits[0]["text"], "Adding this voice message anyway...")
        self.assertEqual(len(fake_context.application.created_tasks), 1)


class RetryProcessingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_text_processing_shows_retry_button(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:10"] = {
            "key": "123:10",
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
            "text": "raw text",
        }
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        status_message = SimpleNamespace(chat_id=123, message_id=20)

        with (
            patch.object(bot, "format_entry", new=AsyncMock(side_effect=RuntimeError("formatter failed"))),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot.logger, "exception"),
        ):
            await bot._process_text_record(
                fake_state_store.messages["123:10"],
                SimpleNamespace(chat_id=123, message_id=10),
                fake_context,
                status_message=status_message,
            )

        self.assertEqual(fake_state_store.marked_failed, [("123:10", "formatter failed")])
        self.assertEqual(fake_context.bot.edits[0]["text"], "Preparing preview...")
        self.assertIn("Error: formatter failed", fake_context.bot.edits[1]["text"])
        keyboard = fake_context.bot.edits[1]["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "retry_process:123:10")

    async def test_retry_processing_callback_restarts_message_processing(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:10"] = {
            "key": "123:10",
            "kind": "text",
            "status": "failed",
            "chat_id": 123,
            "message_id": 10,
            "text": "raw text",
        }
        fake_context = SimpleNamespace(
            bot=FakeSendBot(),
            application=FakeApplication(close_coroutines=True),
            user_data={},
        )
        fake_query = FakeQuery(data="retry_process:123:10")
        update = SimpleNamespace(callback_query=fake_query)
        fake_processor = AsyncMock()

        with (
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot, "_process_message_record", new=fake_processor),
        ):
            await bot.retry_processing_callback(update, fake_context)

        self.assertEqual(fake_query.edits[0]["text"], "Retrying...")
        self.assertEqual(len(fake_context.application.created_tasks), 1)
        fake_processor.assert_called_once()
        args, kwargs = fake_processor.call_args
        self.assertEqual(args[0], "123:10")
        self.assertEqual(args[1].chat_id, 123)
        self.assertEqual(args[1].message_id, 10)
        self.assertIs(args[2], fake_context)
        self.assertIs(kwargs["status_message"], fake_query.message)


class FormatDraftFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_format_draft_applies_stored_formatted_text_only(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "raw transcription",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": False,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }
        fake_formatter = AsyncMock(return_value=("Other", "Other body", []))

        with (
            patch.object(bot, "format_entry", new=fake_formatter),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._format_draft(fake_query, fake_context, draft)

        fake_formatter.assert_not_awaited()
        self.assertEqual(draft["title"], "Title")
        self.assertEqual(draft["text"], "formatted body")
        self.assertEqual(draft["tags"], ["work"])
        self.assertTrue(draft["formatted"])
        self.assertEqual(fake_state_store.saved_drafts[-1]["raw_text"], "raw transcription")
        self.assertEqual(
            fake_context.bot.edits[0]["text"],
            bot._preview_text("Title", "formatted body", ["work"], draft["entry_date"]),
        )

    async def test_formatted_draft_keyboard_offers_original_instead_of_format(self):
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "formatted body",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": True,
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
        }

        keyboard = bot._preview_keyboard_for_draft(draft)
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertIn("unformat:entry-1", callback_data)
        self.assertNotIn("format:entry-1", callback_data)

    async def test_format_then_unformat_round_trip_toggles_buttons(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "raw transcription",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": False,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }

        def callbacks():
            keyboard = bot._preview_keyboard_for_draft(draft)
            return [
                button.callback_data
                for row in keyboard.inline_keyboard
                for button in row
            ]

        with patch.object(bot, "state_store", fake_state_store):
            self.assertIn("format:entry-1", callbacks())
            await bot._format_draft(fake_query, fake_context, draft)
            self.assertEqual(draft["text"], "formatted body")
            self.assertIn("unformat:entry-1", callbacks())

            await bot._unformat_draft(fake_query, fake_context, draft)
            self.assertEqual(draft["text"], "raw transcription")
            self.assertIn("format:entry-1", callbacks())

            await bot._format_draft(fake_query, fake_context, draft)
            self.assertEqual(draft["text"], "formatted body")
            self.assertTrue(draft["formatted"])

    async def test_unformat_draft_warns_when_already_original(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "raw transcription",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": False,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }

        with patch.object(bot, "state_store", fake_state_store):
            await bot._unformat_draft(fake_query, fake_context, draft)

        fake_query.message.reply_text.assert_awaited_once()
        self.assertEqual(fake_context.bot.edits, [])
        self.assertEqual(fake_state_store.saved_drafts, [])

    async def test_unformat_draft_restores_raw_text(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        fake_query = FakeQuery()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "formatted body",
            "raw_text": "raw transcription",
            "formatted_text": "formatted body",
            "formatted": True,
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }

        with patch.object(bot, "state_store", fake_state_store):
            await bot._unformat_draft(fake_query, fake_context, draft)

        self.assertEqual(draft["text"], "raw transcription")
        self.assertFalse(draft["formatted"])
        self.assertEqual(draft["preview_page"], 0)
        self.assertEqual(fake_state_store.saved_drafts[-1]["text"], "raw transcription")
        self.assertEqual(
            fake_context.bot.edits[0]["text"],
            bot._preview_text("Title", "raw transcription", ["work"], draft["entry_date"]),
        )


class DatePickerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_entry_date_persists_and_returns_to_preview(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        selected_date = bot._entry_date_options()[1]
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": bot._default_entry_date(),
        }
        update = SimpleNamespace(
            callback_query=SimpleNamespace(data=f"set_date:entry-1:{selected_date}")
        )

        with patch.object(bot, "state_store", fake_state_store):
            await bot._set_entry_date(update, fake_context, draft)

        self.assertEqual(draft["entry_date"], selected_date)
        self.assertEqual(fake_state_store.saved_drafts[-1]["entry_date"], selected_date)
        self.assertEqual(fake_context.bot.edits[0]["text"], bot._preview_text("Title", "Text", ["work"], selected_date))


class PreviewPageFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_preview_page_persists_and_edits_same_preview_message(self):
        fake_state_store = FakeStateStore()
        fake_context = SimpleNamespace(bot=FakeEditBot(), user_data={})
        entry_date = bot._default_entry_date()
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "\n".join(f"line {i:03d} " + "x" * 80 for i in range(120)),
            "tags": ["work"],
            "chat_id": 123,
            "preview_msg_id": 20,
            "entry_date": entry_date,
            "preview_page": 0,
        }
        update = SimpleNamespace(callback_query=SimpleNamespace(data="preview_page:entry-1:1"))

        with patch.object(bot, "state_store", fake_state_store):
            await bot._set_preview_page(update, fake_context, draft)

        self.assertEqual(draft["preview_page"], 1)
        self.assertEqual(fake_state_store.saved_drafts[-1]["preview_page"], 1)
        self.assertEqual(fake_context.bot.edits[0]["message_id"], 20)
        self.assertIn("Page 2/", fake_context.bot.edits[0]["text"])


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
            "entry_date": bot._default_entry_date(),
            "message_key": "123:10",
            "saving": False,
        }
        calls = []

        async def failing_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            calls.append((title, text, tags, metadata, entry_date, allow_duplicate))
            raise RuntimeError("notion timeout")

        with (
            patch.object(bot, "save_entry", new=failing_save_entry),
            patch.object(bot, "state_store", fake_state_store),
            patch.object(bot.logger, "exception"),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertFalse(draft["saving"])
        self.assertEqual(calls[0][-2], draft["entry_date"])
        self.assertFalse(calls[0][-1])
        self.assertEqual(fake_state_store.saved_drafts[-1]["id"], "entry-1")
        self.assertEqual(fake_query.edits[0]["text"], "Saving to Notion...")
        self.assertIn("Not saved to Notion: notion timeout", fake_query.edits[1]["text"])
        self.assertIn("Press Save to retry", fake_query.edits[1]["text"])
        self.assertIsNotNone(fake_query.edits[1].get("reply_markup"))

    async def test_save_draft_keeps_draft_and_offers_add_anyway_when_duplicate_found(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={bot.DRAFTS_KEY: {}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
            "metadata": {"source": "voice"},
            "message_key": "123:10",
            "saving": False,
        }

        async def duplicate_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            return SimpleNamespace(created=False)

        with (
            patch.object(bot, "save_entry", new=duplicate_save_entry),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertFalse(draft["saving"])
        self.assertEqual(fake_state_store.saved_drafts[-1]["id"], "entry-1")
        self.assertIn("voice message has already been added", fake_query.edits[1]["text"])
        keyboard = fake_query.edits[1]["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "save_anyway:entry-1")

    async def test_save_draft_passes_allow_duplicate_when_confirmed(self):
        fake_state_store = FakeStateStore()
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(user_data={bot.DRAFTS_KEY: {"entry-1": {}}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
            "message_key": "123:10",
            "saving": False,
            "allow_duplicate": True,
        }
        calls = []

        async def successful_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            calls.append((title, text, tags, metadata, entry_date, allow_duplicate))
            return SimpleNamespace(created=True)

        with (
            patch.object(bot, "save_entry", new=successful_save_entry),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertTrue(calls[0][-1])
        self.assertEqual(fake_state_store.marked_saved, ["123:10"])

    async def test_save_draft_enriches_old_draft_metadata_with_clickable_source_url(self):
        fake_state_store = FakeStateStore()
        fake_state_store.messages["123:10"] = {
            "key": "123:10",
            "kind": "text",
            "chat_id": 123,
            "message_id": 10,
        }
        fake_query = FakeQuery()
        fake_context = SimpleNamespace(bot=FakeSendBot(), user_data={bot.DRAFTS_KEY: {"entry-1": {}}})
        draft = {
            "id": "entry-1",
            "title": "Title",
            "text": "Text",
            "tags": ["work"],
            "entry_date": bot._default_entry_date(),
            "message_key": "123:10",
            "saving": False,
        }
        calls = []

        async def successful_save_entry(title, text, tags, metadata=None, entry_date=None, allow_duplicate=False):
            calls.append((title, text, tags, metadata, entry_date, allow_duplicate))
            return SimpleNamespace(created=True)

        with (
            patch.object(bot, "save_entry", new=successful_save_entry),
            patch.object(bot, "state_store", fake_state_store),
        ):
            await bot._save_draft(fake_query, fake_context, "entry-1", draft)

        self.assertEqual(calls[0][3]["source_message_url"], "https://t.me/diary_bot?start=src_123_10")
        self.assertEqual(calls[0][3]["source_text_hash"], bot._source_text_hash("Text"))


class StatCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_stat_sends_formatted_audio_stats(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message)

        async def fake_build_audio_stats():
            return "stats"

        with (
            patch.object(bot, "build_audio_stats", fake_build_audio_stats),
            patch.object(bot, "format_audio_stats", return_value="*Аудио статистика*"),
        ):
            await bot.handle_stat(update, SimpleNamespace())

        self.assertEqual(message.reply_text.await_args_list[0].args, ("Counting saved audio stats...",))
        self.assertEqual(message.reply_text.await_args_list[1].args, ("*Аудио статистика*",))
        self.assertEqual(message.reply_text.await_args_list[1].kwargs, {"parse_mode": "Markdown"})


class MainRegistrationTests(unittest.TestCase):
    def test_main_restricts_all_commands_to_allowed_user(self):
        fake_app = FakePollingApplication()

        with patch.object(bot, "ApplicationBuilder", return_value=FakeApplicationBuilder(fake_app)):
            bot.main()

        command_handlers = [
            handler for handler in fake_app.handlers
            if isinstance(handler, CommandHandler)
        ]
        command_filters = {
            next(iter(handler.commands)): handler.filters
            for handler in command_handlers
        }

        self.assertEqual(set(command_filters), {"start", "help", "weekly", "stat"})
        for command, command_filter in command_filters.items():
            with self.subTest(command=command):
                self.assertEqual(command_filter.user_ids, frozenset({bot.settings.allowed_user_id}))


class FakeSendBot:
    def __init__(self):
        self.sent_messages = []
        self.username = "diary_bot"

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
        self.username = "diary_bot"

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(
            chat_id=kwargs["chat_id"],
            message_id=kwargs["message_id"],
            get_bot=lambda: self,
        )


class FakeQuery:
    def __init__(self, data=None):
        self.edits = []
        self.data = data
        self.message = SimpleNamespace(chat_id=123, message_id=20, reply_text=AsyncMock())

    async def answer(self):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, **kwargs})


class FakeApplication:
    def __init__(self, close_coroutines=False):
        self.created_tasks = []
        self.close_coroutines = close_coroutines

    def create_task(self, coroutine, **kwargs):
        self.created_tasks.append((coroutine, kwargs))
        if self.close_coroutines:
            coroutine.close()


class FakePollingApplication:
    def __init__(self):
        self.handlers = []
        self.job_queue = FakeJobQueue()
        self.polling_started = False

    def add_handler(self, handler):
        self.handlers.append(handler)

    def run_polling(self):
        self.polling_started = True


class FakeJobQueue:
    def __init__(self):
        self.daily_jobs = []

    def run_daily(self, *args, **kwargs):
        self.daily_jobs.append((args, kwargs))


class FakeApplicationBuilder:
    def __init__(self, app):
        self.app = app
        self.token_value = None
        self.defaults_value = None
        self.concurrent_updates_value = None
        self.post_init_callback = None

    def token(self, value):
        self.token_value = value
        return self

    def defaults(self, value):
        self.defaults_value = value
        return self

    def concurrent_updates(self, value):
        self.concurrent_updates_value = value
        return self

    def post_init(self, callback):
        self.post_init_callback = callback
        return self

    def build(self):
        return self.app


class FakeStateStore:
    def __init__(self):
        self.messages = {}
        self.saved_drafts = []
        self.marked_processing = []
        self.marked_failed = []
        self.marked_drafted = []
        self.marked_cancelled = []
        self.marked_duplicate_pending = []
        self.marked_duplicate_confirmed = []
        self.marked_saved = []
        self.removed_drafts = []
        self.duplicate_voice = None

    def record_voice(
        self,
        chat_id,
        message_id,
        file_id,
        date,
        file_unique_id=None,
        duration=None,
        file_size=None,
        source_message_url=None,
    ):
        key = f"{chat_id}:{message_id}"
        self.messages[key] = {
            "key": key,
            "kind": "voice",
            "chat_id": chat_id,
            "message_id": message_id,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "duration": duration,
            "file_size": file_size,
            "source_message_url": source_message_url,
            "date": date,
        }
        return key

    def find_duplicate_voice(self, file_unique_id, duration=None, file_size=None, exclude_key=None):
        return self.duplicate_voice

    def get_message(self, key):
        return self.messages.get(key)

    def save_draft(self, draft):
        self.saved_drafts.append(dict(draft))

    def mark_message_processing(self, key):
        self.marked_processing.append(key)
        self.messages[key]["status"] = "processing"

    def mark_message_failed(self, key, error):
        self.marked_failed.append((key, error))
        self.messages[key]["status"] = "failed"
        self.messages[key]["error"] = error

    def mark_message_drafted(self, key, entry_id):
        self.marked_drafted.append((key, entry_id))

    def mark_message_duplicate_pending(self, key, duplicate_key):
        self.marked_duplicate_pending.append((key, duplicate_key))

    def mark_message_duplicate_confirmed(self, key):
        self.marked_duplicate_confirmed.append(key)
        self.messages[key]["allow_duplicate"] = True

    def mark_message_saved(self, key):
        self.marked_saved.append(key)

    def mark_message_cancelled(self, key):
        self.marked_cancelled.append(key)

    def remove_draft(self, entry_id):
        self.removed_drafts.append(entry_id)
