"""Per-account interaction state and neutral, idempotent learning records."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
import uuid

from deeptutor.multi_user.context import get_current_user

_lock = threading.RLock()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class LearningLedger:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records_path = root / "learning_records.json"
        self.interactions_path = root / "learning_interactions.json"

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        return [dict(row) for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def records(self) -> list[dict[str, Any]]:
        return self._read(self.records_path)

    def save_interaction(self, row: dict[str, Any]) -> dict[str, Any]:
        with _lock:
            rows = self._read(self.interactions_path)
            existing = next(
                (item for item in rows if item.get("interaction_id") == row.get("interaction_id")),
                None,
            )
            if existing is not None:
                return existing
            rows.append(row)
            _atomic_json(self.interactions_path, rows)
        return row

    def interaction(self, interaction_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in self._read(self.interactions_path) if row.get("interaction_id") == interaction_id),
            None,
        )

    def record(
        self,
        *,
        interaction: dict[str, Any],
        submission: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        canonical = json.dumps(submission, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        event_id = sha256(
            f"{interaction.get('interaction_id')}|{canonical}".encode()
        ).hexdigest()
        with _lock:
            rows = self._read(self.records_path)
            existing = next((row for row in rows if row.get("event_id") == event_id), None)
            if existing is not None:
                return existing
            user = get_current_user()
            payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
            event = {
                "event_id": event_id,
                "user_id": user.id,
                "material_id": interaction.get("material_id", ""),
                "locator": interaction.get("locator", 1),
                "extension": interaction.get("extension", ""),
                "action": interaction.get("action", ""),
                "score": payload.get("score"),
                "total": payload.get("total"),
                "completed": bool(payload.get("completed")),
                "occurred_at": time.time(),
            }
            rows.append(event)
            _atomic_json(self.records_path, rows)
        return event


__all__ = ["LearningLedger"]
