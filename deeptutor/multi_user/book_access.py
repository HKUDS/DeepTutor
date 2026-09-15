"""One access resolver for personal and admin-shared books."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from deeptutor.book.learning_overlay import BookLearningOverlay
from deeptutor.book.models import Book, Progress
from deeptutor.book.storage import BookStorage, get_book_storage

from .book_permission import BookPermissionLevel, permission_for_user
from .context import get_current_user
from .paths import get_admin_path_service, get_current_path_service

if TYPE_CHECKING:
    from deeptutor.book.engine import BookEngine

BookSource = Literal["own", "shared"]


def _auth_enabled() -> bool:
    from deeptutor.services.auth import AUTH_ENABLED

    return bool(AUTH_ENABLED)


def _admin_storage() -> BookStorage:
    return BookStorage(path_service=get_admin_path_service())


@dataclass(frozen=True, slots=True)
class ResolvedBook:
    """A Book bound to its canonical store and the caller's learning store."""

    engine: BookEngine
    source: BookSource
    permission: BookPermissionLevel
    can_edit: bool
    can_delete: bool
    learning: BookStorage | BookLearningOverlay

    @property
    def is_shared(self) -> bool:
        return self.source == "shared"

    def capabilities(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "permission": self.permission,
            "can_edit": self.can_edit,
            "can_delete": self.can_delete,
        }

    def load_progress(self, book_id: str) -> Progress:
        progress = self.learning.load_progress(book_id)
        return progress or Progress(book_id=book_id)

    def reading_summary(self, book: Book) -> dict[str, Any]:
        progress = self.learning.load_progress(book.id)
        total = max(0, book.page_count)
        if progress is None:
            return {
                "current_page_id": "",
                "visited_pages": 0,
                "total_pages": total,
                "percent": 0,
            }
        visited = len(set(progress.visited_page_ids))
        return {
            "current_page_id": progress.current_page_id,
            "visited_pages": visited,
            "total_pages": total,
            "percent": round(min(100.0, visited * 100.0 / total)) if total else 0,
        }


def can_create_book() -> bool:
    if not _auth_enabled() or get_current_user().is_admin:
        return True
    return permission_for_user(get_current_user()).create


def _peer_book_storage(owner_id: str) -> BookStorage:
    """Storage rooted at another account's workspace."""

    from .paths import get_path_service_for_scope, scope_for_user

    return BookStorage(
        path_service=get_path_service_for_scope(scope_for_user(owner_id, is_admin=False))
    )


def _peer_book_owner(book_id: str, *, exclude: set[str]) -> str | None:
    """Find the workspace that holds *book_id*, or None.

    A peer grant names a book that lives in another ordinary user's workspace,
    so the grant alone cannot say whose it is. The deployment's book count is
    of the order of a hundred, so scanning ``data/users/*/`` per lookup is
    acceptable; the per-scope path services are cached, so each scan is one
    ``stat`` per user directory.
    """

    from . import paths

    users_root = paths.USERS_ROOT
    try:
        candidates = sorted(
            child for child in users_root.iterdir() if child.is_dir() and child.name not in exclude
        )
    except OSError:
        return None
    for child in candidates:
        try:
            if _peer_book_storage(child.name).book_exists(book_id):
                return child.name
        except (OSError, ValueError):
            continue
    return None


def _peer_resolved_book(book_id: str, user: Any, level: BookPermissionLevel) -> ResolvedBook | None:
    """Resolve a book granted to *user* that lives in a peer workspace.

    Returns None when the grant is stale (the owning workspace is gone), so
    fail-close never depends on ACL hygiene.
    """

    from deeptutor.book.engine import BookEngine

    owner_id = _peer_book_owner(book_id, exclude={user.id})
    if owner_id is None:
        return None
    storage = _peer_book_storage(owner_id)
    if storage.load_book(book_id) is None:
        return None
    return ResolvedBook(
        engine=BookEngine(storage=storage),
        source="shared",
        permission=level,
        can_edit=level == "edit",
        can_delete=False,
        learning=BookLearningOverlay(get_current_path_service()),
    )


def resolve_book(book_id: str) -> ResolvedBook | None:
    """Resolve own-first, then shared, returning None for denied/unknown ids."""

    from deeptutor.book.engine import BookEngine, get_book_engine

    own_storage = get_book_storage()
    user = get_current_user()
    if own_storage.book_exists(book_id):
        return ResolvedBook(
            engine=get_book_engine(),
            source="own",
            permission="edit",
            can_edit=True,
            can_delete=True,
            learning=own_storage,
        )
    if not _auth_enabled() or user.is_admin:
        return None

    level = permission_for_user(user).level_for(book_id)
    admin_storage = _admin_storage()
    if admin_storage.book_exists(book_id):
        if level == "none":
            return None
        return ResolvedBook(
            engine=BookEngine(storage=admin_storage),
            source="shared",
            permission=level,
            can_edit=level == "edit",
            can_delete=False,
            learning=BookLearningOverlay(get_current_path_service()),
        )
    if level == "none":
        return None
    return _peer_resolved_book(book_id, user, level)


