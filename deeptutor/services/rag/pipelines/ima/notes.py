"""Client for Tencent IMA's notes OpenAPI (``/openapi/note/v1``).

Notes are the other half of a user's IMA account: a knowledge base holds files
and web pages, while notes are the text the user writes, and a note can also be
linked *into* a knowledge base (media type 11) — which is why retrieval already
needed this module to read a matched note's body.

Exposed here: searching notes (with IMA's own sort orders, the only place in the
API where "my most recent items" is answerable, since notes carry create/modify
timestamps and knowledge items do not), browsing notebooks, reading a note's
plain text, and the two additive writes — create a note, append to a note.
Nothing deletes or overwrites.

Field-name compatibility
------------------------
The reference names the note identifier ``doc_id`` while other IMA surfaces have
used ``note_id`` for the same value. Requests send both spellings: unknown body
fields are ignored by the API, so sending both is strictly safer than betting on
one and having every call 404.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import ImaConfig
from .models import ImaNote, ImaNotebook, ImaPageCursor, parse_note, parse_notebook
from .transport import DEFAULT_TIMEOUT, NOTE_PREFIX, ImaTransport

# ``content_format`` / ``target_content_format`` enum values IMA documents.
MARKDOWN_FORMAT = 1
PLAIN_TEXT_FORMAT = 0

# ``sort_type`` values. Recency is the default because "my latest notes" is the
# question this module exists to answer.
SORT_BY_UPDATED = 0
SORT_BY_CREATED = 1
SORT_BY_TITLE = 2
SORT_BY_SIZE = 3
SORT_TYPES = frozenset({SORT_BY_UPDATED, SORT_BY_CREATED, SORT_BY_TITLE, SORT_BY_SIZE})

# ``search_type`` values: match titles only, or full text.
SEARCH_BY_TITLE = 0
SEARCH_BY_CONTENT = 1

# The notes list endpoints are cursor-paginated; the notebook listing starts at
# the literal cursor "0" rather than an empty string.
NOTEBOOK_FIRST_CURSOR = "0"

MAX_NOTE_PAGE_LIMIT = 50


class ImaNotesClient:
    """Stateless wrapper over the IMA notes OpenAPI."""

    def __init__(
        self,
        config: ImaConfig,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._wire = ImaTransport(config, timeout=timeout, transport=transport)

    async def _post(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._wire.post(method, body, prefix=NOTE_PREFIX)

    # ----- reading --------------------------------------------------------

    async def search_notes(
        self,
        query: str = "",
        *,
        by_content: bool = False,
        sort_type: int = SORT_BY_UPDATED,
        limit: int = 20,
        start: int = 0,
    ) -> tuple[list[ImaNote], bool]:
        """Search notes, newest-updated first by default.

        An empty *query* lists notes in ``sort_type`` order, which is how "my
        latest notes" is answered. Returns the notes plus whether IMA reported
        the end of the result set. Pagination is a half-open ``[start, end)``
        window rather than a cursor.
        """
        size = _note_limit(limit)
        text = str(query or "").strip()
        search_type = SEARCH_BY_CONTENT if by_content else SEARCH_BY_TITLE
        data = await self._post(
            "search_note_book",
            {
                "search_type": search_type,
                "sort_type": sort_type if sort_type in SORT_TYPES else SORT_BY_UPDATED,
                "query_info": ({"content": text} if by_content else {"title": text}),
                "start": max(0, int(start)),
                "end": max(0, int(start)) + size,
            },
        )
        notes = _notes_from(data, ("docs", "note_book_list"))
        return notes[:size], bool(data.get("is_end"))

    async def list_notebooks(
        self,
        *,
        cursor: str = NOTEBOOK_FIRST_CURSOR,
        limit: int = MAX_NOTE_PAGE_LIMIT,
    ) -> tuple[list[ImaNotebook], ImaPageCursor]:
        """Return one page of the user's notebooks."""
        data = await self._post(
            "list_note_folder_by_cursor",
            {"cursor": str(cursor or NOTEBOOK_FIRST_CURSOR), "limit": _note_limit(limit)},
        )
        notebooks: list[ImaNotebook] = []
        raw_list = data.get("note_book_folders")
        if isinstance(raw_list, list):
            for raw in raw_list:
                notebook = parse_notebook(raw)
                if notebook is not None:
                    notebooks.append(notebook)
        return notebooks, _cursor_of(data)

    async def list_notes(
        self,
        *,
        folder_id: str = "",
        cursor: str = "",
        limit: int = MAX_NOTE_PAGE_LIMIT,
    ) -> tuple[list[ImaNote], ImaPageCursor]:
        """Return one page of notes inside *folder_id* (root when omitted)."""
        body: dict[str, Any] = {"cursor": str(cursor or ""), "limit": _note_limit(limit)}
        folder = str(folder_id or "").strip()
        if folder:
            body["folder_id"] = folder
        data = await self._post("list_note_by_folder_id", body)
        return _notes_from(data, ("note_book_list", "docs")), _cursor_of(data)

    async def get_note_content(self, note_id: str, *, as_markdown: bool = False) -> str:
        """Return one note's text, or ``""`` when it has none.

        Plain text is IMA's recommended (and only reliably supported) target
        format; *as_markdown* is accepted for callers that want to try the
        Markdown variant.
        """
        identifier = str(note_id or "").strip()
        if not identifier:
            return ""
        data = await self._post(
            "get_doc_content",
            {
                "doc_id": identifier,
                "note_id": identifier,
                "target_content_format": MARKDOWN_FORMAT if as_markdown else PLAIN_TEXT_FORMAT,
            },
        )
        return str(data.get("content") or "").strip()

    # ----- additive writes ------------------------------------------------

    async def create_note(self, content: str, *, folder_id: str = "") -> str:
        """Create a note from Markdown and return its id.

        IMA takes the title from the Markdown body's leading heading, so callers
        that want a specific title should include one.
        """
        body_text = str(content or "").strip()
        if not body_text:
            raise ValueError("Note content is required.")
        body: dict[str, Any] = {"content_format": MARKDOWN_FORMAT, "content": body_text}
        folder = str(folder_id or "").strip()
        if folder:
            body["folder_id"] = folder
        data = await self._post("import_doc", body)
        return str(data.get("doc_id") or data.get("note_id") or "").strip()

    async def append_note(self, note_id: str, content: str) -> str:
        """Append Markdown to an existing note and return its id.

        Appending mutates a note the user owns and cannot be undone, so callers
        must have an explicitly identified target — never a guessed one.
        """
        identifier = str(note_id or "").strip()
        if not identifier:
            raise ValueError("A target note id is required.")
        body_text = str(content or "").strip()
        if not body_text:
            raise ValueError("Content to append is required.")
        data = await self._post(
            "append_doc",
            {
                "doc_id": identifier,
                "note_id": identifier,
                "content_format": MARKDOWN_FORMAT,
                "content": body_text,
            },
        )
        return str(data.get("doc_id") or data.get("note_id") or identifier).strip()


def _notes_from(data: dict[str, Any], keys: tuple[str, ...]) -> list[ImaNote]:
    for key in keys:
        raw_list = data.get(key)
        if not isinstance(raw_list, list):
            continue
        notes = [note for note in (parse_note(raw) for raw in raw_list) if note is not None]
        if notes or raw_list:
            return notes
    return []


def _cursor_of(data: dict[str, Any]) -> ImaPageCursor:
    return ImaPageCursor(
        next_cursor=str(data.get("next_cursor") or ""),
        is_end=bool(data.get("is_end")),
    )


def _note_limit(limit: Any) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return MAX_NOTE_PAGE_LIMIT
    return max(1, min(value, MAX_NOTE_PAGE_LIMIT))


__all__ = [
    "MARKDOWN_FORMAT",
    "MAX_NOTE_PAGE_LIMIT",
    "NOTEBOOK_FIRST_CURSOR",
    "PLAIN_TEXT_FORMAT",
    "SEARCH_BY_CONTENT",
    "SEARCH_BY_TITLE",
    "SORT_BY_CREATED",
    "SORT_BY_SIZE",
    "SORT_BY_TITLE",
    "SORT_BY_UPDATED",
    "SORT_TYPES",
    "ImaNotesClient",
]
