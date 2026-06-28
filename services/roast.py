import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)

ROAST_MAX_TOKENS = 1024
MAX_CONVERSATION_MESSAGES = 40

DEFAULT_SYSTEM_PROMPT = """You are a blunt but caring therapist. You receive an entry from someone's personal diary, and your job is to give it an honest "roast": cut through the sugar-coating and surface what the person actually feels and what they are avoiding saying.

How to respond:
- Speak directly and plainly, like a close friend who is not afraid to tell the truth.
- Spot the patterns, excuses, self-deception, and avoidance — name them out loud.
- Do not humiliate or belittle: behind the bluntness there is always care and belief in the person.
- End with a concrete question or challenge that pushes them to grow.
- Write in plain, vivid prose, without corporate jargon or markdown formatting. A few dense paragraphs.

If the person replies to your message, continue the conversation, building on the entire prior thread."""


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def system_prompt() -> str:
    base = settings.roast_system_prompt or DEFAULT_SYSTEM_PROMPT
    language = (settings.roast_language or "").strip()
    if language:
        base = f"{base}\n\nAlways write your response in {language}, regardless of the language of the diary entry."
    return base


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
