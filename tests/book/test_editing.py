"""Reader-authored content: in-place edits, notes, and remediation.

Covers the promise the UI used to make and could not keep — the note block
invited you to "start writing" with nowhere to write — plus the rule that
makes editing safe to offer at all: a forced regenerate must not silently
delete what the reader wrote.
"""

from __future__ import annotations

import pytest

from deeptutor.book.engine import BookEngine
from deeptutor.book.models import Block, BlockStatus, BlockType, Page, PageStatus


class _Storage:
    """In-memory stand-in holding exactly one page."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.logs: list[str] = []

    def load_page(self, book_id: str, page_id: str) -> Page | None:
        return self.page if page_id == self.page.id else None

    def save_page(self, page: Page) -> None:
        self.page = page

    def append_log(self, book_id: str, message: str, op: str = "info") -> None:
        self.logs.append(op)


def _engine(page: Page) -> BookEngine:
    engine = BookEngine.__new__(BookEngine)
    engine.storage = _Storage(page)
    from deeptutor.book.compiler import BookCompiler, CompilerOptions

    engine.compiler = BookCompiler.__new__(BookCompiler)
    engine.compiler.options = CompilerOptions()
    return engine


# ── Editing ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_editing_a_note_stores_the_body() -> None:
    note = Block(type=BlockType.USER_NOTE, status=BlockStatus.READY, payload={"body": ""})
    page = Page(id="pg_1", book_id="bk", blocks=[note])
    engine = _engine(page)

    updated = await engine.update_block(
        book_id="bk", page_id="pg_1", block_id=note.id, body="my annotation"
    )

    assert updated is not None
    assert updated.payload["body"] == "my annotation"
    assert updated.metadata["edited_by_user"] is True


@pytest.mark.asyncio
async def test_editing_a_text_block_writes_the_key_it_already_uses() -> None:
    # Overview blocks store prose under `content`; generated ones use `body`.
    block = Block(type=BlockType.TEXT, status=BlockStatus.READY, payload={"content": "original"})
    page = Page(id="pg_1", book_id="bk", blocks=[block])
    engine = _engine(page)

    updated = await engine.update_block(
        book_id="bk", page_id="pg_1", block_id=block.id, body="corrected"
    )

    assert updated is not None
    assert updated.payload["content"] == "corrected"
    assert "body" not in updated.payload, "an edit must land where the renderer reads"


@pytest.mark.asyncio
async def test_structured_blocks_are_not_editable_as_plain_text() -> None:
    quiz = Block(type=BlockType.QUIZ, status=BlockStatus.READY, payload={"questions": []})
    page = Page(id="pg_1", book_id="bk", blocks=[quiz])
    engine = _engine(page)

    assert (
        await engine.update_block(book_id="bk", page_id="pg_1", block_id=quiz.id, body="nope")
        is None
    )


def test_a_forced_regenerate_keeps_hand_edited_prose() -> None:
    edited = Block(
        type=BlockType.TEXT,
        status=BlockStatus.READY,
        payload={"body": "I fixed this sentence"},
        metadata={"edited_by_user": True},
    )
    generated = Block(type=BlockType.TEXT, status=BlockStatus.READY, payload={"body": "untouched"})
    page = Page(status=PageStatus.READY, blocks=[edited, generated])

    BookEngine._reset_page_for_force_compile(page)

    assert edited.payload == {"body": "I fixed this sentence"}
    assert edited.status == BlockStatus.READY
    assert generated.payload == {}
    assert generated.status == BlockStatus.PENDING


# ── Remediation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_supplement_is_idempotent_per_topic() -> None:
    """Three generated blocks a click is too expensive to duplicate."""
    existing = Block(
        type=BlockType.TEXT,
        status=BlockStatus.READY,
        params={"role": "remediation", "topic": "gradients"},
    )
    page = Page(id="pg_1", book_id="bk", blocks=[existing])
    engine = _engine(page)

    inserted: list[str] = []

    async def _fail_insert(**kwargs):
        inserted.append(kwargs["block_type"].value)

    engine.insert_block = _fail_insert

    result = await engine.supplement_for_weakness(
        book_id="bk", page_id="pg_1", topic="  gradients  "
    )

    assert result is existing
    assert inserted == [], "asking twice must not stack a second remediation"
