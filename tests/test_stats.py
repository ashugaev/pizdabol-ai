import os
import unittest
from datetime import date

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NOTION_TOKEN", "test-notion-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-notion-db")
os.environ.setdefault("ALLOWED_USER_ID", "1")

from services import stats


class StatsFormattingTests(unittest.TestCase):
    def test_build_audio_stats_groups_total_week_days_and_months(self):
        pages = [
            audio_page("2026-06-23", 120),
            audio_page("2026-06-22", 3600),
            audio_page("2026-06-17", 30),
            audio_page("2026-05-10", 180),
            audio_page("2026-01-01", 60),
            audio_page("2025-12-31", 60),
            audio_page("2026-06-21", None),
        ]

        result = stats.build_audio_stats_from_pages(pages, today=date(2026, 6, 23))

        self.assertEqual(result.total.count, 6)
        self.assertEqual(result.total.seconds, 4050)
        self.assertEqual(result.week.count, 3)
        self.assertEqual(result.week.seconds, 3750)
        self.assertEqual(
            [(bucket.label, bucket.count, bucket.seconds) for bucket in result.daily],
            [
                ("17 июня", 1, 30),
                ("18 июня", 0, 0),
                ("19 июня", 0, 0),
                ("20 июня", 0, 0),
                ("21 июня", 0, 0),
                ("22 июня", 1, 3600),
                ("23 июня", 1, 120),
            ],
        )
        self.assertEqual(
            [(bucket.label, bucket.count, bucket.seconds) for bucket in result.monthly],
            [
                ("январь 2026", 1, 60),
                ("февраль 2026", 0, 0),
                ("март 2026", 0, 0),
                ("апрель 2026", 0, 0),
                ("май 2026", 1, 180),
                ("июнь 2026", 3, 3750),
            ],
        )

    def test_format_audio_stats_is_user_readable(self):
        result = stats.build_audio_stats_from_pages(
            [audio_page("2026-06-23", 3660)],
            today=date(2026, 6, 23),
        )

        text = stats.format_audio_stats(result)

        self.assertIn("*Аудио статистика*", text)
        self.assertIn("Всего: 1 ч 01 мин · 1 аудио", text)
        self.assertIn("*По дням за последние 7 дней*", text)
        self.assertIn("- 23 июня: 1 ч 01 мин · 1 аудио", text)
        self.assertIn("*По месяцам за последние 6 месяцев*", text)

    def test_period_stats_counts_entries_audio_and_busiest_day(self):
        result = stats.build_period_stats_from_pages([
            audio_page("2026-06-22", 120),
            audio_page("2026-06-22", 180),
            audio_page("2026-06-23", 60),
            text_page("2026-06-23"),
        ])

        self.assertEqual(result.entry_count, 4)
        self.assertEqual(result.voice_count, 3)
        self.assertEqual(result.audio_seconds, 360)
        self.assertEqual(result.busiest_day.label, "22 июня")
        self.assertEqual(result.busiest_day.seconds, 300)
        self.assertEqual(
            stats.format_weekly_stats(result),
            "*Цифры недели*\n"
            "Записи: 4\n"
            "Аудио: 6 мин · 3 аудио\n"
            "Самый насыщенный день: 22 июня, 5 мин",
        )


class StatsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_audio_stats_fetches_all_pages_with_duration(self):
        calls = []

        async def fake_get_diary_pages(**kwargs):
            calls.append(kwargs)
            return [audio_page("2026-06-23", 120), text_page("2026-06-23")]

        original_get_diary_pages = stats.get_diary_pages
        stats.get_diary_pages = fake_get_diary_pages
        try:
            result = await stats.build_audio_stats(today=date(2026, 6, 23))
        finally:
            stats.get_diary_pages = original_get_diary_pages

        self.assertEqual(calls, [{}])
        self.assertEqual(result.total.count, 1)
        self.assertEqual(result.total.seconds, 120)


def audio_page(entry_date, duration):
    return {
        "properties": {
            "Created": {"type": "date", "date": {"start": entry_date}},
            "Audio Duration": {"type": "number", "number": duration},
        }
    }


def text_page(entry_date):
    return {
        "properties": {
            "Created": {"type": "date", "date": {"start": entry_date}},
        }
    }
