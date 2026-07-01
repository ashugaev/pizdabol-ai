import os
import zoneinfo
from dotenv import load_dotenv

load_dotenv()

def _optional_env(name: str, default: str) -> str:
    return os.getenv(name) or default


def _optional_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _required_int(name: str) -> int:
    value = _required_env(name)
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _diary_day_start_hour() -> int:
    name = "DIARY_DAY_START_HOUR"
    value = os.getenv(name, "0").strip() or "0"
    try:
        hour = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer from 0 to 23") from exc
    if hour < 0 or hour > 23:
        raise RuntimeError(f"{name} must be an integer from 0 to 23")
    return hour


def _timezone() -> str:
    value = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
    try:
        zoneinfo.ZoneInfo(value)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"TIMEZONE must be a valid IANA timezone: {value}") from exc
    return value


class _Settings:
    telegram_token: str = _required_env("TELEGRAM_TOKEN")
    openai_api_key: str = _required_env("OPENAI_API_KEY")
    openai_transcription_model: str = _optional_env("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    openai_formatter_model: str = _optional_env("OPENAI_FORMATTER_MODEL", "gpt-5.4-mini")
    openai_summary_model: str = _optional_env("OPENAI_SUMMARY_MODEL", openai_formatter_model)
    notion_token: str = _required_env("NOTION_TOKEN")
    notion_database_id: str = _required_env("NOTION_DATABASE_ID")
    allowed_user_id: int = _required_int("ALLOWED_USER_ID")
    timezone: str = _timezone()
    diary_day_start_hour: int = _diary_day_start_hour()
    silent_notifications: bool = _optional_bool("SILENT_NOTIFICATIONS", True)
    openai_roast_model: str = _optional_env("OPENAI_ROAST_MODEL", "gpt-5.4")
    roast_language: str = _optional_env("ROAST_LANGUAGE", "Russian").strip()
    roast_system_prompt: str = os.getenv("ROAST_SYSTEM_PROMPT", "").strip()


settings = _Settings()
