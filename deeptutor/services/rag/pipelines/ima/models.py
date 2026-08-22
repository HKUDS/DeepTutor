"""Typed views over IMA's wire payloads, and the parsers that produce them.

Every IMA list response is a bag of loosely-typed dicts whose field names differ
between the documented reference and live responses, and whose entries mix
*documents* with *folders* — ``get_knowledge_list`` returns both by design, and
``search_knowledge`` also matches folder names. Parsing that in the client would
scatter the same defensive ``str(raw.get(...) or "")`` over every method and let
a folder leak into retrieval results as a document with no content (which is how
a folder used to end up cited as a source).

So the wire shapes are decoded exactly once, here:

* :func:`parse_knowledge_page` splits a page into documents and folders,
  discarding entries that identify as neither;
* the notes payloads are deeply nested (``docs[].doc.basic_info.docid``), which
  :func:`parse_note` flattens into something a tool can render directly.

These types carry no behaviour and no I/O, so the client, the inventory reader,
the retrieval pipeline and the capability's tools can all share them without a
cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ImaDocument:
    """One document in a knowledge base (a file, a web page, or a linked note)."""

    media_id: str
    title: str
    parent_folder_id: str = ""
    highlight: str = ""
    """Matched snippet — search results only; empty for a plain listing."""


@dataclass(frozen=True, slots=True)
class ImaFolder:
    """One folder in a knowledge base's tree."""

    folder_id: str
    name: str
    file_number: int = 0
    folder_number: int = 0
    parent_folder_id: str = ""


@dataclass(frozen=True, slots=True)
class ImaKnowledgePage:
    """One cursor page of a knowledge base's contents."""

    documents: tuple[ImaDocument, ...] = ()
    folders: tuple[ImaFolder, ...] = ()
    path: tuple[str, ...] = ()
    """Breadcrumb folder names for the listed location, outermost first."""

    next_cursor: str = ""
    is_end: bool = False


@dataclass(frozen=True, slots=True)
class ImaKnowledgeBase:
    """One knowledge base available to a credential pair."""

    id: str
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ImaNote:
    """One note, flattened from the notes API's nested payload."""

    note_id: str
    title: str
    summary: str = ""
    folder_name: str = ""
    created_at: int = 0
    """Unix milliseconds, or ``0`` when absent."""

    updated_at: int = 0


@dataclass(frozen=True, slots=True)
class ImaNotebook:
    """One notebook (a notes folder)."""

    folder_id: str
    name: str
    note_number: int = 0


@dataclass(frozen=True, slots=True)
class ImaImportedUrl:
    """The per-URL verdict ``import_urls`` reports."""

    url: str
    ok: bool
    media_id: str = ""
    code: int = 0


@dataclass(frozen=True, slots=True)
class ImaPageCursor:
    """Cursor state shared by every paginated notes/knowledge response."""

    next_cursor: str = ""
    is_end: bool = False


# ---------------------------------------------------------------------------
# Knowledge base parsing
# ---------------------------------------------------------------------------

# ``get_knowledge_list`` names the document array ``knowledge_list`` while
# ``search_knowledge`` names it ``info_list``; folders have been observed under
# both ``folder_list`` and ``folders``. Accepting each spelling keeps one parser
# for both calls.
_DOCUMENT_KEYS: tuple[str, ...] = ("knowledge_list", "info_list")
_FOLDER_KEYS: tuple[str, ...] = ("folder_list", "folders")


def parse_knowledge_page(data: Mapping[str, Any]) -> ImaKnowledgePage:
    """Decode one page of ``get_knowledge_list`` / ``search_knowledge``."""
    documents: list[ImaDocument] = []
    folders: list[ImaFolder] = []
    seen_documents: set[str] = set()
    seen_folders: set[str] = set()

    for raw in _entries(data, _DOCUMENT_KEYS):
        # A folder can appear inside the document array (search matches folder
        # names, and a listing mixes both), identified by carrying a folder id
        # and no media id. Route it to the folder list instead of inventing a
        # content-less document.
        folder = _folder_from(raw)
        if folder is not None and not _text(raw, "media_id"):
            if folder.folder_id not in seen_folders:
                seen_folders.add(folder.folder_id)
                folders.append(folder)
            continue
        document = _document_from(raw)
        if document is not None and document.media_id not in seen_documents:
            seen_documents.add(document.media_id)
            documents.append(document)

    for raw in _entries(data, _FOLDER_KEYS):
        folder = _folder_from(raw)
        if folder is not None and folder.folder_id not in seen_folders:
            seen_folders.add(folder.folder_id)
            folders.append(folder)

    return ImaKnowledgePage(
        documents=tuple(documents),
        folders=tuple(folders),
        path=_breadcrumb(data.get("current_path")),
        next_cursor=str(data.get("next_cursor") or ""),
        is_end=bool(data.get("is_end")),
    )


