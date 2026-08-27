"""Book-level permissions for shared books in multi-user deployments.

The admin workspace is the shared catalogue.  A normal user's own workspace
remains private and fully editable; this model only controls access to books in
the shared catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .models import CurrentUser

BookPermissionLevel = Literal["none", "read", "edit"]
BookDefaultLevel = Literal["none", "read"]
BOOK_PERMISSION_LEVELS = frozenset({"none", "read", "edit"})
BOOK_DEFAULT_LEVELS = frozenset({"none", "read"})


@dataclass(frozen=True, slots=True)
class BookPermission:
    """Creation capability plus shared-catalogue defaults and overrides."""

    create: bool = True
    default: BookDefaultLevel = "none"
    books: tuple[tuple[str, BookPermissionLevel], ...] = ()

    def level_for(self, book_id: str) -> BookPermissionLevel:
        for candidate, level in self.books:
            if candidate == book_id:
                return level
        return self.default

    def books_dict(self) -> dict[str, BookPermissionLevel]:
        return dict(self.books)


# Missing, malformed, and newly created records all preserve the pre-feature
# ability to create a personal book, but expose no admin book implicitly.
DEFAULT_BOOK_PERMISSION = BookPermission()
ADMIN_BOOK_PERMISSION = BookPermission(create=True, default="read")


def normalize_book_permission(raw: Any) -> BookPermission:
    """Return a fail-closed canonical permission from any persisted shape.

    The external reference implementation had earlier ``mode/actions`` shapes.
    We accept those conservatively for operators who tried that build: delete is
    collapsed to edit, and an absent/unknown legacy shape never grants access.
    """

    if not isinstance(raw, dict):
        return DEFAULT_BOOK_PERMISSION

    if any(key in raw for key in ("create", "default", "books")):
        create = raw.get("create", True) is True
        default_raw = raw.get("default")
        default: BookDefaultLevel = default_raw if default_raw in BOOK_DEFAULT_LEVELS else "none"
        books: list[tuple[str, BookPermissionLevel]] = []
        raw_books = raw.get("books")
        if isinstance(raw_books, dict):
            for raw_id, raw_level in raw_books.items():
                book_id = str(raw_id or "").strip()
                if not book_id:
                    continue
                if raw_level == "delete":
                    raw_level = "edit"
                if raw_level in BOOK_PERMISSION_LEVELS:
                    books.append((book_id, raw_level))
        return BookPermission(create=create, default=default, books=tuple(books))

    mode = str(raw.get("mode") or "none")
    actions = raw.get("actions") if isinstance(raw.get("actions"), dict) else {}
    create = actions.get("create", True) is True
    writable = actions.get("edit") is True or actions.get("delete") is True
    level: BookPermissionLevel = "edit" if writable else "read"
    if mode == "all":
        # A legacy all-mode is honoured because it was an explicit stored
        # choice, but it can never imply write access for future books.
        return BookPermission(create=create, default="read")
    if mode == "list" and isinstance(raw.get("book_ids"), (list, tuple, set)):
        seen: set[str] = set()
        books = []
        for item in raw["book_ids"]:
            book_id = str(item or "").strip()
            if book_id and book_id not in seen:
                seen.add(book_id)
                books.append((book_id, level))
        return BookPermission(create=create, books=tuple(books))
    return BookPermission(create=create)


def public_permission_dict(permission: BookPermission) -> dict[str, Any]:
    return {
        "create": permission.create,
        "default": permission.default,
        "books": permission.books_dict(),
    }


def canonical_book_permission(raw: Any) -> dict[str, Any]:
    return public_permission_dict(normalize_book_permission(raw))


def permission_for_user(user: CurrentUser) -> BookPermission:
    if user.is_admin:
        return ADMIN_BOOK_PERMISSION
    from .identity import get_user

    record = get_user(user.username) or {}
    return normalize_book_permission(record.get("book_permission"))


__all__ = [
    "ADMIN_BOOK_PERMISSION",
    "BOOK_DEFAULT_LEVELS",
    "BOOK_PERMISSION_LEVELS",
    "DEFAULT_BOOK_PERMISSION",
    "BookDefaultLevel",
    "BookPermission",
    "BookPermissionLevel",
    "canonical_book_permission",
    "normalize_book_permission",
    "permission_for_user",
    "public_permission_dict",
]
