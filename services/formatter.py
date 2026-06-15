import json
import logging

import openai
from config import settings

client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)

LONG_TRANSCRIPTION_CHAR_LIMIT = 6000
FORMATTER_MAX_COMPLETION_TOKENS = 1024
METADATA_MAX_COMPLETION_TOKENS = 512

SYSTEM_PROMPT = """Верни JSON для дневниковой заметки:
- "title": короткий заголовок 3-5 слов, без кавычек
- "text": исходный текст с минимальной правкой
- "tags": только явно названные пользователем теги, иначе []

Правила для "text":
- не переписывай стиль, формулировки и порядок мыслей
- не заменяй слова синонимами и не улучшай смысл
- исправляй только очевидный мусор распознавания, повторы, пунктуацию и грубые ошибки
- не добавляй факты, выводы, имена и детали
- если фраза короткая или обрывочная, оставь ее короткой

Только валидный JSON, без markdown и пояснений."""

METADATA_PROMPT = """Верни JSON для дневниковой заметки:
- "title": короткий заголовок 3-5 слов, без кавычек
- "tags": только явно названные пользователем теги, иначе []

Не возвращай полный текст заметки.
Только валидный JSON, без markdown и пояснений."""


def _fallback_title(transcription: str) -> str:
    words = " ".join(transcription.split()).split()
    if not words:
        return "Без названия"
    return " ".join(words[:5]).strip(".,:;!?") or "Без названия"


def _coerce_tags(value) -> list[str]:
    if not isinstance(value, list):
        return []

    tags = []
    for item in value:
        tag = str(item).strip()
        if tag:
            tags.append(tag)
    return tags


def _parse_json(content: str) -> dict:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Formatter returned invalid JSON; falling back to raw transcription: %s", exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Formatter returned non-object JSON; falling back to raw transcription")
        return {}
    return data


async def format_entry(transcription: str) -> tuple[str, str, list[str]]:
    if len(transcription) > LONG_TRANSCRIPTION_CHAR_LIMIT:
        response = await client.chat.completions.create(
            model=settings.openai_formatter_model,
            max_completion_tokens=METADATA_MAX_COMPLETION_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": METADATA_PROMPT},
                {"role": "user", "content": transcription},
            ],
        )
        data = _parse_json(response.choices[0].message.content or "")
        title = str(data.get("title") or "").strip() or _fallback_title(transcription)
        return title, transcription, _coerce_tags(data.get("tags"))

    response = await client.chat.completions.create(
        model=settings.openai_formatter_model,
        max_completion_tokens=FORMATTER_MAX_COMPLETION_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcription},
        ],
    )
    data = _parse_json(response.choices[0].message.content or "")
    title = str(data.get("title") or "").strip() or _fallback_title(transcription)
    text = str(data.get("text") or "").strip() or transcription
    return title, text, _coerce_tags(data.get("tags"))
