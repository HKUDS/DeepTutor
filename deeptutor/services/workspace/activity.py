"""Cross-process maintenance exclusion for requests and detached data writers."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import sqlite3

from deeptutor.services.workspace.models import WorkspaceError


def acquire_activity(*, exclusive: bool = False):
    from deeptutor.multi_user.paths import get_account_path_service

    root = get_account_path_service().ensure_runtime_state_dir()
    # A rollback-journal SQLite read transaction is a cross-process shared
    # lease, including on Windows. Closing the connection releases the lease.
    handle = sqlite3.connect(
        root / "workspace-activity.sqlite3", timeout=0, check_same_thread=False
    )
    try:
        handle.execute("BEGIN EXCLUSIVE" if exclusive else "BEGIN")
        handle.execute("PRAGMA user_version").fetchone()
        if not exclusive:
            from deeptutor.services.workspace.data_migration import assert_no_pending_recovery

            assert_no_pending_recovery()
    except sqlite3.OperationalError as exc:
        handle.close()
        raise WorkspaceError(
            "Workspace data is busy. Wait for active requests and tasks before retrying."
        ) from exc
    except BaseException:
        handle.close()
        raise
    return handle


@contextmanager
def data_activity(*, exclusive: bool = False):
    handle = acquire_activity(exclusive=exclusive)
    try:
        yield
    finally:
        handle.close()


def workspace_writer(function):
    """A detached task owns its lock independently of its initiating request."""

    @wraps(function)
    async def guarded(*args, **kwargs):
        from deeptutor.services.workspace.context import (
            get_workspace_scope,
            resolve_workspace_scope,
        )

        scope = get_workspace_scope()
        if scope is not None and resolve_workspace_scope(scope.workspace_id).archived:
            raise WorkspaceError("Restore this workspace before changing its data.")
        with data_activity():
            return await function(*args, **kwargs)

    return guarded


class WorkspaceActivityMiddleware:
    """Hold an authenticated request's lock through its ASGI/background lifetime."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        finally:
            handle = scope.get("state", {}).pop("workspace_activity", None)
            if handle is not None:
                handle.close()
