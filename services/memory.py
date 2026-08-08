"""ID-addressed memory shared by the author profile and the bot's own rules.

Both are accumulated lists of short facts. The model never rewrites a list and
never quotes it back — it edits one entry at a time with targeted operations:

  {"action": "create", "text": "..."}
  {"action": "modify", "id": "7", "text": "..."}
  {"action": "delete", "id": "7"}

An operation names its target by a stable id, so the cost of a change is flat
however much has been learned, and an id the model gets wrong is a skipped
no-op — never a lost entry and never a near-duplicate appended beside the entry
it meant to edit.

Ids are assigned here and live in local state next to the text, so an entry
keeps its id for as long as it exists. A single update never recycles an id it
just deleted, so no operation in a batch can land on the wrong entry.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CREATE = "create"
MODIFY = "modify"
DELETE = "delete"
ACTIONS = (CREATE, MODIFY, DELETE)


@dataclass(frozen=True)
class MemoryItem:
    id: str
    text: str


def _clean(value: Any) -> str:
    """Collapse whitespace. Length is guided at the prompt level, never trimmed."""
    return " ".join(str(value).split()) if isinstance(value, str) else ""


def _dedupe(items: list[MemoryItem]) -> list[MemoryItem]:
    """Drop exact repeats, keeping the first — semantic dedup is the model's job."""
    seen: set[str] = set()
    result = []
    for item in items:
        key = item.text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _numeric(item_id: str) -> int:
    return int(item_id) if item_id.isdigit() else 0


def _next_id(items: list[MemoryItem], used: set[str]) -> str:
    """One past the highest id in play, counting ids already spent in this pass."""
    seen = [_numeric(item.id) for item in items] + [_numeric(item_id) for item_id in used]
    return str(max(seen, default=0) + 1)


def load(raw: Any) -> list[MemoryItem]:
    """Read stored entries. Accepts the legacy plain-string list and mints an id
    for any entry missing one, so an old state file upgrades on first read."""
    if not isinstance(raw, list):
        return []

    items: list[MemoryItem] = []
    used: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            text, item_id = _clean(entry), ""
        elif isinstance(entry, dict):
            text, item_id = _clean(entry.get("text")), _clean(entry.get("id"))
        else:
            continue
        if not text:
            continue
        if not item_id or item_id in used:
            item_id = _next_id(items, used)
        used.add(item_id)
        items.append(MemoryItem(item_id, text))
    return _dedupe(items)


def dump(items: list[MemoryItem]) -> list[dict]:
    """Wire and state shape: the id travels with the text, so what the model is
    shown is exactly what is stored and it can quote an id back."""
    return [{"id": item.id, "text": item.text} for item in items]


def texts(items: list[MemoryItem]) -> list[str]:
    """Just the facts — for prompts, the Notion mirror, and user-facing lists."""
    return [item.text for item in items]


def render(items: list[MemoryItem]) -> str:
    """Numbered-by-id lines for a system prompt the model edits inline."""
    return "\n".join(f"[{item.id}] {item.text}" for item in items)


def adopt(items: list[MemoryItem], edited: list[str]) -> list[MemoryItem]:
    """Rebuild the list from plain text edited outside the bot — a Notion page.

    An entry whose text survived the edit keeps its id, so ids stay stable across
    a hand edit and the model's next reference still lands. A reworded or brand
    new line gets a fresh id, because it is a different entry now.
    """
    by_text = {item.text.lower(): item.id for item in items}
    used = {item.id for item in items}

    result: list[MemoryItem] = []
    for value in edited:
        text = _clean(value)
        if not text:
            continue
        item_id = by_text.pop(text.lower(), "")
        if not item_id:
            item_id = _next_id(result, used)
            used.add(item_id)
        result.append(MemoryItem(item_id, text))
    return _dedupe(result)


def apply_ops(items: list[MemoryItem], ops: Any) -> list[MemoryItem]:
    """Fold a list of operations into `items`, returning the new list.

    Order is preserved: a modify rewrites in place, a delete drops out, a create
    lands at the end. Everything unrecognised is skipped and logged — a
    malformed operation must cost one entry's worth of change, not the list.
    """
    if not isinstance(ops, list):
        return list(items)

    by_id = {item.id: item.text for item in items}
    edits: dict[str, str] = {}
    removals: set[str] = set()
    creations: list[str] = []
    used = set(by_id)

    for op in ops:
        if not isinstance(op, dict):
            logger.warning("Memory op is not an object; skipping it")
            continue
        action = _clean(op.get("action")).lower()
        item_id = _clean(op.get("id"))
        text = _clean(op.get("text"))

        if action not in ACTIONS:
            logger.warning("Memory op has an unknown action %r; skipping it", action)
            continue
        if action in (CREATE, MODIFY) and not text:
            logger.warning("Memory op %s carries no text; skipping it", action)
            continue
        if action == CREATE:
            creations.append(text)
            continue
        if item_id not in by_id:
            logger.warning("Memory op %s references unknown id %r; skipping it", action, item_id)
            continue
        if action == DELETE:
            removals.add(item_id)
            edits.pop(item_id, None)
        else:
            edits[item_id] = text

    result = [
        MemoryItem(item.id, edits.get(item.id, item.text))
        for item in items
        if item.id not in removals
    ]
    for text in creations:
        item_id = _next_id(result, used)
        used.add(item_id)
        result.append(MemoryItem(item_id, text))
    return _dedupe(result)
