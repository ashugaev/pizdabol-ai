import json
import logging

from config import settings
from services.ai import create_chat_client

logger = logging.getLogger(__name__)

ROAST_MAX_COMPLETION_TOKENS = 4096
ROAST_REASONING_EFFORT = "high"
MAX_CONVERSATION_MESSAGES = 40

# Compact author profile the model maintains across roasts.
# The extractor answers with a delta, so a steady-state completion is tiny. The
# budget is sized for the worst case instead — a first pass over a dense note
# that adds many facts at once — with room for the reasoning tokens that count
# against the same ceiling.
PROFILE_MAX_COMPLETION_TOKENS = 8192
# Pinned low: this is mechanical merge/dedup work, and on reasoning models any
# effort left unpinned eats the completion budget and truncates the answer.
PROFILE_REASONING_EFFORT = "low"
# Soft guidance passed to the model only — never enforced mechanically.
MAX_PROFILE_POINTS = 100
MAX_PROFILE_POINT_LENGTH = 200

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
- Каждый факт — одно самодостаточное предложение, ориентировочно до {MAX_PROFILE_POINT_LENGTH} символов; это ориентир, а не жёсткий обрез — не режь мысль ради лимита.
- Различай долгосрочное (черты, байасы) и среднесрочное (текущая фаза): формулируй так, чтобы было понятно, что есть что.
- Держи примерно до {MAX_PROFILE_POINTS} самых важных фактов, лучше меньше; если их становится больше — объединяй и убирай слабое, а не обрезай по счётчику.
- Семантический дедуп: объединяй факты, которые значат одно и то же, никогда не выдавай почти-дубли и переформулировки уже известного.
- Обновляй факт, если запись его уточняет или он устарел (особенно текущую фазу); убирай то, что перестало быть правдой.
- Лучше вернуть меньше фактов, чем добавить дубль или шум.
- Пиши на русском.

Ты возвращаешь ТОЛЬКО ИЗМЕНЕНИЯ профиля, а не профиль целиком. Уже известные факты, которых ты не тронул, сохраняются сами — НЕ перечисляй их.
Верни СТРОГО JSON вида {{"add": ["..."], "remove": ["..."], "update": [{{"from": "...", "to": "..."}}]}} без пояснений.
- "add" — новые устойчивые факты, которых ещё нет в known_facts.
- "remove" — факты из known_facts, которые перестали быть правдой. Строку копируй из known_facts ДОСЛОВНО.
- "update" — переформулировка или уточнение известного факта: "from" — дословная строка из known_facts, "to" — новая версия. Через update же объединяй дубли: один from -> to, остальные дубли в remove.
- Если запись не добавляет ничего реально нового и устойчивого — верни {{"add": [], "remove": [], "update": []}}. Это нормальный и частый ответ.
- Если фактов стало заметно больше {MAX_PROFILE_POINTS} — объединяй близкие через update и убирай слабые через remove."""

# Appended only when the author supplies priorities for a retrospective pass.
PROFILE_FOCUS_INSTRUCTION = """Автор задал приоритеты для этого прохода — они в поле "focus".
Считай их главным фильтром: в первую очередь вытаскивай и уточняй то, что относится к focus, и переформулируй уже известные факты под эти акценты через "update".
Остальные устойчивые факты сохраняй по обычным правилам, но не в ущерб focus.
Сам текст focus в факты не превращай — это инструкция, а не знание об авторе."""

DEFAULT_SYSTEM_PROMPT = """Ты — чёткий пацан, братан автора. Тебе прилетает запись из его личного дневника. Твоя работа — честный разъёб: срезать сахарную вату, вытащить наружу, что чел реально чувствует и о чём молчит.

Тон:
- Прямо, по-уличному, как близкий друг, который не ссыт сказать правду в лицо. Без канцелярщины и корпоративной хуйни.
- Ловишь паттерны, отмазки, самообман, избегание, драму — называешь вслух, даже если челу это не понравится.
- Подъёбываешь по-доброму, но не унижаешь: за подколом — братская забота и вера в чела.
- Ты на его стороне, но не поддакиваешь: соглашаешься только там, где он реально прав, а не потому что версия его.
- Красавчик — говори прямо, без лишней скромности. Но хвалишь за реальное, а не за очевидное и не по умолчанию.
- Живой русский, ярко и сочно. Без markdown и списков.

Длина — коротко и плотно:
- 3-6 предложений, один абзац. Максимум два, если реально есть что сказать.
- Один главный вывод. Не вываливай все наблюдения — бери самое острое.
- Не пересказывай запись, чел её и так знает.
- Каждое предложение несёт новое. Вода, разгон, повтор, украшательства — вырезать.

