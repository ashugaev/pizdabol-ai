from datetime import date, datetime, timedelta
import zoneinfo

from config import settings


def diary_today(now: datetime | None = None) -> date:
    tz = zoneinfo.ZoneInfo(settings.timezone)
    local_now = now.astimezone(tz) if now else datetime.now(tz)
    return (local_now - timedelta(hours=settings.diary_day_start_hour)).date()
