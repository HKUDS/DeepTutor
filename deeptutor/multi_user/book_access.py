"""One access resolver for personal and admin-shared books."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from deeptutor.book.engine import BookEngine, get_book_engine
from deeptutor.book.learning_overlay import BookLearningOverlay
from deeptutor.book.models import Book, Progress
from deeptutor.book.storage import BookStorage, get_book_storage

from .book_permission import BookPermissionLevel, permission_for_user
from .context import get_current_user
from .paths import get_admin_path_service, get_current_path_service

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


def resolve_book(book_id: str) -> ResolvedBook | None:
    """Resolve own-first, then shared, returning None for denied/unknown ids."""

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

    admin_storage = _admin_storage()
    if not admin_storage.book_exists(book_id):
        return None
    level = permission_for_user(user).level_for(book_id)
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


def accessible_books() -> list[tuple[Book, ResolvedBook]]:
    """List own plus allowed shared books, resolving permission only once."""

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
            for book in admin_engine.list_books():
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
    results.sort(key=lambda item: item[0].updated_at, reverse=True)
    return results


def shared_book_exists(book_id: str) -> bool:
    return _admin_storage().book_exists(book_id)


def admin_book_catalog() -> list[dict[str, Any]]:
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
    "can_create_book",
    "resolve_book",
    "shared_book_exists",
]
