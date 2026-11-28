"""Owner-private GitHub credentials; never import another application's login."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import stat
import threading
import time
from typing import Iterator

from deeptutor.services.codex_auth.contracts import CodexAuthError
from deeptutor.services.codex_auth.storage import (
    _assert_safe_directory,
    _assert_safe_regular_path,
    _atomic_write_json,
    _locked_file,
)


@dataclass(frozen=True)
class GitHubToken:
    access: str = field(repr=False)
    expires: int
    account_id: str | None = None


@dataclass(frozen=True)
class CopilotAuthState:
    generation: int = 0
    credential_version: int = 0
    operation_state: str | None = None
    verification_uri: str | None = None
    user_code: str | None = None
    expires_at: float | None = None
    error_code: str | None = None


def _default_state() -> CopilotAuthState:
    return CopilotAuthState()


class GitHubCopilotStorage:
    def __init__(self, owner_root: Path) -> None:
        self.owner_root = owner_root
        self.root = owner_root / "private" / "github-copilot"
        self.credentials_path = self.root / "credentials.v1.json"
        self.state_path = self.root / "auth-state.v1.json"
        self._thread_lock = threading.Lock()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            with self._thread_lock:
                dirs: list[Path] = []
                if self.owner_root.parent.name == "user-secrets":
                    dirs.append(self.owner_root.parent)
                dirs.extend((self.owner_root, self.root.parent, self.root))
                for directory in dirs:
                    _assert_safe_directory(directory)
                    directory.mkdir(parents=True, exist_ok=True)
                    os.chmod(directory, stat.S_IRWXU)
                with _locked_file(self.root / "auth.lock"):
                    _assert_safe_regular_path(self.credentials_path)
                    _assert_safe_regular_path(self.state_path)
                    yield
        except CodexAuthError as exc:
            raise RuntimeError("GitHub Copilot credential storage uses an unsafe path.") from exc
        except OSError as exc:
            raise RuntimeError("GitHub Copilot credential storage could not be accessed.") from exc

    def _load_token_and_version_locked(self) -> tuple[GitHubToken | None, int]:
        if not self.credentials_path.exists():
            return None, 0
        try:
            payload = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError("Invalid schema")
            access = payload.get("access")
            expires = payload.get("expires")
            account = payload.get("account_id")
            raw_ver = payload.get("credential_version", 0)
            if (
                not isinstance(access, str)
                or not access
                or type(expires) is not int
                or (account is not None and not isinstance(account, str))
                or type(raw_ver) is not int
                or raw_ver < 0
            ):
                raise ValueError("Invalid credential fields")
            return GitHubToken(access=access, expires=expires, account_id=account), raw_ver
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "Stored GitHub Copilot credentials are invalid. "
                "Run: deeptutor provider login github-copilot"
            ) from exc

    def _read_state_locked(self) -> CopilotAuthState:
        if not self.state_path.exists():
            return _default_state()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError("Invalid state schema")
            generation = payload.get("generation")
            credential_version = payload.get("credential_version")
            if (
                type(generation) is not int
                or generation < 0
                or type(credential_version) is not int
                or credential_version < 0
            ):
                raise ValueError("Invalid state version fields")
            op_state = payload.get("operation_state")
            uri = payload.get("verification_uri")
            user_code = payload.get("user_code")
            expires_at = payload.get("expires_at")
            error_code = payload.get("error_code")
            return CopilotAuthState(
                generation=generation,
                credential_version=credential_version,
                operation_state=op_state if isinstance(op_state, str) else None,
                verification_uri=uri if isinstance(uri, str) else None,
                user_code=user_code if isinstance(user_code, str) else None,
                expires_at=float(expires_at) if isinstance(expires_at, (int, float)) else None,
                error_code=error_code if isinstance(error_code, str) else None,
            )
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("Stored GitHub Copilot auth state is invalid.") from exc

    def _write_state_locked(self, state: CopilotAuthState) -> None:
        _atomic_write_json(
            self.state_path,
            {
                "schema_version": 1,
                "generation": state.generation,
                "credential_version": state.credential_version,
                "operation_state": state.operation_state,
                "verification_uri": state.verification_uri,
                "user_code": state.user_code,
                "expires_at": state.expires_at,
                "error_code": state.error_code,
            },
        )

    def load(self) -> GitHubToken | None:
        with self._locked():
            token, _ = self._load_token_and_version_locked()
            return token

    def load_with_version(self) -> tuple[GitHubToken | None, int]:
        """Return ``(token, effective_credential_version)`` atomically under lock.

        ``credential_version`` is embedded inside ``credentials.v1.json`` as well
        as ``auth-state.v1.json``, so even if a crash interrupted writing the
        state file after replacing credentials, the effective version advances.
        """
        with self._locked():
            state = self._read_state_locked()
            token, token_ver = self._load_token_and_version_locked()
            return token, max(state.credential_version, token_ver)

    def read_snapshot(self) -> tuple[GitHubToken | None, CopilotAuthState]:
        """Atomically read token and durable auth state under the same file lock."""
        with self._locked():
            state = self._read_state_locked()
            token, token_ver = self._load_token_and_version_locked()
            if token_ver > state.credential_version:
                state = CopilotAuthState(
                    generation=state.generation,
                    credential_version=token_ver,
                    operation_state=state.operation_state,
                    verification_uri=state.verification_uri,
                    user_code=state.user_code,
                    expires_at=state.expires_at,
                    error_code=state.error_code,
                )
            return token, state

    def read_state(self) -> CopilotAuthState:
        with self._locked():
            return self._read_state_locked()

    def begin_cli_login(self) -> int:
        """Allocate a generation for an interactive CLI login so logout can supersede it."""
        with self._locked():
            state = self._read_state_locked()
            next_state = CopilotAuthState(
                generation=state.generation + 1,
                credential_version=state.credential_version,
                operation_state=None,
                verification_uri=None,
                user_code=None,
                expires_at=None,
                error_code=None,
            )
            self._write_state_locked(next_state)
            return next_state.generation

    def save(self, token: GitHubToken) -> None:
        """Persist token directly, bumping generation & credential version."""
        self.commit_token(token, expected_generation=None)

    def commit_token(
        self,
        token: GitHubToken,
        *,
        expected_generation: int | None = None,
    ) -> tuple[bool, CopilotAuthState]:
        """Atomically persist token and embedded credential_version if generation matches."""
        with self._locked():
            state = self._read_state_locked()
            if expected_generation is not None and state.generation != expected_generation:
                return False, state
            existing_token_ver = 0
            if self.credentials_path.exists():
                try:
                    _, existing_token_ver = self._load_token_and_version_locked()
                except RuntimeError:
                    existing_token_ver = 0
            next_generation = state.generation + 1
            next_cred_version = max(state.credential_version, existing_token_ver) + 1
            _atomic_write_json(
                self.credentials_path,
                {
                    "schema_version": 1,
                    "credential_version": next_cred_version,
                    **asdict(token),
                },
            )
            next_state = CopilotAuthState(
                generation=next_generation,
                credential_version=next_cred_version,
                operation_state="completed",
                verification_uri=None,
                user_code=None,
                expires_at=None,
                error_code=None,
            )
            self._write_state_locked(next_state)
            return True, next_state

    def reserve_device_flow(self) -> tuple[bool, CopilotAuthState]:
        """Atomically reserve a login generation unless an active unexpired flow exists."""
        with self._locked():
            state = self._read_state_locked()
            now = time.time()
            if (
                state.operation_state == "waiting"
                and state.verification_uri
                and state.user_code
                and state.expires_at is not None
                and state.expires_at > now
            ):
                return False, state
            next_state = CopilotAuthState(
                generation=state.generation + 1,
                credential_version=state.credential_version,
                operation_state="starting",
                verification_uri=None,
                user_code=None,
                expires_at=now + 30.0,
                error_code=None,
            )
            self._write_state_locked(next_state)
            return True, next_state

    def publish_device_prompt(
        self,
        *,
        expected_generation: int,
        verification_uri: str,
        user_code: str,
        expires_at: float,
    ) -> tuple[bool, CopilotAuthState]:
        """Publish public device-code prompt if ``expected_generation`` still owns the flow."""
        with self._locked():
            state = self._read_state_locked()
            if state.generation != expected_generation:
                return False, state
            next_state = CopilotAuthState(
                generation=state.generation,
                credential_version=state.credential_version,
                operation_state="waiting",
                verification_uri=verification_uri,
                user_code=user_code,
                expires_at=expires_at,
                error_code=None,
            )
            self._write_state_locked(next_state)
            return True, next_state

    def mark_flow_failed(
        self,
        *,
        expected_generation: int,
        error_code: str,
    ) -> tuple[bool, CopilotAuthState]:
        """Record terminal failure and bump generation so late publishes cannot overwrite it."""
        with self._locked():
            state = self._read_state_locked()
            if state.generation != expected_generation:
                return False, state
            next_state = CopilotAuthState(
                generation=state.generation + 1,
                credential_version=state.credential_version,
                operation_state="failed",
                verification_uri=None,
                user_code=None,
                expires_at=None,
                error_code=error_code,
            )
            self._write_state_locked(next_state)
            return True, next_state

    def cancel_flow(self) -> CopilotAuthState:
        """Invalidate any in-flight device flow across all workers."""
        with self._locked():
            state = self._read_state_locked()
            next_state = CopilotAuthState(
                generation=state.generation + 1,
                credential_version=state.credential_version,
                operation_state="cancelled",
                verification_uri=None,
                user_code=None,
                expires_at=None,
                error_code=None,
            )
            self._write_state_locked(next_state)
            return next_state

    def clear_credentials(self) -> tuple[bool, CopilotAuthState]:
        """Atomically delete stored token and invalidate any in-flight flows across workers."""
        with self._locked():
            try:
                state = self._read_state_locked()
            except RuntimeError:
                state = _default_state()
            existing_token_ver = 0
            if self.credentials_path.exists():
                try:
                    _, existing_token_ver = self._load_token_and_version_locked()
                except RuntimeError:
                    existing_token_ver = 0
            removed = self.credentials_path.exists()
            if removed:
                self.credentials_path.unlink(missing_ok=True)
            next_state = CopilotAuthState(
                generation=state.generation + 1,
                credential_version=max(state.credential_version, existing_token_ver) + 1,
                operation_state=None,
                verification_uri=None,
                user_code=None,
                expires_at=None,
                error_code=None,
            )
            self._write_state_locked(next_state)
            return removed, next_state

    def delete(self) -> bool:
        removed, _ = self.clear_credentials()
        return removed


def _validate_owner_id(owner_id: str) -> str:
    cleaned = (owner_id or "").strip()
    if (
        not cleaned
        or cleaned in {".", ".."}
        or "/" in cleaned
        or "\\" in cleaned
        or "\x00" in cleaned
        or ".." in cleaned
    ):
        raise RuntimeError("Unsafe GitHub Copilot owner identifier.")
    return cleaned


def resolve_copilot_owner_id() -> str:
    """Resolve the distinct human account owner for GitHub Copilot credentials.

    CLI runs (no request scope) and partner turns map to ``LOCAL_ADMIN_ID``.
    Authenticated human accounts — including distinct administrators who share
    ``admin_scope`` in production — each map to their own ``user.id`` so two
    admins never share or cancel each other's Copilot login.
    """
    from deeptutor.core.identities import is_partner_user_id
    from deeptutor.multi_user.context import get_current_user_or_none
    from deeptutor.multi_user.paths import LOCAL_ADMIN_ID

    user = get_current_user_or_none()
    if user is None or is_partner_user_id(user.id):
        return LOCAL_ADMIN_ID
    return _validate_owner_id(user.id)


def get_copilot_owner_scope() -> tuple[Path, str]:
    """Return the trusted ``(runtime_home, owner_id)`` pair for the current request."""
    from deeptutor.runtime.home import get_runtime_home

    return get_runtime_home(), resolve_copilot_owner_id()


def get_github_copilot_storage() -> GitHubCopilotStorage:
    from deeptutor.multi_user.paths import USER_SECRETS_DIRNAME

    # Resolve home and owner per call without pre-creating or resolving symlinks:
    # GitHubCopilotStorage._locked() validates every path component first.
    runtime_home, owner_id = get_copilot_owner_scope()
    owner_root = runtime_home / "data" / "system" / USER_SECRETS_DIRNAME / owner_id
    return GitHubCopilotStorage(owner_root)


__all__ = [
    "CopilotAuthState",
    "GitHubCopilotStorage",
    "GitHubToken",
    "get_copilot_owner_scope",
    "get_github_copilot_storage",
    "resolve_copilot_owner_id",
]
