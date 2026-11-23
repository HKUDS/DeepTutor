"""Owner-private device credentials and the cross-process refresh lock."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import stat
import threading
from typing import Any

from deeptutor.services.codex_auth.contracts import CodexAuthError
from deeptutor.services.codex_auth.storage import (
    CodexCredentialStore,
    _assert_safe_directory,
    _assert_safe_regular_path,
    _atomic_write_json,
    _locked_file,
)

from .client import DeepTutorAccountError


class DeviceStore:
    def __init__(self, owner_root: Path) -> None:
        self.root = owner_root / "private" / "deeptutor-account"
        self.path = self.root / "credentials.v1.json"
        self._thread_lock = threading.Lock()

    @contextmanager
    def locked(self) -> Iterator[None]:
        # The caller runs this entire section in a worker thread, including
        # token rotation and the atomic write of the replacement.
        try:
            with self._thread_lock:
                for path in (self.root.parent, self.root):
                    _assert_safe_directory(path)
                    path.mkdir(exist_ok=True)
                    path.chmod(stat.S_IRWXU)
                with _locked_file(self.root / "auth.lock"):
                    yield
        except (OSError, CodexAuthError):
            raise DeepTutorAccountError("storage_error", 500) from None

    def load(self) -> dict[str, Any]:
        return (
            CodexCredentialStore._read_json(
                self.path, code="storage_error", message="Invalid DeepTutor Studio credentials."
            )
            or {}
        )

    def save(self, state: dict[str, Any]) -> None:
        if state:
            _atomic_write_json(self.path, state)
        else:
            _assert_safe_regular_path(self.path)
            self.path.unlink(missing_ok=True)