Не делай:
- Облизывания, пустое подбадривание, комплименты ради галочки, плизерский мусор.
- Раздутых извинений. Ошибся — коротко исправился и дальше по делу.
- Не пизди: не уверен — так и скажи. Не заявляй, что что-то сохранил, записал или сделал, если этого не было.
- Вопрос в конце, «а давай ещё» — ты не клянчишь продолжение. Захочет — сам напишет.
- Вступления, дисклеймеры, пояснения того, что ты сейчас делаешь.

Заканчиваешь на реальном выводе или наблюдении. Точка.

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


def _finish_reason(response) -> str:
    """Why the model stopped, for logs. `"length"` means the completion budget ran out."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return "unknown"
    return getattr(choices[0], "finish_reason", None) or "unknown"


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
    """Light hygiene only: drop non-strings, empties, and exact duplicates.
    Point length and list size are guided at the prompt level — never trimmed
    or capped mechanically."""
    seen: set[str] = set()
    result: list[str] = []
    for point in points:
        if not isinstance(point, str):
            continue
        text = " ".join(point.split())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _point_key(text: str) -> str:
    """Match key for referring to a known fact. Whitespace- and case-insensitive
    so a model that reflows or recases a quoted fact still matches it."""
    return " ".join(str(text).split()).lower()


def _clean_strings(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [" ".join(v.split()) for v in values if isinstance(v, str) and v.strip()]


def _update_map(values) -> dict[str, str]:
    """`[{"from": known, "to": revised}]` -> {match key of known: revised}."""
    if not isinstance(values, list):
        return {}
    pairs = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        source, target = item.get("from"), item.get("to")
        if isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip():
            pairs[_point_key(source)] = " ".join(target.split())
    return pairs


def _apply_profile_delta(existing: list[str], delta: dict) -> list[str]:
    """Fold a `{add, remove, update}` delta into the known facts.

    Existing order is preserved: updates rewrite in place, removals drop out,
    and additions land at the end. A removal wins over an update of the same
    fact, and an update whose "from" matches nothing is kept as an addition
    rather than discarded — the model meant to record it either way."""
    if not isinstance(delta, dict):
        return _normalize_points(existing)
    removals = {_point_key(text) for text in _clean_strings(delta.get("remove"))}
    updates = _update_map(delta.get("update"))

    result = []
    for point in existing:
        key = _point_key(point)
        if key in removals:
            updates.pop(key, None)
            continue
        result.append(updates.pop(key, point))

    result.extend(updates.values())
    result.extend(_clean_strings(delta.get("add")))
    return _normalize_points(result)


async def extract_profile_points(
    diary_text: str,
    existing_points: list[str] | None = None,
    focus: str | None = None,
) -> list[str]:
    """Distill a compact, deduped set of durable facts about the author from a diary
    entry, merged with what is already known. Returns the normalized full list.

    The model answers with a `{add, remove, update}` delta rather than the whole
    profile, so the completion size tracks how much actually changed instead of
    how much has been learned — the profile can grow without approaching the
    output ceiling. The merge happens here, in code.

    `focus` carries the author's priorities for this extraction, if any: it steers
    what gets pulled out and how known facts are reframed, never what is stored."""
    if not is_configured():
        raise RuntimeError("AI provider API key is not configured")

    existing = _normalize_points(existing_points or [])
    request = {"diary_entry": diary_text, "known_facts": existing}
    system_prompt = PROFILE_EXTRACTION_PROMPT
    if focus:
        request["focus"] = focus
        system_prompt = f"{system_prompt}\n\n{PROFILE_FOCUS_INSTRUCTION}"

    payload = json.dumps(request, ensure_ascii=False)
    response = await client.chat.completions.create(
        model=settings.profile_model,
        max_completion_tokens=PROFILE_MAX_COMPLETION_TOKENS,
        reasoning_effort=PROFILE_REASONING_EFFORT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload},
        ],
    )
    # A completion that ran out of budget comes back either empty or as partial
    # JSON. The profile is accumulated knowledge, so both degrade to a no-op:
    # keeping what we already know beats failing the caller or losing the list.
    text = _extract_text(response)
    if text:
        try:
            return _apply_profile_delta(existing, json.loads(text))
        except json.JSONDecodeError:
            pass
    logger.warning(
        "Profile extraction returned no usable JSON (finish_reason=%s); keeping the existing profile",
        _finish_reason(response),
    )
    return existing
