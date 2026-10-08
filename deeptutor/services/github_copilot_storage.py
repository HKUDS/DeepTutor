"""Owner-private GitHub credentials; never import another application's login."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import stat
import threading
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


class GitHubCopilotStorage:
    def __init__(self, owner_root: Path) -> None:
        self.root = owner_root / "private" / "github-copilot"
        self.credentials_path = self.root / "credentials.v1.json"
        self._thread_lock = threading.Lock()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            with self._thread_lock:
                for directory in (self.root.parent, self.root):
                    _assert_safe_directory(directory)
                    directory.mkdir(parents=True, exist_ok=True)
                    os.chmod(directory, stat.S_IRWXU)
                with _locked_file(self.root / "auth.lock"):
                    _assert_safe_regular_path(self.credentials_path)
                    yield
        except CodexAuthError as exc:
            raise RuntimeError("GitHub Copilot credential storage uses an unsafe path.") from exc

    def load(self) -> GitHubToken | None:
        with self._locked():
            if not self.credentials_path.exists():
                return None
            try:
                payload = json.loads(self.credentials_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                    raise ValueError("Invalid schema")
                access = payload.get("access")
                expires = payload.get("expires")
                account = payload.get("account_id")
                if (
                    not isinstance(access, str)
                    or not access
                    or type(expires) is not int
                    or (account is not None and not isinstance(account, str))
                ):
                    raise ValueError("Invalid credential fields")
                return GitHubToken(access=access, expires=expires, account_id=account)
            except (OSError, ValueError) as exc:
                raise RuntimeError(
                    "Stored GitHub Copilot credentials are invalid. "
                    "Run: deeptutor provider login github-copilot"
                ) from exc

    def save(self, token: GitHubToken) -> None:
        with self._locked():
            _atomic_write_json(self.credentials_path, {"schema_version": 1, **asdict(token)})


def get_github_copilot_storage() -> GitHubCopilotStorage:
    from deeptutor.multi_user.paths import get_owner_secrets_dir
    from deeptutor.runtime.home import get_runtime_home

    # Resolve the home per call: `init --home` can change it after paths was imported.
    return GitHubCopilotStorage(get_owner_secrets_dir(runtime_home=get_runtime_home()))
