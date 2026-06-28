import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import roast


def _text_response(*texts):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text) for text in texts]
    )


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeAnthropic:
    def __init__(self, response):
        self.messages = FakeMessages(response)


class RoastServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_roast_uses_configured_model_default_prompt_and_chain(self):
        fake = FakeAnthropic(_text_response("Разъёб готов."))
        chain = [{"role": "user", "content": "сегодня ничего не успел"}]

        with patch.object(roast.settings, "anthropic_api_key", "key"), \
                patch.object(roast, "_client", fake):
            result = await roast.roast(chain)

        self.assertEqual(result, "Разъёб готов.")
        kwargs = fake.messages.calls[0]
        self.assertEqual(kwargs["model"], roast.settings.anthropic_model)
        self.assertEqual(kwargs["max_tokens"], roast.ROAST_MAX_TOKENS)
        self.assertEqual(kwargs["system"], roast.DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(kwargs["messages"], chain)

    async def test_roast_honors_env_system_prompt_override(self):
        fake = FakeAnthropic(_text_response("ok"))

        with patch.object(roast.settings, "anthropic_api_key", "key"), \
                patch.object(roast.settings, "roast_system_prompt", "Кастомный психотерапевт"), \
                patch.object(roast, "_client", fake):
            await roast.roast([{"role": "user", "content": "x"}])

        self.assertEqual(fake.messages.calls[0]["system"], "Кастомный психотерапевт")

    async def test_roast_concatenates_multiple_text_blocks(self):
        fake = FakeAnthropic(_text_response("Первая часть.", "Вторая часть."))

        with patch.object(roast.settings, "anthropic_api_key", "key"), \
                patch.object(roast, "_client", fake):
            result = await roast.roast([{"role": "user", "content": "x"}])

        self.assertEqual(result, "Первая часть.\nВторая часть.")

    async def test_roast_trims_long_alternating_chain_and_keeps_user_first(self):
        fake = FakeAnthropic(_text_response("ok"))
        # Realistic alternating chain (user, assistant, user, ...) long enough to trim.
        chain = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(roast.MAX_CONVERSATION_MESSAGES + 11)
        ]

        with patch.object(roast.settings, "anthropic_api_key", "key"), \
                patch.object(roast, "_client", fake):
            await roast.roast(chain)

        sent = fake.messages.calls[0]["messages"]
        self.assertLessEqual(len(sent), roast.MAX_CONVERSATION_MESSAGES)
        # First message must be a user turn or Anthropic rejects the request.
        self.assertEqual(sent[0]["role"], "user")
        self.assertEqual(sent[-1], chain[-1])

    async def test_roast_raises_when_response_is_empty(self):
        fake = FakeAnthropic(_text_response())

        with patch.object(roast.settings, "anthropic_api_key", "key"), \
                patch.object(roast, "_client", fake):
            with self.assertRaisesRegex(RuntimeError, "empty response"):
                await roast.roast([{"role": "user", "content": "x"}])

    async def test_roast_raises_when_not_configured(self):
        with patch.object(roast.settings, "anthropic_api_key", ""):
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY is not configured"):
                await roast.roast([{"role": "user", "content": "x"}])

    def test_is_configured_reflects_api_key(self):
        with patch.object(roast.settings, "anthropic_api_key", "key"):
            self.assertTrue(roast.is_configured())
        with patch.object(roast.settings, "anthropic_api_key", ""):
            self.assertFalse(roast.is_configured())


if __name__ == "__main__":
    unittest.main()
