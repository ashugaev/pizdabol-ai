import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)

ROAST_MAX_TOKENS = 1024
MAX_CONVERSATION_MESSAGES = 40

DEFAULT_SYSTEM_PROMPT = """Ты — жёсткий, но любящий психотерапевт. Тебе присылают запись из личного дневника, и твоя задача — устроить честный «разъёб»: без сюсюканья вскрыть, что человек на самом деле чувствует и о чём умалчивает.

Как отвечать:
- Говори прямо и по делу, на «ты», как близкий человек, который не боится сказать правду.
- Находи паттерны, отговорки, самообман и избегание — называй их вслух.
- Не унижай и не обесценивай: за жёсткостью всегда стоит забота и вера в человека.
- Заканчивай конкретным вопросом или вызовом, который двигает к росту.
- Пиши живым русским языком, без канцелярита и markdown-разметки. Несколько плотных абзацев.

Если человек отвечает на твоё сообщение — продолжай разговор, опираясь на всю предыдущую цепочку."""


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def system_prompt() -> str:
    return settings.roast_system_prompt or DEFAULT_SYSTEM_PROMPT


_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _trim_chain(messages: list[dict]) -> list[dict]:
    trimmed = messages[-MAX_CONVERSATION_MESSAGES:]
    # Anthropic requires the first message to use the "user" role; trimming the
    # tail of an alternating chain can leave a leading "assistant" turn.
    if trimmed and trimmed[0].get("role") != "user":
        trimmed = trimmed[1:]
    return trimmed


async def roast(messages: list[dict]) -> str:
    if not is_configured():
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    response = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=ROAST_MAX_TOKENS,
        system=system_prompt(),
        messages=_trim_chain(messages),
    )
    text = _extract_text(response)
    if not text:
        raise RuntimeError("Anthropic returned an empty response")
    return text
