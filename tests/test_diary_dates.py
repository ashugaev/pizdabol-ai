import os
import unittest
from datetime import date, datetime
from unittest.mock import patch
import zoneinfo

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import diary_dates


class DiaryDateTests(unittest.TestCase):
    def test_diary_today_moves_early_morning_to_previous_day(self):
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        with (
            patch.object(diary_dates.settings, "timezone", "Europe/Moscow"),
            patch.object(diary_dates.settings, "diary_day_start_hour", 4),
        ):
            self.assertEqual(
                diary_dates.diary_today(datetime(2026, 6, 22, 3, 59, tzinfo=tz)),
                date(2026, 6, 21),
            )
            self.assertEqual(
                diary_dates.diary_today(datetime(2026, 6, 22, 4, 0, tzinfo=tz)),
                date(2026, 6, 22),
            )
