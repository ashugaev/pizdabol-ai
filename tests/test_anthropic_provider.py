import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import openai

from services import ai


class FakeMessages:
    def __init__(self, blocks):
        self.blocks = blocks
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.blocks)


class FakeAnthropic:
    def __init__(self, blocks):
        self.messages = FakeMessages(blocks)


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _anthropic_client(blocks):
    fake = FakeAnthropic(blocks)
    return ai._AnthropicChatClient(fake), fake


class CreateChatClientTests(unittest.TestCase):
    def test_default_provider_returns_openai_client(self):
        # The shared test process imports config in its default (openai) mode.
        self.assertEqual(ai.settings.ai_provider, "openai")
        self.assertIsInstance(ai.create_chat_client(), openai.AsyncOpenAI)


class AnthropicShimTests(unittest.IsolatedAsyncioTestCase):
    async def test_translates_call_and_adapts_response(self):
        client, fake = _anthropic_client([_text_block("hello world")])

        response = await client.chat.completions.create(
            model="claude-opus-4-8",
            max_completion_tokens=512,
            messages=[
                {"role": "system", "content": "You are a diary formatter."},
                {"role": "user", "content": "raw text"},
            ],
        )

        self.assertEqual(response.choices[0].message.content, "hello world")
        kwargs = fake.messages.calls[0]
        self.assertEqual(kwargs["model"], "claude-opus-4-8")
        self.assertEqual(kwargs["max_tokens"], 512)
        self.assertEqual(kwargs["system"], "You are a diary formatter.")
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "raw text"}])

    async def test_json_request_adds_directive_and_strips_fences(self):
        client, fake = _anthropic_client([_text_block('```json\n{"title":"T"}\n```')])

        response = await client.chat.completions.create(
            model="claude-opus-4-8",
            max_completion_tokens=1024,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Base prompt."},
                {"role": "user", "content": "payload"},
            ],
        )

        self.assertEqual(response.choices[0].message.content, '{"title":"T"}')
        system = fake.messages.calls[0]["system"]
        self.assertIn("Base prompt.", system)
        self.assertIn(ai._JSON_DIRECTIVE, system)

    async def test_ignores_reasoning_effort_and_joins_text_blocks(self):
        client, fake = _anthropic_client([_text_block("part one "), _text_block("part two")])

        response = await client.chat.completions.create(
            model="claude-opus-4-8",
            max_completion_tokens=4096,
            reasoning_effort="high",
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
        )

        self.assertEqual(response.choices[0].message.content, "part one part two")
        kwargs = fake.messages.calls[0]
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertEqual(
            kwargs["messages"],
            [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
        )

    async def test_omits_system_when_no_system_message(self):
        client, fake = _anthropic_client([_text_block("ok")])

        await client.chat.completions.create(
            model="claude-opus-4-8",
            max_completion_tokens=256,
            messages=[{"role": "user", "content": "only user"}],
        )

        self.assertNotIn("system", fake.messages.calls[0])


class AnthropicHelperTests(unittest.TestCase):
    def test_strip_json_fences_without_language_tag(self):
        self.assertEqual(ai._strip_json_fences('```\n{"a":1}\n```'), '{"a":1}')

    def test_strip_json_fences_plain_passthrough(self):
        self.assertEqual(ai._strip_json_fences('  {"a":1}  '), '{"a":1}')

    def test_extract_text_skips_non_text_blocks(self):
        blocks = [
            SimpleNamespace(type="thinking", thinking="hmm"),
            SimpleNamespace(type="text", text="answer"),
        ]
        self.assertEqual(ai._extract_text(SimpleNamespace(content=blocks)), "answer")


if __name__ == "__main__":
    unittest.main()
