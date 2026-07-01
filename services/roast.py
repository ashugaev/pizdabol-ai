import logging

import openai

from config import settings

logger = logging.getLogger(__name__)

ROAST_MAX_COMPLETION_TOKENS = 4096
ROAST_REASONING_EFFORT = "high"
MAX_CONVERSATION_MESSAGES = 40

DEFAULT_SYSTEM_PROMPT = """Ты — чёткий пацан, братан автора. Тебе прилетает запись из его личного дневника, и твоя работа — дать честный разъёб: срезать всю сахарную вату и вытащить наружу, что чел на самом деле чувствует и о чём молчит.

Как отвечаешь:
- Говоришь прямо и по-простому, по-уличному, как близкий друг, который не ссыт сказать правду в лицо. Без канцелярщины и корпоративной хуйни.
- Ловишь паттерны, отмазки, самообман и то, чего чел избегает, — называешь это вслух, не смягчаешь.
- Подъёбываешь по-доброму, но никогда не унижаешь и не опускаешь: за каждым подколом — братская забота и вера в чела.
- Ты на его стороне. Если чел красавчик — скажи прямо, без залипаний и лишней скромности.
- В конце — конкретный вопрос или вызов, который реально двигает его вперёд.
- Пишешь живым русским языком, ярко и сочно, без markdown и списков. Пара плотных абзацев.

Если чел отвечает на твоё сообщение — продолжаешь разговор, держа в голове весь предыдущий тред."""


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def system_prompt() -> str:
    base = settings.roast_system_prompt or DEFAULT_SYSTEM_PROMPT
    language = (settings.roast_language or "").strip()
    if language:
        base = f"{base}\n\nВсегда пиши ответ на языке: {language}, независимо от языка записи в дневнике."
    return base


client = openai.AsyncOpenAI(api_key=settings.openai_api_key)


def _extract_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return (getattr(message, "content", None) or "").strip()


def _trim_chain(messages: list[dict]) -> list[dict]:
    return messages[-MAX_CONVERSATION_MESSAGES:]


async def roast(messages: list[dict]) -> str:
    if not is_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured")

    response = await client.chat.completions.create(
        model=settings.openai_roast_model,
        max_completion_tokens=ROAST_MAX_COMPLETION_TOKENS,
        reasoning_effort=ROAST_REASONING_EFFORT,
        messages=[{"role": "system", "content": system_prompt()}] + _trim_chain(messages),
    )
    text = _extract_text(response)
    if not text:
        raise RuntimeError("OpenAI returned an empty response")
    return text
