"""Periodic owner-scoped Codex catalog refresh."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import os
from pathlib import Path

from .constants import CODEX_AUTO_REFRESH_POLL_SECONDS
from .service import get_codex_oauth_service
from .contracts import CodexAuthError
from .storage import _assert_safe_directory, _assert_safe_regular_path

logger = logging.getLogger(__name__)


def _has_credentials(root: Path) -> bool:
    try:
        for parent in (root, root / "private", root / "private" / "openai-codex"):
            _assert_safe_directory(parent)
        path = root / "private" / "openai-codex" / "credentials.v1.json"
        _assert_safe_regular_path(path)
        return path.is_file()
    except (OSError, CodexAuthError):
        return False


class CodexCatalogRefreshScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self) -> None:
        from deeptutor.core.identities import is_partner_user_id
        from deeptutor.multi_user import identity, paths
        from deeptutor.multi_user.models import CurrentUser, LOCAL_ADMIN_ID

        candidate_ids: list[str] = []
        if _has_credentials(paths.get_admin_path_service().get_user_root()):
            candidate_ids.append(LOCAL_ADMIN_ID)
        root = paths.SYSTEM_ROOT / paths.USER_SECRETS_DIRNAME
        _assert_safe_directory(paths.SYSTEM_ROOT)
        _assert_safe_directory(root)
        if root.is_dir():
            for child in sorted(root.iterdir(), key=lambda p: p.name):
                if is_partner_user_id(child.name) or child.name in candidate_ids:
                    continue
                if _has_credentials(child):
                    candidate_ids.append(child.name)

        admin = paths.local_admin_user()
        for owner_id in candidate_ids:
            try:
                if owner_id == LOCAL_ADMIN_ID:
                    if not (
                        _has_credentials(paths.get_admin_path_service().get_user_root())
                        or _has_credentials(root / LOCAL_ADMIN_ID)
                    ):
                        continue
                    user = admin
                else:
                    child = root / owner_id
                    if not _has_credentials(child):
                        continue
                    # Resolve identity right before refreshing this owner so accounts
                    # deleted or disabled while earlier owners refreshed are skipped.
                    resolved = identity.get_user_by_id(owner_id)
                    if resolved is None:
                        continue
                    username, record = resolved
                    if bool(record.get("disabled", False)) or str(record.get("role") or "user") == "admin":
                        continue
                    user = CurrentUser(
                        id=owner_id,
                        username=username,
                        role="user",
                        scope=paths.scope_for_user(owner_id, is_admin=False),
                    )
                    with paths.user_context(user):
                        if paths.get_owner_secrets_dir().resolve() != child.resolve():
                            continue
                with paths.user_context(user):
                    await get_codex_oauth_service().refresh_models_if_due(
                        lease_owner=f"scheduler:{os.getpid()}"
                    )
            except Exception:
                logger.warning("Codex catalog refresh failed for an owner")

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.warning("Codex catalog refresh scan failed")
            await asyncio.sleep(CODEX_AUTO_REFRESH_POLL_SECONDS + os.getpid() % 11)
