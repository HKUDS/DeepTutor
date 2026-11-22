"""Revision-fenced book edits: pure previews, explicit apply, and guarded undo.

Records live with the book and inherit its ownership/retention. Only files in
this server-built plan can be written; model proposals never apply themselves.
"""

from __future__ import annotations

import difflib
import json
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page, PageStatus
from deeptutor.book.storage import _read_json, _safe_page_id
from deeptutor.services.file_io import atomic_write_json


class BookEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "add_chapter",
        "rename_chapter",
        "move_chapter",
        "delete_chapter",
        "add_page",
        "rename_page",
        "move_page",
        "delete_page",
        "insert_block",
        "extend_page",
    ]
    chapter_id: str = ""
    page_id: str = ""
    title: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=100000)
    learning_objectives: list[str] = Field(default_factory=list, max_length=30)
    position: int = Field(default=0, ge=0, le=10000)


def _read(storage, book_id):
    book = storage.load_book(book_id)
    spine = storage.load_spine(book_id)
    if book is None or spine is None:
        raise ValueError("Book or spine not found")
    if book.status.value == "compiling":
        raise ValueError("Pause book generation before editing its structure")
    pages = {p.id: p for p in storage.list_pages(book_id)}
    if any(p.status in {PageStatus.PLANNING, PageStatus.GENERATING} for p in pages.values()):
        raise ValueError("Pause book generation before editing its structure")
    return book, spine, pages


def _path(storage, book_id, name):
    # Names originate in our plan, never a model or client-supplied path.
    if name in {"spine.json", "manifest.json"}:
        return storage.book_root(book_id) / name
    if name.startswith("pages/") and name.endswith(".json"):
        return storage.book_root(book_id) / "pages" / (_safe_page_id(name[6:-5]) + ".json")
    raise ValueError("Invalid edit file")


def _record_path(storage, book_id, edit_id):
    return storage.book_root(book_id) / "edits" / (_safe_page_id(edit_id) + ".json")


def _write_files(storage, book_id, values):
    for name, value in values.items():
        path = _path(storage, book_id, name)
        if value is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write_json(path, value)


def recover_edits(storage, book_id):
    # A process interrupted during a multi-file write leaves its rollback
    # journal. Refuse unknown external changes instead of overwriting them.
    for path in (storage.book_root(book_id) / "edits").glob("*.json"):
        record = _read_json(path)
        if not record or record.get("status") not in {"applying", "undoing"}:
            continue
        before, after = record["transaction_before"], record["transaction_after"]
        if any(
            _read_json(_path(storage, book_id, name)) not in (value, after.get(name))
            for name, value in before.items()
        ):
            raise ValueError("Interrupted book edit needs recovery; its files changed externally")
        _write_files(storage, book_id, before)
        record["status"] = record["previous_status"]
        record.pop("transaction_before", None)
        record.pop("transaction_after", None)
        atomic_write_json(path, record)


