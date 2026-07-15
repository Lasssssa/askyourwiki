"""Persistence of user chat conversations as JSON files on disk.

Each conversation is stored as a single JSON document at
``data/conversations/<user>/<conversation_id>.json``. This mirrors the
file-based approach of :class:`storage.wiki_store.WikiStore` and keeps the
history browseable without any database dependency.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Path segments come from a signed session (the username) and a client-generated
# id, but we still strip anything that could escape the conversations directory.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_TITLE_MAX_LEN = 80


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(segment: str) -> str:
    """Return a filesystem-safe path segment, or '' if nothing usable remains."""
    return _UNSAFE.sub("_", segment or "").strip("._")


class ConversationStore:
    """Manages persistence of chat conversations on disk, one file per chat."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _user_dir(self, user: str) -> Path:
        return self.data_dir / (_sanitize(user) or "anonymous")

    def _read(self, path: Path) -> Optional[dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read conversation %s: %s", path, exc)
            return None

    def _write(self, path: Path, conversation: dict[str, Any]) -> None:
        # Write to a temp file then atomically replace, so a crash mid-write
        # never leaves a half-written conversation behind.
        tmp = path.parent / f"{path.name}.tmp"
        tmp.write_text(json.dumps(conversation, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def append_turn(self, user: str, conversation_id: str, question: str, answer: str) -> str:
        """Append one user/assistant exchange, creating the conversation if new.

        Returns the id under which the conversation was stored.
        """
        cid = _sanitize(conversation_id) or uuid.uuid4().hex
        user_dir = self._user_dir(user)
        user_dir.mkdir(parents=True, exist_ok=True)
        path = user_dir / f"{cid}.json"

        now = _now()
        conversation = self._read(path) or {
            "id": cid,
            "user": user,
            "created_at": now,
            "title": "",
            "messages": [],
        }
        conversation["messages"].append({"role": "user", "content": question, "ts": now})
        conversation["messages"].append({"role": "assistant", "content": answer, "ts": now})
        if not conversation.get("title"):
            conversation["title"] = question.strip()[:_TITLE_MAX_LEN] or "Untitled"
        conversation["updated_at"] = now

        self._write(path, conversation)
        return cid

    def list_conversations(self, user: str) -> list[dict[str, Any]]:
        """Return lightweight summaries for a user, most recently updated first."""
        user_dir = self._user_dir(user)
        if not user_dir.is_dir():
            return []

        summaries: list[dict[str, Any]] = []
        for file in user_dir.glob("*.json"):
            conversation = self._read(file)
            if not conversation:
                continue
            summaries.append(
                {
                    "id": conversation.get("id", file.stem),
                    "title": conversation.get("title") or "Untitled",
                    "updated_at": conversation.get("updated_at", ""),
                    "message_count": len(conversation.get("messages", [])),
                }
            )

        summaries.sort(key=lambda item: item["updated_at"], reverse=True)
        return summaries

    def get_conversation(self, user: str, conversation_id: str) -> Optional[dict[str, Any]]:
        cid = _sanitize(conversation_id)
        if not cid:
            return None
        return self._read(self._user_dir(user) / f"{cid}.json")

    def delete_conversation(self, user: str, conversation_id: str) -> bool:
        cid = _sanitize(conversation_id)
        if not cid:
            return False
        try:
            (self._user_dir(user) / f"{cid}.json").unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.warning("Could not delete conversation %s/%s: %s", user, cid, exc)
            return False