def accessible_books() -> list[tuple[Book, ResolvedBook]]:
    """List own plus allowed shared books, resolving permission only once."""

    from deeptutor.book.engine import BookEngine, get_book_engine

    own_storage = get_book_storage()
    own_engine = get_book_engine()
    results: list[tuple[Book, ResolvedBook]] = []
    own_ids: set[str] = set()
    for book in own_engine.list_books():
        own_ids.add(book.id)
        results.append(
            (
                book,
                ResolvedBook(
                    engine=own_engine,
                    source="own",
                    permission="edit",
                    can_edit=True,
                    can_delete=True,
                    learning=own_storage,
                ),
            )
        )

    user = get_current_user()
    if _auth_enabled() and not user.is_admin:
        permission = permission_for_user(user)
        if permission.default != "none" or permission.books:
            admin_storage = _admin_storage()
            admin_engine = BookEngine(storage=admin_storage)
            overlay = BookLearningOverlay(get_current_path_service())
            admin_ids: set[str] = set()
            for book in admin_engine.list_books():
                admin_ids.add(book.id)
                if book.id in own_ids:
                    continue
                level = permission.level_for(book.id)
                if level == "none":
                    continue
                results.append(
                    (
                        book,
                        ResolvedBook(
                            engine=admin_engine,
                            source="shared",
                            permission=level,
                            can_edit=level == "edit",
                            can_delete=False,
                            learning=overlay,
                        ),
                    )
                )
            # Peer grants: books another ordinary user's workspace owns and
            # this account was explicitly granted. A stale grant (workspace
            # deleted) resolves to nothing and is skipped, fail-close.
            for granted_id, level in permission.books:
                if level == "none" or granted_id in own_ids or granted_id in admin_ids:
                    continue
                resolved = _peer_resolved_book(granted_id, user, level)
                if resolved is None:
                    continue
                book = resolved.engine.load_book(granted_id)
                if book is None:
                    continue
                results.append((book, resolved))
    results.sort(key=lambda item: item[0].updated_at, reverse=True)
    return results


def shared_book_exists(book_id: str) -> bool:
    return _admin_storage().book_exists(book_id)


def book_share_grants(book_id: str) -> list[dict[str, str]]:
    """Every account holding an explicit grant on *book_id*.

    Drives the owner's share dialog: who the book is shared with and at which
    level. Admin-catalogue grants and peer grants are indistinguishable here —
    both are plain ``book_permission.books`` entries — and that is fine: an
    owner seeing (and being able to revoke) an admin-set grant is honest
    reporting of who can read the book.
    """

    from .book_permission import normalize_book_permission
    from .identity import load_users

    grants: list[dict[str, str]] = []
    for username, record in load_users().items():
        permission = normalize_book_permission(record.get("book_permission"))
        level = permission.books_dict().get(book_id)
        # Only explicit per-book entries count. The admin record's default
        # "read" (and any user default) is not a grant on this book — a share
        # dialog that listed the admin as a revocable grantee would be lying.
        if level is None or level == "none":
            continue
        grants.append(
            {
                "user_id": str(record.get("id") or ""),
                "username": username,
                "level": level,
            }
        )
    return grants


def share_candidate_users() -> list[dict[str, str]]:
    """Ordinary, enabled accounts a book owner may share a book with."""

    from .identity import load_users

    candidates: list[dict[str, str]] = []
    for username, record in load_users().items():
        if str(record.get("role") or "user") == "admin":
            continue
        if bool(record.get("disabled", False)):
            continue
        candidates.append(
            {
                "user_id": str(record.get("id") or ""),
                "username": username,
            }
        )
    return sorted(candidates, key=lambda item: item["username"])


def admin_book_catalog() -> list[dict[str, Any]]:
    from deeptutor.book.engine import BookEngine

    engine = BookEngine(storage=_admin_storage())
    return [
        {
            "book_id": book.id,
            "title": book.title,
            "status": book.status.value,
            "updated_at": book.updated_at,
        }
        for book in engine.list_books()
    ]


__all__ = [
    "ResolvedBook",
    "accessible_books",
    "admin_book_catalog",
    "book_share_grants",
    "can_create_book",
    "resolve_book",
    "share_candidate_users",
    "shared_book_exists",
]
