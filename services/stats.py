from dataclasses import dataclass
from datetime import date, datetime, timedelta
import zoneinfo

from config import settings
from services.notion import AUDIO_DURATION_PROPERTY, CREATED_PROPERTY, get_diary_pages


STAT_DAYS = 7
STAT_MONTHS = 6
MONTH_NAMES_RU = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}
MONTH_GENITIVE_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


@dataclass(frozen=True)
class AudioRecord:
    entry_date: date
    duration_seconds: int


@dataclass(frozen=True)
class AudioBucket:
    label: str
    count: int
    seconds: int


@dataclass(frozen=True)
class PeriodStats:
    entry_count: int
    voice_count: int
    audio_seconds: int
    busiest_day: AudioBucket | None = None


@dataclass(frozen=True)
class AudioStats:
    total: AudioBucket
    week: AudioBucket
    daily: list[AudioBucket]
    monthly: list[AudioBucket]


def _local_today() -> date:
    tz = zoneinfo.ZoneInfo(settings.timezone)
    return datetime.now(tz).date()


def _page_date(page: dict) -> date | None:
    prop = page.get("properties", {}).get(CREATED_PROPERTY, {})
    value = prop.get("date", {}).get("start")
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _page_audio_seconds(page: dict) -> int | None:
    value = page.get("properties", {}).get(AUDIO_DURATION_PROPERTY, {}).get("number")
    if value is None:
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _audio_records(pages: list[dict]) -> list[AudioRecord]:
    records = []
    for page in pages:
        entry_date = _page_date(page)
        seconds = _page_audio_seconds(page)
        if entry_date and seconds:
            records.append(AudioRecord(entry_date=entry_date, duration_seconds=seconds))
    return records


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _date_label(value: date) -> str:
    return f"{value.day} {MONTH_GENITIVE_RU[value.month]}"


def _month_label(value: date) -> str:
    return f"{MONTH_NAMES_RU[value.month]} {value.year}"


def _bucket(label: str, records: list[AudioRecord]) -> AudioBucket:
    return AudioBucket(
        label=label,
        count=len(records),
        seconds=sum(record.duration_seconds for record in records),
    )


def build_audio_stats_from_pages(pages: list[dict], today: date | None = None) -> AudioStats:
    today = today or _local_today()
    records = _audio_records(pages)
    week_start = today - timedelta(days=STAT_DAYS - 1)
    month_start = _add_months(_month_start(today), -(STAT_MONTHS - 1))

    daily = []
    for offset in range(STAT_DAYS):
        current_day = week_start + timedelta(days=offset)
        daily_records = [record for record in records if record.entry_date == current_day]
        daily.append(_bucket(_date_label(current_day), daily_records))

    monthly = []
    for offset in range(STAT_MONTHS):
        current_month = _add_months(month_start, offset)
        next_month = _add_months(current_month, 1)
        month_records = [
            record
            for record in records
            if current_month <= record.entry_date < next_month
        ]
        monthly.append(_bucket(_month_label(current_month), month_records))

    week_records = [
        record
        for record in records
        if week_start <= record.entry_date <= today
    ]
    return AudioStats(
        total=_bucket("все время", records),
        week=_bucket("последние 7 дней", week_records),
        daily=daily,
        monthly=monthly,
    )


async def build_audio_stats(today: date | None = None) -> AudioStats:
    pages = await get_diary_pages()
    return build_audio_stats_from_pages(pages, today=today)


def build_period_stats_from_pages(pages: list[dict]) -> PeriodStats:
    records = _audio_records(pages)
    day_buckets = {}
    for record in records:
        day_buckets.setdefault(record.entry_date, []).append(record)

    busiest_day = None
    if day_buckets:
        buckets = [
            _bucket(_date_label(day), day_records)
            for day, day_records in day_buckets.items()
        ]
        busiest_day = max(buckets, key=lambda bucket: (bucket.seconds, bucket.count))

    return PeriodStats(
        entry_count=len(pages),
        voice_count=len(records),
        audio_seconds=sum(record.duration_seconds for record in records),
        busiest_day=busiest_day,
    )


def _rounded_minutes(seconds: int) -> int:
    if seconds <= 0:
        return 0
    return max(1, (seconds + 30) // 60)


def format_duration(seconds: int) -> str:
    minutes = _rounded_minutes(seconds)
    if minutes == 0:
        return "0 мин"
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} ч {minutes:02d} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def _audio_label(value: int) -> str:
    return f"{value} аудио"


def _bucket_line(bucket: AudioBucket) -> str:
    return f"- {bucket.label}: {format_duration(bucket.seconds)} · {_audio_label(bucket.count)}"


def format_audio_stats(stats: AudioStats) -> str:
    return "\n".join([
        "*Аудио статистика*",
        "",
        f"Всего: {format_duration(stats.total.seconds)} · {_audio_label(stats.total.count)}",
        f"За неделю: {format_duration(stats.week.seconds)} · {_audio_label(stats.week.count)}",
        "",
        "*По дням за последние 7 дней*",
        *[_bucket_line(bucket) for bucket in stats.daily],
        "",
        "*По месяцам за последние 6 месяцев*",
        *[_bucket_line(bucket) for bucket in stats.monthly],
    ])


def format_daily_stats(stats: PeriodStats) -> str:
    return "\n".join([
        "*Цифры дня*",
        f"Записи: {stats.entry_count}",
        f"Аудио: {format_duration(stats.audio_seconds)} · {_audio_label(stats.voice_count)}",
    ])


def format_weekly_stats(stats: PeriodStats) -> str:
    lines = [
        "*Цифры недели*",
        f"Записи: {stats.entry_count}",
        f"Аудио: {format_duration(stats.audio_seconds)} · {_audio_label(stats.voice_count)}",
    ]
    if stats.busiest_day:
        lines.append(
            f"Самый насыщенный день: {stats.busiest_day.label}, "
            f"{format_duration(stats.busiest_day.seconds)}"
        )
    return "\n".join(lines)
