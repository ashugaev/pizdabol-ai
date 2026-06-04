import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_PATH = Path(os.getenv("BOT_STATE_PATH", ".data/message_state.json"))
MAX_RETAINED_MESSAGES = 200
UNPROCESSED_STATUSES = {"received", "processing", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "messages": {}, "drafts": {}}
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("version", 1)
        data.setdefault("messages", {})
        data.setdefault("drafts", {})
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        tmp_path.replace(self.path)

    def _prune_messages(self) -> None:
        messages = self.data["messages"]
        if len(messages) <= MAX_RETAINED_MESSAGES:
            return
        ordered = sorted(
            messages.items(),
            key=lambda item: (item[1].get("date") or "", item[1].get("message_id") or 0),
            reverse=True,
        )
        keep = {key for key, _ in ordered[:MAX_RETAINED_MESSAGES]}
        self.data["messages"] = {key: value for key, value in messages.items() if key in keep}

    def message_key(self, chat_id: int, message_id: int) -> str:
        return f"{chat_id}:{message_id}"

    def record_text(self, chat_id: int, message_id: int, text: str, date: str | None) -> str:
        return self._record_message(chat_id, message_id, "text", {"text": text}, date)

    def record_voice(self, chat_id: int, message_id: int, file_id: str, date: str | None) -> str:
        return self._record_message(chat_id, message_id, "voice", {"file_id": file_id}, date)

    def _record_message(
        self,
        chat_id: int,
        message_id: int,
        kind: str,
        payload: dict[str, Any],
        date: str | None,
    ) -> str:
        key = self.message_key(chat_id, message_id)
        messages = self.data["messages"]
        if key in messages:
            return key
        messages[key] = {
            "key": key,
            "chat_id": chat_id,
            "message_id": message_id,
            "kind": kind,
            "status": "received",
            "date": date or _now(),
            "created_at": _now(),
            "updated_at": _now(),
            **payload,
        }
        self._prune_messages()
        self._save()
        return key

    def get_message(self, key: str) -> dict[str, Any] | None:
        message = self.data["messages"].get(key)
        return deepcopy(message) if message else None

    def mark_message_processing(self, key: str) -> None:
        self._update_message(key, {"status": "processing", "error": None})

    def mark_message_drafted(self, key: str, entry_id: str) -> None:
        self._update_message(key, {"status": "drafted", "entry_id": entry_id, "error": None})

    def mark_message_saved(self, key: str | None) -> None:
        if key:
            self._update_message(key, {"status": "saved", "error": None})

    def mark_message_failed(self, key: str, error: str) -> None:
        self._update_message(key, {"status": "failed", "error": error})

    def _update_message(self, key: str, updates: dict[str, Any]) -> None:
        message = self.data["messages"].get(key)
        if not message:
            return
        message.update(updates)
        message["updated_at"] = _now()
        self._save()

    def recent_unprocessed_messages(self, limit: int) -> list[dict[str, Any]]:
        messages = [
            message
            for message in self.data["messages"].values()
            if message.get("status") in UNPROCESSED_STATUSES
        ]
        messages.sort(
            key=lambda message: (message.get("date") or "", message.get("message_id") or 0),
            reverse=True,
        )
        return [deepcopy(message) for message in reversed(messages[:limit])]

    def save_draft(self, draft: dict[str, Any]) -> None:
        stored = deepcopy(draft)
        stored["updated_at"] = _now()
        stored.setdefault("created_at", _now())
        self.data["drafts"][stored["id"]] = stored
        self._save()

    def get_draft(self, entry_id: str) -> dict[str, Any] | None:
        draft = self.data["drafts"].get(entry_id)
        return deepcopy(draft) if draft else None

    def remove_draft(self, entry_id: str) -> None:
        self.data["drafts"].pop(entry_id, None)
        self._save()


state_store = StateStore()
