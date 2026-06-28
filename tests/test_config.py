import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

import config


class ConfigValidationTests(unittest.TestCase):
    def test_required_env_rejects_missing_or_blank_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing required environment variable: TELEGRAM_TOKEN"):
                config._required_env("TELEGRAM_TOKEN")

        with patch.dict(os.environ, {"TELEGRAM_TOKEN": "   "}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing required environment variable: TELEGRAM_TOKEN"):
                config._required_env("TELEGRAM_TOKEN")

    def test_required_int_rejects_non_integer_allowed_user_id(self):
        with patch.dict(os.environ, {"ALLOWED_USER_ID": "not-a-number"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ALLOWED_USER_ID must be an integer"):
                config._required_int("ALLOWED_USER_ID")

    def test_timezone_rejects_invalid_iana_timezone(self):
        with patch.dict(os.environ, {"TIMEZONE": "Mars/Olympus"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TIMEZONE must be a valid IANA timezone: Mars/Olympus"):
                config._timezone()

    def test_blank_anthropic_key_is_treated_as_unset(self):
        # Mirrors how _Settings loads ANTHROPIC_API_KEY: a blank/whitespace value
        # must collapse to "" so the roast button stays hidden.
        for raw in ("", "   "):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": raw}, clear=True):
                self.assertEqual(config._optional_env("ANTHROPIC_API_KEY", "").strip(), "")
