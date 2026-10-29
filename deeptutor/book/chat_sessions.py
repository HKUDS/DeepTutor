"""The conversations a book owns.

A page's tutor chat is an ordinary session, and the book records it per page
in ``page_chat_sessions``. The session carries the same link back —
``book_id`` and ``book_page_id`` in its preferences — so the sidebar files it
under its book and opens it on its page, the way mastery and reading
conversations already are. The two are written together; links recorded only
on the book side before this existed are adopted once at startup.
"""

from __future__ import annotations

import asyncio
from typing import Any

BOOK_ID = "book_id"
BOOK_PAGE_ID = "book_page_id"


async def tag_book_chat_session(store: Any, *, book_id: str, page_id: str, session_id: str) -> bool:
    """Point a conversation at the book page it was held on. False when unchanged."""
    session = await store.get_session(session_id)
    if session is None:
        return False
    preferences = session.get("preferences") or {}
    if preferences.get(BOOK_ID) == book_id and preferences.get(BOOK_PAGE_ID) == page_id:
        return False
    # A link, not activity: the conversation keeps its place by last use.
    return await store.update_session_preferences(
        session_id, {BOOK_ID: book_id, BOOK_PAGE_ID: page_id}, touch=False
    )


def page_chat_sessions(book: Any, resolved: Any) -> dict[str, str]:
    """Page id → conversation id, from wherever this reader's mapping lives."""
    if resolved.is_shared:
        return resolved.learning.load_page_chat_sessions(book.id)
    mapping = (book.metadata or {}).get("page_chat_sessions")
    return mapping if isinstance(mapping, dict) else {}


async def adopt_book_chat_sessions(store: Any | None = None) -> int:
    """Tag the conversations the current scope's books already map. Idempotent."""
    from deeptutor.multi_user.book_access import accessible_books
    from deeptutor.services.session import get_session_store

    store = store or get_session_store()
    tagged = 0
    for book, resolved in await asyncio.to_thread(accessible_books):
        for page_id, session_id in page_chat_sessions(book, resolved).items():
            if session_id and await tag_book_chat_session(
                store, book_id=book.id, page_id=str(page_id), session_id=str(session_id)
            ):
                tagged += 1
    return tagged


__all__ = [
    "BOOK_ID",
    "BOOK_PAGE_ID",
    "adopt_book_chat_sessions",
    "page_chat_sessions",
    "tag_book_chat_session",
]
