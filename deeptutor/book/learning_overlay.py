"""Per-reader state for a shared canonical book.

Shared content lives in the admin workspace, but reading state belongs to the
reader.  Keeping it outside ``workspace/book`` also prevents an overlay-only
directory from being mistaken for a personal book by ``list_book_ids``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.file_io import atomic_write_text
from deeptutor.services.path_service import PathService

from .models import LearningCapture, LearningCaptureStatus, Progress
from .storage import _safe_book_id

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))


class BookLearningOverlay:
    """Storage-compatible subset for progress, captures, and page chat."""

    def __init__(self, path_service: PathService) -> None:
        self.path_service = path_service

    def book_root(self, book_id: str) -> Path:
        return (
            self.path_service.get_workspace_dir()
            / "book_learning"
            / f"book_{_safe_book_id(book_id)}"
        )

    def _progress_path(self, book_id: str) -> Path:
        return self.book_root(book_id) / "progress.json"

    def _captures_path(self, book_id: str) -> Path:
        return self.book_root(book_id) / "learning_captures.json"

    def _chat_path(self, book_id: str) -> Path:
        return self.book_root(book_id) / "page_chat_sessions.json"

    def load_progress(self, book_id: str) -> Progress | None:
        raw = _read_json(self._progress_path(book_id))
        if raw is None:
            return None
        try:
            return Progress.model_validate(raw)
        except Exception:
            return None

    def save_progress(self, progress: Progress) -> None:
        _write_json(self._progress_path(progress.book_id), progress.model_dump(mode="json"))

    def load_learning_captures(
        self,
        book_id: str,
        *,
        status: LearningCaptureStatus | None = None,
    ) -> list[LearningCapture]:
        raw = _read_json(self._captures_path(book_id))
        if not isinstance(raw, list):
            return []
        captures: list[LearningCapture] = []
        for item in raw:
            try:
                capture = LearningCapture.model_validate(item)
            except Exception as exc:
                logger.warning(
                    "Skipping invalid learning capture for shared book %s: %s",
                    book_id,
                    exc,
                )
                continue
            if status is None or capture.status == status:
                captures.append(capture)
        return sorted(captures, key=lambda item: item.updated_at, reverse=True)

    def load_learning_capture(self, book_id: str, capture_id: str) -> LearningCapture | None:
        return next(
            (
                capture
                for capture in self.load_learning_captures(book_id)
                if capture.id == capture_id
            ),
            None,
        )

    def upsert_learning_capture(self, capture: LearningCapture) -> None:
        captures = self.load_learning_captures(capture.book_id)
        for index, existing in enumerate(captures):
            if existing.id == capture.id:
                captures[index] = capture
                break
        else:
            captures.append(capture)
        captures.sort(key=lambda item: item.updated_at, reverse=True)
        _write_json(
            self._captures_path(capture.book_id),
            [item.model_dump(mode="json") for item in captures],
        )

    def load_page_chat_sessions(self, book_id: str) -> dict[str, str]:
        raw = _read_json(self._chat_path(book_id))
        if not isinstance(raw, dict):
            return {}
        return {
            str(page_id): str(session_id)
            for page_id, session_id in raw.items()
            if str(page_id).strip() and str(session_id).strip()
        }

    def set_page_chat_session(self, book_id: str, page_id: str, session_id: str) -> None:
        sessions = self.load_page_chat_sessions(book_id)
        sessions[str(page_id)] = str(session_id).strip()
        _write_json(self._chat_path(book_id), sessions)


__all__ = ["BookLearningOverlay"]
