"""Path resolution for admin-local and per-user workspaces.

Everything lives under ``<runtime-home>/data`` so a deployment has exactly
one tree to mount and back up:

* ``data/user``           — the admin workspace (admin scope root is ``data/``)
* ``data/users/<uid>``    — one workspace per non-admin user
* ``data/partners/<id>``  — partner (synthetic-user) workspaces
* ``data/system``         — deployment state: accounts, grants, audit, and the
  per-owner secrets of :func:`get_owner_secrets_dir`. Never mounted into the
  sandbox runner — see ``docker-compose.yml``.

Deployments upgraded from the sibling ``multi-user/`` layout are migrated
in place by :func:`migrate_legacy_multi_user_tree`.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import shutil
import stat
import threading
from typing import Iterator

from deeptutor.runtime.home import get_runtime_home
from deeptutor.services.path_service import PathService

from .models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME, CurrentUser, UserScope

logger = logging.getLogger(__name__)

PROJECT_ROOT = get_runtime_home()
ADMIN_WORKSPACE_ROOT = PROJECT_ROOT / "data"
USERS_ROOT = ADMIN_WORKSPACE_ROOT / "users"
SYSTEM_ROOT = ADMIN_WORKSPACE_ROOT / "system"
LEGACY_MULTI_USER_ROOT = PROJECT_ROOT / "multi-user"
USER_SECRETS_DIRNAME = "user-secrets"

_path_services: dict[str, PathService] = {}

_legacy_migration_lock = threading.Lock()
_legacy_migration_done = False


def migrate_legacy_multi_user_tree() -> None:
    """One-time move of the pre-v1.5 sibling ``multi-user/`` tree into ``data/``.

    ``multi-user/_system`` becomes ``data/system``; every other child is a
    user id directory and becomes ``data/users/<uid>``. Existing targets are
    never overwritten — leftovers stay in place and are logged so an operator
    can reconcile by hand. Idempotent and cheap once migrated (one existence
    check), so callers on the auth/grants/workspace read paths can invoke it
    unconditionally.
    """
    global _legacy_migration_done
    if _legacy_migration_done:
        return
    with _legacy_migration_lock:
        if _legacy_migration_done:
            return
        _legacy_migration_done = True
        legacy = LEGACY_MULTI_USER_ROOT
        if not legacy.is_dir():
            return
        leftovers: list[str] = []
        for child in sorted(legacy.iterdir()):
            target = SYSTEM_ROOT if child.name == "_system" else USERS_ROOT / child.name
            if target.exists():
                leftovers.append(child.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(child), str(target))
            logger.info("Migrated legacy multi-user path %s -> %s", child, target)
        if leftovers:
            logger.warning(
                "Legacy multi-user tree partially migrated; reconcile by hand: %s",
                ", ".join(str(legacy / name) for name in leftovers),
            )
            return
        try:
            legacy.rmdir()
        except OSError:
            logger.warning("Could not remove legacy multi-user root %s", legacy)


def admin_scope() -> UserScope:
    return UserScope(kind="admin", user_id=LOCAL_ADMIN_ID, root=ADMIN_WORKSPACE_ROOT.resolve())


def local_admin_user() -> CurrentUser:
    return CurrentUser(
        id=LOCAL_ADMIN_ID,
        username=LOCAL_ADMIN_USERNAME,
        role="admin",
        scope=admin_scope(),
    )


def scope_for_user(user_id: str, *, is_admin: bool) -> UserScope:
    if is_admin:
        return admin_scope()
    migrate_legacy_multi_user_tree()
    return UserScope(kind="user", user_id=user_id, root=(USERS_ROOT / user_id).resolve())


def ensure_user_workspace(user_id: str) -> Path:
    return ensure_scope_workspace(scope_for_user(user_id, is_admin=False))


def ensure_scope_workspace(scope: UserScope) -> Path:
    """Create the workspace tree for *scope* at its own root.

    Resolving from ``scope.root`` (instead of recomputing ``USERS_ROOT /
    user_id``) keeps this correct for synthetic scopes whose root lives
    elsewhere — e.g. partner workspaces under ``data/partners/<id>/workspace``.
    For regular users both paths are identical.
    """
    root = scope.root.resolve()
    PathService(workspace_root=root).ensure_all_directories()
    (root / "knowledge_bases").mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(parents=True, exist_ok=True)
    return root


def ensure_system_dirs() -> None:
    migrate_legacy_multi_user_tree()
    for child in ("auth", "grants", "audit", "indexes"):
        (SYSTEM_ROOT / child).mkdir(parents=True, exist_ok=True)
    # Per-owner secrets (see ``get_owner_secrets_dir``). Declared here, and its
    # mode set once at startup, so the per-request path only has to create the
    # one owner directory below it.
    secrets_root = SYSTEM_ROOT / USER_SECRETS_DIRNAME
    secrets_root.mkdir(parents=True, exist_ok=True)
    os.chmod(secrets_root, stat.S_IRWXU)


def get_path_service_for_scope(scope: UserScope) -> PathService:
    key = scope.cache_key
    service = _path_services.get(key)
    if service is None:
        service = PathService(workspace_root=scope.root)
        _path_services[key] = service
    return service


def get_admin_path_service() -> PathService:
    return get_path_service_for_scope(admin_scope())


def get_current_path_service() -> PathService:
    from .context import get_current_user_or_none

    user = get_current_user_or_none()
    if user is None:
        return PathService.get_instance()
    if user.scope.kind == "user":
        ensure_scope_workspace(user.scope)
    return get_path_service_for_scope(user.scope)


def _resolve_owner() -> tuple[str, PathService]:
    """The owning account's id and its workspace, from one decision.

    Owner-keyed assets are addressed two ways — by directory (a workspace root)
    and by name (a secrets directory) — and the two must never disagree: keying
    a secret by one identity while writing it under another is exactly how one
    account's credentials end up in another's directory. So both come from here,
    and neither is recovered from the other afterwards (a path cannot be
    reversed back into an identity: symlinked roots resolve elsewhere, and a
    "give up and assume admin" fallback fails open onto the most privileged
    account there is).
    """
    from deeptutor.services.partners.scope import is_partner_user_id

    from .context import get_current_user_or_none

    user = get_current_user_or_none()
    if user is None:
        # No request scope: CLI runs and background jobs act as the deployment.
        return LOCAL_ADMIN_ID, PathService.get_instance()
    if is_partner_user_id(user.id):
        # A partner is a synthetic user, not a person: it has a workspace but no
        # account, so an asset keyed to an account belongs to its owner.
        return LOCAL_ADMIN_ID, get_admin_path_service()
    if user.scope.kind == "user":
        ensure_scope_workspace(user.scope)
        return user.id, get_path_service_for_scope(user.scope)
    return LOCAL_ADMIN_ID, get_path_service_for_scope(user.scope)


def get_owner_path_service() -> PathService:
    """Resolve to the root of the human account that owns the current scope.

    A partner is a *synthetic* user, not a person: it has a workspace under
    ``data/partners/<id>`` but no account of its own, and that workspace is
    created by — and lives inside — the admin tree. Assets keyed to a real
    account rather than to a workspace (OAuth credentials, above all) must
    therefore resolve to the owner, or a partner turn would look for a login
    that can never exist there. Every other scope owns itself.

    Use this only for owner-keyed assets; workspace-keyed ones (rag, skills,
    notebooks, memory) belong to the partner and go through
    :func:`get_current_path_service`.
    """
    return _resolve_owner()[1]


def owner_secrets_dir(owner_id: str) -> Path:
    """Secrets directory of a *named* owner, independent of the request scope.

    Needed because not every reader runs inside a request: an MCP connection
    task resolves its own server's credentials long after the turn that created
    it, and must address them by the owner it was opened for rather than by
    whoever happens to be current.
    """
    # SYSTEM_ROOT is read per call so a monkey-patched root (tests) is honored.
    secrets_root = SYSTEM_ROOT / USER_SECRETS_DIRNAME
    owner_dir = secrets_root / (owner_id or LOCAL_ADMIN_ID)
    owner_dir.mkdir(parents=True, exist_ok=True)
    # Re-asserted rather than assumed from ``ensure_system_dirs``: this is the
    # only guarantee that holds when a directory was created by something else
    # (an operator, a restore, a caller that skipped startup), and the cost of
    # being wrong is a world-readable refresh token.
    for path in (secrets_root, owner_dir):
        os.chmod(path, stat.S_IRWXU)
    return owner_dir.resolve()


def get_owner_secrets_dir() -> Path:
    """Owner-private directory for secrets the sandbox must never see.

    ``data/system`` is the one branch of the tree the sandbox runner does not
    mount, so credentials that authorize a *person* — OAuth refresh tokens above
    all — belong here rather than inside a workspace subtree that every
    account's ``exec`` shares. The owner is resolved by :func:`_resolve_owner`,
    the same decision :func:`get_owner_path_service` uses, so a partner turn
    lands on the directory of the human who owns it.

    Laid out like a user root (``private/<asset>/``) so a store written against
    one can be pointed here without changing what it knows about its own files.
    """
    return owner_secrets_dir(current_owner_id())


def current_owner_id() -> str:
    """Id of the account owning the current scope (a partner's is its owner's)."""
    return _resolve_owner()[0]


@contextmanager
def user_context(user: CurrentUser) -> Iterator[None]:
    from .context import reset_current_user, set_current_user

    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)
