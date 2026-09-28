"""Immutable content scope, independent of authentication and account settings.

The default scope deliberately keeps the historical paths. Explicit workspaces
store application data inside their private directory. ContextVars propagate to
async tasks and ``asyncio.to_thread``: a running job keeps the scope in which it
was admitted, even when the browser subsequently selects another workspace.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from deeptutor.services.path_service import PathService
from deeptutor.services.workspace.models import WorkspaceError


@dataclass(frozen=True, slots=True)
class WorkspaceScope:
    workspace_id: str
    account_root: Path
    content_root: Path
    archived: bool = False


_scope: ContextVar[WorkspaceScope | None] = ContextVar("content_workspace_scope", default=None)


def get_workspace_scope() -> WorkspaceScope | None:
    return _scope.get()


@contextmanager
def account_workspace_context(account_root: Path):
    """Changing authenticated users drops an inherited content scope."""
    current = _scope.get()
    token = _scope.set(None) if current and current.account_root != account_root.resolve() else None
    try:
        yield
    finally:
        if token is not None:
            _scope.reset(token)


def current_workspace_id() -> str:
    scope = _scope.get()
    return scope.workspace_id if scope else ""


def workspace_url(url: str) -> str:
    """Pin a local resource URL to its originating data scope."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        return url
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["dt_workspace"] = current_workspace_id()
    return urlunsplit(parts._replace(query=urlencode(query)))


def resolve_workspace_scope(workspace_id: str | None = None) -> WorkspaceScope:
    from deeptutor.multi_user.paths import get_account_path_service
    from deeptutor.services.workspace import get_content_workspace_service

    base = get_account_path_service()
    service = get_content_workspace_service()
    service.assert_available()
    workspace_id = str(workspace_id or "").strip()
    if not workspace_id or workspace_id == service._builtin_id("general"):
        return WorkspaceScope("", base.workspace_root, base.get_workspace_dir())
    # Catalog resolution checks owner and kind. A session/system folder is
    # never an application data scope, even if its id is known to the caller.
    binding = service.validate_chat_binding(workspace_id, existing=True)
    row = next(row for row in service._catalog() if row["workspace_id"] == workspace_id)
    if row["kind"] != "workspace":
        raise WorkspaceError("This workspace cannot contain learning data.")
    return WorkspaceScope(workspace_id, base.workspace_root, binding.root, bool(row["archived"]))


def install_workspace_scope(workspace_id: str | None = None) -> WorkspaceScope:
    scope = resolve_workspace_scope(workspace_id)
    _scope.set(scope)
    return scope


@contextmanager
def workspace_context(workspace_id: str | WorkspaceScope | None = None) -> Iterator[WorkspaceScope]:
    scope = (
        workspace_id
        if isinstance(workspace_id, WorkspaceScope)
        else resolve_workspace_scope(workspace_id)
    )
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


class WorkspacePathService(PathService):
    """Data paths are workspace-local; credentials, memory and catalog stay global."""

    def __init__(self, account: PathService, scope: WorkspaceScope):
        private_root = scope.content_root / ".deeptutor" / "data"
        # Refuse redirected private stores before PathService resolves them.
        for candidate in (
            scope.content_root / ".deeptutor",
            private_root,
            private_root / "user",
            private_root / "user" / "workspace",
        ):
            if candidate.is_symlink():
                raise WorkspaceError("Workspace data directories cannot be symbolic links.")
        super().__init__(private_root)
        self.account = account
        self.scope = scope

    @property
    def project_root(self) -> Path:
        return self.account.project_root

    def get_settings_dir(self) -> Path:
        return self.account.get_settings_dir()

    def get_runtime_state_dir(self) -> Path:
        # Coordination/configuration state is account-owned. Individual
        # feature stores and session DBs use the private workspace data tree.
        return self.account.get_runtime_state_dir()

    def get_memory_dir(self) -> Path:
        return self.account.get_memory_dir()

    def get_workspace_feature_dir(self, feature):
        if feature == "memory":
            return self.account.get_workspace_feature_dir(feature)
        return super().get_workspace_feature_dir(feature)

    def migrate_legacy_memory_markdown(self) -> bool:
        return self.account.migrate_legacy_memory_markdown()


def scoped_path_service(account: PathService) -> PathService:
    scope = _scope.get()
    if scope is None or not scope.workspace_id:
        return account
    if account.workspace_root != scope.account_root:
        # Nested explicit user contexts must not inherit the parent's data
        # scope. Never silently route a mismatched identity to another root.
        raise WorkspaceError("The workspace belongs to a different account context.")
    from deeptutor.services.workspace import get_content_workspace_service

    current = get_content_workspace_service().binding_by_id(scope.workspace_id)
    if current.root != scope.content_root:
        raise WorkspaceError("Workspace storage moved. Reload before continuing.")
    return WorkspacePathService(account, scope)
