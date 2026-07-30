"""Private, generation-safe storage for DeepTutor Codex credentials."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
from typing import Any, BinaryIO

from .contracts import CodexAuthError, CodexCredentials

_SCHEMA_VERSION = 1


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _unsafe_path() -> CodexAuthError:
    return CodexAuthError(
        "unsafe_storage_path",
        "Codex authentication storage uses an unsafe filesystem path.",
        500,
    )


def _assert_safe_directory(path: Path) -> None:
    if path.is_symlink() or _is_reparse_point(path):
        raise _unsafe_path()
    if path.exists() and not path.is_dir():
        raise _unsafe_path()


def _assert_safe_regular_path(path: Path) -> None:
    _assert_safe_directory(path.parent)
    if path.is_symlink() or _is_reparse_point(path):
        raise _unsafe_path()
    if path.exists() and not path.is_file():
        raise _unsafe_path()


@contextmanager
def _locked_file(path: Path) -> Iterator[BinaryIO]:
    _assert_safe_regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        # ``sys.platform`` rather than ``os.name``: the checker narrows on it,
        # so the Windows-only ``msvcrt`` branch type-checks off Windows too.
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield handle
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _assert_safe_regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


class CodexCredentialStore:
    """Store credentials only below DeepTutor's explicitly supplied user root."""

    def __init__(self, user_root: Path) -> None:
        self.root = Path(user_root) / "private" / "openai-codex"
        self.credentials_path = self.root / "credentials.v1.json"
        self.state_path = self.root / "state.v1.json"
        self.catalog_cache_path = self.root / "models-cache.v1.json"
        self.lock_path = self.root / "auth.lock"
        self._thread_lock = threading.Lock()

    def assert_safe_location(self) -> None:
        """Raise :class:`CodexAuthError` unless this store sits on plain dirs.

        Both levels are checked, and the parent is the one that matters: a
        store's own ``private/`` lives inside a workspace subtree that other
        accounts' sandboxed ``exec`` can write, so a symlink *there* silently
        redirects the whole store — reading, and worse, relocating — to
        someone else's credentials.
        """
        _assert_safe_directory(self.root.parent)
        _assert_safe_directory(self.root)

    def _ensure_root(self) -> None:
        private_root = self.root.parent
        private_root.mkdir(parents=True, exist_ok=True)
        _assert_safe_directory(private_root)
        self.root.mkdir(exist_ok=True)
        _assert_safe_directory(self.root)
        os.chmod(private_root, stat.S_IRWXU)
        os.chmod(self.root, stat.S_IRWXU)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self._ensure_root()
            with _locked_file(self.lock_path):
                yield

    @staticmethod
    def _read_json(path: Path, *, code: str, message: str) -> dict[str, Any] | None:
        _assert_safe_regular_path(path)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexAuthError(code, message, 500) from exc
        if not isinstance(payload, dict):
            raise CodexAuthError(code, message, 500)
        return payload

    def _read_state_unlocked(self) -> dict[str, Any]:
        state = self._read_json(
            self.state_path,
            code="state_corrupt",
            message="Stored Codex authentication state is invalid.",
        )
        if state is None:
            return {"schema_version": _SCHEMA_VERSION, "generation": 0}
        generation = state.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise CodexAuthError(
                "state_corrupt",
                "Stored Codex authentication state is invalid.",
                500,
            )
        return state

    @staticmethod
    def _generation_changed() -> CodexAuthError:
        return CodexAuthError(
            "generation_changed",
            "Codex authentication changed while this operation was running.",
            409,
        )

    def current_generation(self) -> int:
        with self._locked():
            return int(self._read_state_unlocked()["generation"])

    def load_credentials(self) -> CodexCredentials | None:
        with self._locked():
            state_generation = int(self._read_state_unlocked()["generation"])
            payload = self._read_json(
                self.credentials_path,
                code="credential_corrupt",
                message="Stored Codex credentials are invalid.",
            )
            if payload is None:
                return None
            credentials = CodexCredentials.from_dict(payload)
            if credentials.generation != state_generation:
                return None
            return credentials

    def commit_credentials(
        self,
        credentials: CodexCredentials,
        expected_generation: int,
    ) -> CodexCredentials:
        with self._locked():
            state = self._read_state_unlocked()
            current_generation = int(state["generation"])
            if current_generation != expected_generation:
                raise self._generation_changed()
            next_generation = current_generation + 1
            committed = replace(
                credentials,
                schema_version=_SCHEMA_VERSION,
                generation=next_generation,
            )
            next_state = {
                **state,
                "schema_version": _SCHEMA_VERSION,
                "generation": next_generation,
            }
            _atomic_write_json(self.state_path, next_state)
            _atomic_write_json(self.credentials_path, committed.to_dict())
            return committed

    def clear_credentials(self, expected_generation: int | None = None) -> int:
        with self._locked():
            state = self._read_state_unlocked()
            current_generation = int(state["generation"])
            if expected_generation is not None and current_generation != expected_generation:
                raise self._generation_changed()
            next_generation = current_generation + 1
            _atomic_write_json(
                self.state_path,
                {
                    **state,
                    "schema_version": _SCHEMA_VERSION,
                    "generation": next_generation,
                },
            )
            for path in (self.credentials_path, self.catalog_cache_path):
                _assert_safe_regular_path(path)
                path.unlink(missing_ok=True)
            return next_generation

    def load_catalog_cache(self) -> dict[str, Any] | None:
        with self._locked():
            return self._read_json(
                self.catalog_cache_path,
                code="catalog_corrupt",
                message="Stored Codex model data is invalid.",
            )

    def save_catalog_cache(self, payload: Mapping[str, Any]) -> None:
        with self._locked():
            _atomic_write_json(self.catalog_cache_path, payload)

    def clear_catalog_cache(self) -> None:
        with self._locked():
            _assert_safe_regular_path(self.catalog_cache_path)
            self.catalog_cache_path.unlink(missing_ok=True)
