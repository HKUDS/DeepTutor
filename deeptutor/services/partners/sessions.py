"""Lightweight JSONL conversation store for partner sessions.

One JSONL file per session key (``telegram:12345``, ``web:<session_id>``,
``partner:<id>`` …) under ``data/partners/<id>/sessions/``. This is the
partner-side replacement for the deleted engine's SessionManager: it only
has to hand the chat agent loop an OpenAI-format ``conversation_history``
and back the history API, so a flat append-only file per session is enough.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import threading
from typing import Any

from deeptutor.partners.helpers import safe_filename

logger = logging.getLogger(__name__)

_HISTORY_MAX_MESSAGES = 40
_HISTORY_MAX_CHARS = 24_000
_ARCHIVE_PREFIX = "_archived_"


class PartnerSessionStore:
    """Append-only JSONL persistence for one partner's conversations."""

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = sessions_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    def _path(self, session_key: str) -> Path:
        return self._dir / f"{self._stem(session_key)}.jsonl"

    @staticmethod
    def is_archived_key(session_key: str) -> bool:
        return safe_filename(session_key).startswith(_ARCHIVE_PREFIX)

    # ── session metadata (archived flag) ──────────────────────────
    #
    # The web app drives session lifecycle by key (resume / delete / branch),
    # so a web session is archived with a soft flag in this sidecar rather than
    # renamed — the file keeps its key and stays resumable. IM still uses the
    # rename-based ``archive()`` to free a chat's fixed key for a fresh start.

    @property
    def _index_path(self) -> Path:
        return self._dir / "_index.json"

    def _load_index(self) -> dict[str, Any]:
        path = self._index_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_index(self, index: dict[str, Any]) -> None:
        with self._write_lock:
            self._index_path.write_text(
                json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _stem(self, session_key: str) -> str:
        # Single source of truth for key → on-disk stem. ``safe_filename``
        # neutralizes path separators (so a key can't escape the sessions dir);
        # we additionally strip leading/trailing dots and fall back to
        # ``default`` so a degenerate key (empty, ``.`` / ``..``) can't produce a
        # hidden or dots-only file. NOTE: safe_filename is intentionally lossy —
        # ``:`` and ``/`` both fold to ``_`` — so keys differing only in unsafe
        # characters share a file. Callers build keys from safe components (uuid
        # hex, slugged ascii ids), so that collision is unreachable in practice;
        # making the mapping injective would rename every existing session file
        # (``web:<id>`` → ``web_<id>.jsonl``) and orphan history, so it is left
        # as-is deliberately.
        return safe_filename(session_key).strip(".") or "default"

    def is_archived(self, session_key: str) -> bool:
        """Archived = soft flag in the index OR a legacy ``_archived_`` file."""
        stem = self._stem(session_key)
        if bool(self._load_index().get(stem, {}).get("archived")):
            return True
        return self.is_archived_key(session_key)

    def set_archived(self, session_key: str, archived: bool) -> None:
        stem = self._stem(session_key)
        index = self._load_index()
        entry = index.get(stem, {})
        if archived:
            entry["archived"] = True
        else:
            entry.pop("archived", None)
        if entry:
            index[stem] = entry
        else:
            index.pop(stem, None)
        self._save_index(index)

    def delete_session(self, session_key: str) -> bool:
        """Remove a session's file and its index entry. Returns whether it existed."""
        path = self._path(session_key)
        existed = path.exists()
        with self._write_lock:
            path.unlink(missing_ok=True)
        index = self._load_index()
        if index.pop(self._stem(session_key), None) is not None:
            self._save_index(index)
        return existed

    def branch(self, source_key: str, new_key: str) -> dict[str, Any] | None:
        """Copy *source_key*'s full history into *new_key* and archive the source.

        Returns the new session's summary, or ``None`` if the source is empty.
        The new key keeps the conversation going with the same context while the
        original is preserved (archived) and still resumable.
        """
        records = self._read_records(source_key)
        if not records:
            return None
        dest = self._path(new_key)
        with self._write_lock:
            with open(dest, "a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.set_archived(source_key, True)
        return self._session_summary(dest)

    # ── write ─────────────────────────────────────────────────────

    def append(
        self,
        session_key: str,
        role: str,
        content: str,
        *,
        channel: str = "",
        sender_id: str = "",
        metadata: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if channel:
            record["channel"] = channel
        if sender_id:
            record["sender_id"] = sender_id
        if metadata:
            record["metadata"] = metadata
        if attachments:
            record["attachments"] = attachments
        # The turn's trace (thinking / tool calls / narration) so the web chat
        # can rehydrate the collapsible "Done" activity after a refresh — the
        # IM channels never read it back, but it costs only storage there.
        if events:
            record["events"] = events
        line = json.dumps(record, ensure_ascii=False)
        with self._write_lock:
            with open(self._path(session_key), "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def clear(self, session_key: str) -> bool:
        path = self._path(session_key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def archive(self, session_key: str) -> dict[str, Any] | None:
        """Move the current session file aside and return its archive summary.

        The active key remains reusable: after archiving ``telegram:42``, new
        messages write to ``telegram_42.jsonl`` while the old file is kept as a
        separate archived session that can still be inspected through the
        history API by using the returned ``session_key``.
        """
        path = self._path(session_key)
        if not path.exists():
            return None
        records = self._read_records(session_key)
        if not records:
            return None

        safe_key = self._stem(session_key)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_key = f"{_ARCHIVE_PREFIX}{stamp}_{safe_key}"
        archive_path = self._path(archive_key)
        suffix = 1
        while archive_path.exists():
            archive_key = f"{_ARCHIVE_PREFIX}{stamp}_{suffix}_{safe_key}"
            archive_path = self._path(archive_key)
            suffix += 1

        with self._write_lock:
            if not path.exists():
                return None
            path.replace(archive_path)

        return self._session_summary(archive_path)

    # ── read ──────────────────────────────────────────────────────

    def _read_records(self, session_key: str) -> list[dict[str, Any]]:
        path = self._path(session_key)
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict) and data.get("role") and data.get("content"):
                        records.append(data)
        except OSError:
            logger.exception("Failed to read partner session %s", session_key)
        return records

    def conversation_history(
        self,
        session_key: str,
        *,
        max_messages: int = _HISTORY_MAX_MESSAGES,
        max_chars: int = _HISTORY_MAX_CHARS,
    ) -> list[dict[str, str]]:
        """Return trailing history in OpenAI message format, budget-capped."""
        records = self._read_records(session_key)
        window = [
            {"role": str(r["role"]), "content": str(r["content"])}
            for r in records[-max_messages:]
            if r.get("role") in {"user", "assistant"}
        ]
        total = 0
        kept: list[dict[str, str]] = []
        for message in reversed(window):
            total += len(message["content"])
            if kept and total > max_chars:
                break
            kept.append(message)
        kept.reverse()
        return kept

    def messages(self, session_key: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Raw records (role/content/timestamp/...) for the history API."""
        return self._read_records(session_key)[-limit:]

    def merged_messages(
        self, *, limit: int = 100, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """All sessions' records merged chronologically (recent-activity view)."""
        merged: list[tuple[str, int, dict[str, Any]]] = []
        sequence = 0
        for path in sorted(self._dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
            if not include_archived and self.is_archived(path.stem):
                continue
            key = path.stem
            for record in self._read_records(key):
                merged.append((str(record.get("timestamp", "")), sequence, record))
                sequence += 1
        merged.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in merged[-limit:]]

    def _session_summary(self, path: Path) -> dict[str, Any]:
        records = self._read_records(path.stem)
        last = records[-1] if records else {}
        archived = self.is_archived(path.stem)
        return {
            "session_key": path.stem,
            "title": self._derive_title(records),
            "message_count": len(records),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "last_message": str(last.get("content", ""))[:200],
            "archived": archived,
        }

    @staticmethod
    def _derive_title(records: list[dict[str, Any]]) -> str:
        """A short, human label for a session — its opening user message.

        The first user turn is what a conversation is "about"; fall back to the
        first record of any role. First line only, trimmed to a chip-sized
        length. Empty for an empty session (the UI shows a generic label).
        """
        opener = next(
            (r for r in records if r.get("role") == "user"),
            records[0] if records else None,
        )
        if not opener:
            return ""
        text = str(opener.get("content", "")).strip()
        first_line = text.splitlines()[0] if text else ""
        return first_line[:60].strip()

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            self._session_summary(path)
            for path in sorted(
                self._dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
            )
        ]


__all__ = ["PartnerSessionStore"]
