from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import uuid

from deeptutor.learning.models import LearningProgress
from deeptutor.services.path_service import get_path_service

# Module-level lock so CAS semantics hold across all store instances.
_cas_lock = threading.Lock()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex}")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        # Don't leave an orphaned temp file behind on write/replace failure.
        tmp.unlink(missing_ok=True)
        raise


class LearningStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (get_path_service().get_workspace_dir() / "learning")
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, book_id: str) -> Path:
        if "/" in book_id or "\\" in book_id or ".." in book_id or ":" in book_id:
            raise ValueError(f"Invalid book_id: {book_id!r}")
        return self._root / f"{book_id}.json"

    def save(self, progress: LearningProgress) -> None:
        with _cas_lock:
            progress.updated_at = time.time()
            progress.version += 1
            data = progress.model_dump(mode="json")
            text = json.dumps(data, ensure_ascii=False, indent=2)
            _atomic_write_text(self._path(progress.book_id), text)

    def load(self, book_id: str) -> LearningProgress | None:
        path = self._path(book_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LearningProgress.model_validate(data)

    def delete(self, book_id: str) -> None:
        with _cas_lock:
            path = self._path(book_id)
            if path.exists():
                path.unlink()

    def exists(self, book_id: str) -> bool:
        return self._path(book_id).exists()

    def list_all(self) -> list[str]:
        """Return all book_ids that have stored progress."""
        return sorted(p.stem for p in self._root.glob("*.json") if not p.name.startswith("."))


__all__ = ["LearningStore"]
