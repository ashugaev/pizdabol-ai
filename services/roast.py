import json
import logging

from config import settings
from services.ai import create_chat_client

logger = logging.getLogger(__name__)

ROAST_MAX_COMPLETION_TOKENS = 4096
ROAST_REASONING_EFFORT = "high"
MAX_CONVERSATION_MESSAGES = 40

# Compact author profile the model maintains across roasts.
PROFILE_MAX_COMPLETION_TOKENS = 1024
MAX_PROFILE_POINTS = 20
MAX_PROFILE_POINT_LENGTH = 140

PROFILE_EXTRACTION_PROMPT = f"""Ты ведёшь компактный профиль автора дневника, чтобы лучше понимать, кто он, и точнее его направлять.
Ты обновляешь профиль после КАЖДОЙ записи в дневнике, поэтому будь особенно строг: лучше 0 новых фактов, чем дубли или мусор.
На вход дают новую запись из дневника и уже известные факты о человеке.

Собирай ТОЛЬКО устойчивый, значимый контекст — то, что влияет на его решения, состояние и путь в целом. Именно это стоит копить:
- Долгосрочные черты личности и характер — то, что вряд ли изменится.
- Его байасы, установки, привычные способы мышления и реакции.
- Ценности, внутренние драйверы, страхи и мотивации.
- Повторяющиеся паттерны в поведении и в принятии решений.
- Ключевые отношения, работа/проекты, крупные цели.
- Текущая жизненная фаза или период, который он сейчас проходит: это среднесрочный, глобальный контекст (не про один день), и его нужно обновлять, когда фаза меняется.

ВЫБРАСЫВАЙ разовое и то, что верно лишь в один момент: что он поел, туалетные и телесные события, настроение одной минуты, простой пересказ прошедшего дня. Это НЕ устойчивые факты о человеке — не сохраняй их.

Правила:
- Каждый факт — одно короткое самодостаточное предложение, максимум {MAX_PROFILE_POINT_LENGTH} символов.
- Различай долгосрочное (черты, байасы) и среднесрочное (текущая фаза): формулируй так, чтобы было понятно, что есть что.
- Верни не больше {MAX_PROFILE_POINTS} самых важных фактов, лучше меньше.
- Семантический дедуп: объединяй факты, которые значат одно и то же, никогда не выдавай почти-дубли и переформулировки уже известного.
- Обновляй факт, если запись его уточняет или он устарел (особенно текущую фазу); убирай то, что перестало быть правдой.
- Если новая запись не добавляет ничего реально нового и устойчивого — верни уже известные факты БЕЗ ИЗМЕНЕНИЙ, дословно.
- Лучше вернуть меньше фактов, чем добавить дубль или шум.
- Пиши на русском.
Верни СТРОГО JSON вида {{"points": ["...", "..."]}} без пояснений."""

DEFAULT_SYSTEM_PROMPT = """Ты — чёткий пацан, братан автора. Тебе прилетает запись из его личного дневника, и твоя работа — дать честный разъёб: срезать всю сахарную вату и вытащить наружу, что чел на самом деле чувствует и о чём молчит.

Как отвечаешь:
- Говоришь прямо и по-простому, по-уличному, как близкий друг, который не ссыт сказать правду в лицо. Без канцелярщины и корпоративной хуйни.
- Ловишь паттерны, отмазки, самообман и то, чего чел избегает, — называешь это вслух, не смягчаешь.
- Подъёбываешь по-доброму, но никогда не унижаешь и не опускаешь: за каждым подколом — братская забота и вера в чела.
- Ты на его стороне. Если чел красавчик — скажи прямо, без залипаний и лишней скромности.
- Не заканчивай вопросом и не подсовывай «а давай ещё» — ты не бот, который клянчит продолжение. Никакого пустого подбадривания ради галочки и плизерского мусора в конце. Ставишь точку на реальном выводе или наблюдении, и всё. Захочет чел продолжить — сам напишет, это его дело, а не твоя задача его удержать.
- Пишешь живым русским языком, ярко и сочно, без markdown и списков. Пара плотных абзацев.

Если чел отвечает на твоё сообщение — продолжаешь разговор, держа в голове весь предыдущий тред."""


def is_configured() -> bool:
    return bool(settings.ai_api_key)


def system_prompt(points: list[str] | None = None) -> str:
    base = settings.roast_system_prompt or DEFAULT_SYSTEM_PROMPT
    language = (settings.roast_language or "").strip()
    if language:
        base = f"{base}\n\nВсегда пиши ответ на языке: {language}, независимо от языка записи в дневнике."
    if points:
        joined = "\n".join(f"- {point}" for point in points)
        base = (
            f"{base}\n\nЧто ты уже знаешь об авторе (фон для понимания, не пересказывай это в лоб):\n{joined}"
        )
    return base


client = create_chat_client()


def _extract_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return (getattr(message, "content", None) or "").strip()


def _trim_chain(messages: list[dict]) -> list[dict]:
    return messages[-MAX_CONVERSATION_MESSAGES:]


async def roast(messages: list[dict], points: list[str] | None = None) -> str:
    if not is_configured():
        raise RuntimeError("AI provider API key is not configured")

    response = await client.chat.completions.create(
        model=settings.roast_model,
        max_completion_tokens=ROAST_MAX_COMPLETION_TOKENS,
        reasoning_effort=ROAST_REASONING_EFFORT,
        messages=[{"role": "system", "content": system_prompt(points)}] + _trim_chain(messages),
    )
    text = _extract_text(response)
    if not text:
        raise RuntimeError("AI provider returned an empty response")
    return text


def _normalize_points(points: list) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for point in points:
        if not isinstance(point, str):
            continue
        text = " ".join(point.split())
        if not text:
            continue
        if len(text) > MAX_PROFILE_POINT_LENGTH:
            text = text[:MAX_PROFILE_POINT_LENGTH].rstrip()
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= MAX_PROFILE_POINTS:
            break
    return result


async def extract_profile_points(diary_text: str, existing_points: list[str] | None = None) -> list[str]:
    """Distill a compact, deduped set of durable facts about the author from a diary
    entry, merged with what is already known. Returns the normalized full list."""
    if not is_configured():
        raise RuntimeError("AI provider API key is not configured")

    payload = json.dumps(
        {"diary_entry": diary_text, "known_facts": existing_points or []},
        ensure_ascii=False,
    )
    response = await client.chat.completions.create(
        model=settings.profile_model,
        max_completion_tokens=PROFILE_MAX_COMPLETION_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PROFILE_EXTRACTION_PROMPT},
            {"role": "user", "content": payload},
        ],
    )
    text = _extract_text(response)
    if not text:
        raise RuntimeError("AI provider returned an empty response")
    data = json.loads(text)
    return _normalize_points(data.get("points", []))
