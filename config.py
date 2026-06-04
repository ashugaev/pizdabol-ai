import os
from dotenv import load_dotenv

load_dotenv()

def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


def _optional_env(name: str, default: str) -> str:
    return os.getenv(name) or default


class _Settings:
    telegram_token: str = _required_env("TELEGRAM_TOKEN")
    openai_api_key: str = _required_env("OPENAI_API_KEY")
    openai_transcription_model: str = _optional_env("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    openai_formatter_model: str = _optional_env("OPENAI_FORMATTER_MODEL", "gpt-5.4-mini")
    openai_summary_model: str = _optional_env("OPENAI_SUMMARY_MODEL", openai_formatter_model)
    notion_token: str = _required_env("NOTION_TOKEN")
    notion_database_id: str = _required_env("NOTION_DATABASE_ID")
    allowed_user_id: int = int(_required_env("ALLOWED_USER_ID"))
    timezone: str = os.getenv("TIMEZONE", "Europe/Moscow")


settings = _Settings()