def preview_edit(storage, book_id, edit: BookEdit, *, source_session_id="", source_turn_id=""):
    recover_edits(storage, book_id)
    book, spine, pages = _read(storage, book_id)
    before = {
        "spine.json": spine.model_dump(mode="json"),
        **{f"pages/{pid}.json": page.model_dump(mode="json") for pid, page in pages.items()},
    }
    chapter = spine.chapter_by_id(edit.chapter_id)
    page = pages.get(edit.page_id)
    if edit.action.endswith("chapter") and edit.action != "add_chapter" and chapter is None:
        raise ValueError("Chapter not found")
    if (
        edit.action
        not in {"add_chapter", "rename_chapter", "move_chapter", "delete_chapter", "add_page"}
        and page is None
    ):
        raise ValueError("Page not found")
    if (chapter and chapter.content_type.value == "overview") or (
        page and page.content_type.value == "overview"
    ):
        raise ValueError("The generated overview cannot be structurally edited")
    if (
        edit.action in {"add_chapter", "rename_chapter", "add_page", "rename_page"}
        and not edit.title.strip()
    ):
        raise ValueError("Title is required")
    if edit.action == "add_chapter":
        chapter = Chapter(title=edit.title.strip(), learning_objectives=edit.learning_objectives)
        spine.chapters.insert(min(edit.position, len(spine.chapters)), chapter)
        page = Page(
            book_id=book_id,
            chapter_id=chapter.id,
            title=chapter.title,
            learning_objectives=edit.learning_objectives,
        )
        pages[page.id] = page
        chapter.page_ids = [page.id]
    elif edit.action == "rename_chapter":
        chapter.title = edit.title.strip()
    elif edit.action == "move_chapter":
        spine.chapters.remove(chapter)
        spine.chapters.insert(min(edit.position, len(spine.chapters)), chapter)
    elif edit.action == "delete_chapter":
        removed = {pid for pid, value in pages.items() if value.chapter_id == chapter.id}
        if any(
            value.parent_page_id in removed and pid not in removed for pid, value in pages.items()
        ):
            raise ValueError("Remove dependent deep-dive pages before deleting this chapter")
        spine.chapters.remove(chapter)
        pages = {pid: value for pid, value in pages.items() if value.chapter_id != chapter.id}
        for other in spine.chapters:
            other.prerequisites = [cid for cid in other.prerequisites if cid != chapter.id]
        spine.concept_graph.nodes = [
            n for n in spine.concept_graph.nodes if n.chapter_id != chapter.id
        ]
        nodes = {n.id for n in spine.concept_graph.nodes}
        spine.concept_graph.edges = [
            e for e in spine.concept_graph.edges if e.src in nodes and e.dst in nodes
        ]
    elif edit.action == "add_page":
        if chapter is None:
            raise ValueError("Chapter not found")
        page = Page(
            book_id=book_id,
            chapter_id=chapter.id,
            title=edit.title.strip(),
            learning_objectives=edit.learning_objectives,
            content_type=chapter.content_type,
            section=True,
        )
        pages[page.id] = page
        chapter.page_ids.insert(min(edit.position, len(chapter.page_ids)), page.id)
        if edit.body:
            page.blocks = [
                Block(type=BlockType.TEXT, status=BlockStatus.READY, payload={"body": edit.body})
            ]
            page.status = PageStatus.READY
    elif edit.action == "rename_page":
        page.title = edit.title.strip()
        page.__pydantic_extra__ = {**(page.__pydantic_extra__ or {}), "section": True}
    elif edit.action in {"move_page", "delete_page"}:
        parent = spine.chapter_by_id(page.chapter_id)
        if parent is None or page.id not in parent.page_ids:
            raise ValueError("Only sections in the book outline can be moved or deleted")
        parent.page_ids.remove(page.id)
        if edit.action == "move_page":
            destination = chapter or parent
            destination.page_ids.insert(min(edit.position, len(destination.page_ids)), page.id)
            page.chapter_id = destination.id
        else:
            # Deep-dive children retain evidence; removing their parent would orphan them.
            if any(p.parent_page_id == page.id for p in pages.values()):
                raise ValueError(
                    "Remove the dependent deep-dive pages before deleting this section"
                )
            pages.pop(page.id)
    elif edit.action in {"insert_block", "extend_page"}:
        if not edit.body.strip():
            raise ValueError("Content is required")
        block = Block(
            type=BlockType.TEXT,
            status=BlockStatus.READY,
            title=edit.title.strip(),
            payload={"body": edit.body},
            metadata={"source_session_id": source_session_id, "source_turn_id": source_turn_id},
        )
        position = (
            len(page.blocks)
            if edit.action == "extend_page"
            else min(edit.position, len(page.blocks))
        )
        page.blocks.insert(position, block)
        page.status = PageStatus.READY
    for index, item in enumerate(spine.chapters):
        item.order = index
        for pid in item.page_ids:
            if pid in pages:
                pages[pid].order = index
    after = {
        "spine.json": spine.model_dump(mode="json"),
        **{f"pages/{pid}.json": value.model_dump(mode="json") for pid, value in pages.items()},
    }
    changed = [name for name in before.keys() | after.keys() if before.get(name) != after.get(name)]
    if not changed:
        raise ValueError("The proposed edit does not change the book")
    if len(list((storage.book_root(book_id) / "edits").glob("*.json"))) >= 1000:
        raise ValueError("Book edit history limit reached; export an archive before further edits")
    record = dict(
        id="edit_" + uuid4().hex,
        book_id=book_id,
        page_id=edit.page_id,
        expected_revision=book.revision,
        status="proposed",
        created_at=time.time(),
        source_session_id=source_session_id,
        source_turn_id=source_turn_id,
        edit=edit.model_dump(),
        before={n: before.get(n) for n in changed},
        after={n: after.get(n) for n in changed},
    )

    def prose(values, page_map):
        lines = []
        if values.get("spine.json"):
            lines.append("# Outline")
            for number, chapter in enumerate(values["spine.json"]["chapters"], 1):
                lines.append(f"{number}. {chapter['title']}")
                for pid in chapter["page_ids"]:
                    item = page_map.get(pid)
                    lines.append("   - " + (item.title if item else pid))
        for name, value in sorted(values.items()):
            if name.startswith("pages/") and value:
                lines.extend(["", "# " + value["title"]])
                for block in value["blocks"]:
                    lines.extend(
                        [
                            block.get("title") or "",
                            str(
                                block.get("payload", {}).get("body")
                                or json.dumps(block.get("payload") or {}, ensure_ascii=False)
                            ),
                        ]
                    )
        return lines

    old_pages = {
        key: Page.model_validate(value)
        for name, value in before.items()
        if name.startswith("pages/")
        for key in [name[6:-5]]
    }
    record["diff"] = "\n".join(
        difflib.unified_diff(
            prose(record["before"], old_pages),
            prose(record["after"], pages),
            fromfile="Current book",
            tofile="Proposed book",
            lineterm="",
        )
    )
    atomic_write_json(_record_path(storage, book_id, record["id"]), record)
    return public_edit(record)


