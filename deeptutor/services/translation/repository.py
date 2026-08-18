"""Serialized JSON persistence for the translation task board."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import threading
from typing import Any, Iterator

from deeptutor.services.file_io import atomic_write_json


class TranslationStateRepository:
    """Read and mutate one process-local JSON state file.

    The lock is reentrant so nested service helpers can use the same short
    transaction. Model calls must happen outside a transaction; task completion
    is applied as a bounded patch rather than replacing the entire state.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            state: dict[str, Any] = {}
        else:
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("version", 1)
        state.setdefault("tasks", [])
        state.setdefault("sources", {})
        state.setdefault("glossaries", {})
        state.setdefault("runs", {})
        state.setdefault("is_running", False)
        state.setdefault("last_run_at", 0)
        return state

    def read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_unlocked()

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._lock:
            yield

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        with self._lock:
            state = self._read_unlocked()
            yield state
            atomic_write_json(self.path, state)

    def update_task(self, task_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as state:
            task = next((item for item in state["tasks"] if item.get("id") == task_id), None)
            if task is None:
                raise ValueError("Translation task not found")
            task.update(**patch)
            return dict(task)

    def update_run(self, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as state:
            run = state["runs"].get(run_id)
            if run is None:
                raise ValueError("Translation run not found")
            run.update(patch)
            return dict(run)
