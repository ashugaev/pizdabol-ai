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


def _chat_response(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAI:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=FakeCompletions(response))


class RoastServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_roast_uses_configured_model_high_reasoning_and_chain(self):
        fake = FakeOpenAI(_chat_response("Roast ready."))
        chain = [{"role": "user", "content": "got nothing done today"}]

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", ""), \
                patch.object(roast, "client", fake):
            result = await roast.roast(chain)

        self.assertEqual(result, "Roast ready.")
        kwargs = fake.chat.completions.calls[0]
        self.assertEqual(kwargs["model"], roast.settings.openai_roast_model)
        self.assertEqual(kwargs["max_completion_tokens"], roast.ROAST_MAX_COMPLETION_TOKENS)
        self.assertEqual(kwargs["reasoning_effort"], roast.ROAST_REASONING_EFFORT)
        # System persona is prepended, then the diary chain follows verbatim.
        self.assertEqual(kwargs["messages"][0]["role"], "system")
        self.assertEqual(kwargs["messages"][0]["content"], roast.DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(kwargs["messages"][1:], chain)

    async def test_roast_honors_env_system_prompt_override(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", ""), \
                patch.object(roast.settings, "roast_system_prompt", "Custom persona"), \
                patch.object(roast, "client", fake):
            await roast.roast([{"role": "user", "content": "x"}])

        self.assertEqual(fake.chat.completions.calls[0]["messages"][0]["content"], "Custom persona")

    async def test_roast_appends_response_language_directive(self):
        fake = FakeOpenAI(_chat_response("ok"))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast.settings, "roast_language", "English"), \
                patch.object(roast, "client", fake):
            await roast.roast([{"role": "user", "content": "x"}])

        system = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertTrue(system.startswith(roast.DEFAULT_SYSTEM_PROMPT))
        self.assertIn("English", system)

    async def test_roast_trims_long_chain_to_limit_and_keeps_latest(self):
        fake = FakeOpenAI(_chat_response("ok"))
        chain = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(roast.MAX_CONVERSATION_MESSAGES + 11)
        ]

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            await roast.roast(chain)

        sent = fake.chat.completions.calls[0]["messages"]
        # System prompt plus at most MAX_CONVERSATION_MESSAGES diary turns.
        self.assertLessEqual(len(sent) - 1, roast.MAX_CONVERSATION_MESSAGES)
        self.assertEqual(sent[-1], chain[-1])

    async def test_roast_raises_when_response_is_empty(self):
        fake = FakeOpenAI(_chat_response(""))

        with patch.object(roast.settings, "openai_api_key", "key"), \
                patch.object(roast, "client", fake):
            with self.assertRaisesRegex(RuntimeError, "empty response"):
                await roast.roast([{"role": "user", "content": "x"}])

    async def test_roast_raises_when_not_configured(self):
        with patch.object(roast.settings, "openai_api_key", ""):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is not configured"):
                await roast.roast([{"role": "user", "content": "x"}])

    def test_is_configured_reflects_api_key(self):
        with patch.object(roast.settings, "openai_api_key", "key"):
            self.assertTrue(roast.is_configured())
        with patch.object(roast.settings, "openai_api_key", ""):
            self.assertFalse(roast.is_configured())


if __name__ == "__main__":
    unittest.main()