def public_edit(record):
    return {
        key: record.get(key)
        for key in (
            "id",
            "book_id",
            "page_id",
            "expected_revision",
            "applied_revision",
            "status",
            "created_at",
            "source_session_id",
            "source_turn_id",
            "edit",
            "diff",
        )
    }


def list_edits(storage, book_id, page_id=None):
    recover_edits(storage, book_id)
    records = [_read_json(path) for path in (storage.book_root(book_id) / "edits").glob("*.json")]
    return [
        public_edit(r)
        for r in sorted((r for r in records if r), key=lambda r: r["created_at"], reverse=True)
        if page_id is None or r.get("page_id") == page_id
    ][:50]


def apply_edit(storage, book_id, edit_id, expected_revision, *, undo=False):
    recover_edits(storage, book_id)
    book, spine, pages = _read(storage, book_id)
    path = _record_path(storage, book_id, edit_id)
    record = _read_json(path)
    if not record or record.get("book_id") != book_id:
        raise ValueError("Edit not found")
    # Repeat delivery is a receipt, never a repeated mutation.
    completed = "undone" if undo else "applied"
    if record["status"] == completed:
        return public_edit(record)
    wanted = "applied" if undo else "proposed"
    revision = record.get("applied_revision") if undo else record["expected_revision"]
    if record["status"] != wanted or expected_revision != revision or book.revision != revision:
        raise ValueError("Book revision changed; review a new proposal before applying or undoing")
    before, after = (
        (record["after"], record["before"]) if undo else (record["before"], record["after"])
    )
    if any(_read_json(_path(storage, book_id, name)) != value for name, value in before.items()):
        raise ValueError("Book content changed since the preview; review a new proposal")
    manifest_before = book.model_dump(mode="json")
    book.revision += 1
    book.updated_at = time.time()
    resulting_spine = after.get("spine.json") or spine.model_dump(mode="json")
    book.chapter_count = len(resulting_spine["chapters"])
    book.page_count = (
        len(pages)
        + sum(1 for n in after if n.startswith("pages/") and before[n] is None)
        - sum(1 for n in after if n.startswith("pages/") and after[n] is None)
    )
    transaction_before = {**before, "manifest.json": manifest_before}
    transaction_after = {**after, "manifest.json": book.model_dump(mode="json")}
    record.update(
        previous_status=record["status"],
        status="undoing" if undo else "applying",
        transaction_before=transaction_before,
        transaction_after=transaction_after,
    )
    atomic_write_json(path, record)
    try:
        _write_files(storage, book_id, transaction_after)
    except Exception:
        recover_edits(storage, book_id)
        raise
    record.update(
        status=completed,
        **({"undo_revision": book.revision} if undo else {"applied_revision": book.revision}),
    )
    record.pop("transaction_before", None)
    record.pop("transaction_after", None)
    atomic_write_json(path, record)
    return public_edit(record)