def parse_knowledge_bases(data: Mapping[str, Any]) -> tuple[list[ImaKnowledgeBase], ImaPageCursor]:
    """Decode one page of ``search_knowledge_base``.

    The reference names the fields ``id`` / ``name``; live responses have also
    used ``kb_id`` / ``kb_name``. Both are accepted.
    """
    bases: list[ImaKnowledgeBase] = []
    seen: set[str] = set()
    for raw in _entries(data, ("info_list",)):
        kb_id = _text(raw, "id") or _text(raw, "kb_id")
        name = _text(raw, "name") or _text(raw, "kb_name")
        if not kb_id or not name or kb_id in seen:
            continue
        seen.add(kb_id)
        bases.append(ImaKnowledgeBase(id=kb_id, name=name))
    cursor = ImaPageCursor(
        next_cursor=str(data.get("next_cursor") or ""),
        is_end=bool(data.get("is_end")),
    )
    return bases, cursor


def parse_imported_urls(data: Mapping[str, Any]) -> list[ImaImportedUrl]:
    """Decode ``import_urls``' per-URL results."""
    results: list[ImaImportedUrl] = []
    for raw in _entries(data, ("url_data_list", "info_list", "data_list")):
        url = _text(raw, "url")
        if not url:
            continue
        code = _int(raw.get("ret_code"))
        results.append(
            ImaImportedUrl(
                url=url,
                ok=code == 0,
                media_id=_text(raw, "media_id"),
                code=code,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Notes parsing
# ---------------------------------------------------------------------------


def parse_note(raw: Any) -> ImaNote | None:
    """Flatten one note entry from any of the notes list/search payloads.

    Handles the three nestings the notes API uses for the same object:
    ``{"doc": {"basic_info": {...}}}`` (search), ``{"basic_info": {...}}``
    (listing) and a bare basic-info dict.
    """
    basic = _basic_info(raw, outer_keys=("doc",))
    if basic is None:
        return None
    note_id = _text(basic, "docid") or _text(basic, "doc_id")
    if not note_id:
        return None
    if _int(basic.get("status")) == 1:  # deleted
        return None
    return ImaNote(
        note_id=note_id,
        title=_text(basic, "title") or "(untitled)",
        summary=_text(basic, "summary"),
        folder_name=_text(basic, "folder_name"),
        created_at=_int(basic.get("create_time")),
        updated_at=_int(basic.get("modify_time")),
    )


def parse_notebook(raw: Any) -> ImaNotebook | None:
    """Flatten one notebook entry from ``list_note_folder_by_cursor``."""
    basic = _basic_info(raw, outer_keys=("folder",))
    if basic is None:
        return None
    folder_id = _text(basic, "folder_id")
    if not folder_id or _int(basic.get("status")) == 1:
        return None
    return ImaNotebook(
        folder_id=folder_id,
        name=_text(basic, "name") or "(unnamed)",
        note_number=_int(basic.get("note_number")),
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entries(data: Mapping[str, Any], keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _document_from(raw: Mapping[str, Any]) -> ImaDocument | None:
    media_id = _text(raw, "media_id")
    title = _text(raw, "title")
    if not media_id and not title:
        return None
    return ImaDocument(
        media_id=media_id,
        title=title or media_id,
        parent_folder_id=_text(raw, "parent_folder_id"),
        highlight=_text(raw, "highlight_content"),
    )


def _folder_from(raw: Mapping[str, Any]) -> ImaFolder | None:
    folder_id = _text(raw, "folder_id")
    if not folder_id:
        return None
    return ImaFolder(
        folder_id=folder_id,
        name=_text(raw, "name") or _text(raw, "title") or folder_id,
        file_number=_int(raw.get("file_number")),
        folder_number=_int(raw.get("folder_number")),
        parent_folder_id=_text(raw, "parent_folder_id"),
    )


def _breadcrumb(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    names = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        name = _text(entry, "name")
        if name:
            names.append(name)
    return tuple(names)


def _basic_info(raw: Any, *, outer_keys: tuple[str, ...]) -> Mapping[str, Any] | None:
    """Peel the notes API's wrapper layers down to the basic-info dict."""
    if not isinstance(raw, Mapping):
        return None
    node: Mapping[str, Any] = raw
    for key in outer_keys:
        inner = node.get(key)
        if isinstance(inner, Mapping):
            node = inner
    inner = node.get("basic_info")
    if isinstance(inner, Mapping):
        node = inner
    return node


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return str(value).strip() if value is not None else ""


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "ImaDocument",
    "ImaFolder",
    "ImaImportedUrl",
    "ImaKnowledgeBase",
    "ImaKnowledgePage",
    "ImaNote",
    "ImaNotebook",
    "ImaPageCursor",
    "parse_imported_urls",
    "parse_knowledge_bases",
    "parse_knowledge_page",
    "parse_note",
    "parse_notebook",
]
