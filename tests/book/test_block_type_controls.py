from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.api.routers import book as book_router
from deeptutor.book.agents import page_planner
from deeptutor.book.agents.page_planner import SectionArchitect
from deeptutor.book.compiler import BookCompiler
from deeptutor.book.models import BlockType, Book, Chapter, ContentType, Page


def _chapter() -> Chapter:
    return Chapter(
        id="ch_blocks",
        title="Block controls",
        summary="A chapter used to exercise the architect.",
        content_type=ContentType.THEORY,
    )


def _types(blocks) -> list[BlockType]:
    return [block.type for block in blocks]


def _install_llm(monkeypatch: pytest.MonkeyPatch, blocks: list[dict[str, object]]) -> None:
    async def fake_llm_text(**_kwargs) -> str:
        return json.dumps({"blocks": blocks})

    monkeypatch.setattr(page_planner, "llm_text", fake_llm_text)


def test_allowed_none_leaves_static_plan_unchanged() -> None:
    architect = SectionArchitect(phase=2, llm_enabled=False)

    original = architect.plan_blocks(_chapter())
    explicit_none = architect.plan_blocks(_chapter(), allowed=None)

    volatile = {"id", "created_at", "updated_at"}
    assert [block.model_dump(exclude=volatile) for block in explicit_none] == [
        block.model_dump(exclude=volatile) for block in original
    ]


@pytest.mark.asyncio
async def test_allow_list_filters_static_and_llm_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = {BlockType.QUIZ}
    static = SectionArchitect(phase=2, llm_enabled=False).plan_blocks(_chapter(), allowed=allowed)
    assert set(_types(static)) == {BlockType.SECTION, BlockType.QUIZ}

    _install_llm(
        monkeypatch,
        [
            {"type": "section", "params": {"role": "opening"}},
            {"type": "figure"},
            {"type": "quiz"},
            {"type": "code"},
        ],
    )
    llm = await SectionArchitect(phase=2).plan_blocks_async(_chapter(), allowed=allowed)

    assert _types(llm) == [BlockType.SECTION, BlockType.QUIZ]


@pytest.mark.asyncio
async def test_section_survives_explicit_exclusion(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_llm(
        monkeypatch,
        [
            {"type": "section", "params": {"role": "opening"}},
            {"type": "quiz"},
        ],
    )

    blocks = await SectionArchitect(phase=2).plan_blocks_async(_chapter(), allowed=set())

    assert _types(blocks) == [BlockType.SECTION]
    assert blocks[0].params["role"] == "opening"


@pytest.mark.asyncio
async def test_filtering_every_llm_block_falls_back_to_one_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_llm(monkeypatch, [{"type": "quiz"}, {"type": "animation"}])

    blocks = await SectionArchitect(phase=2).plan_blocks_async(_chapter(), allowed=set())

    assert _types(blocks) == [BlockType.SECTION]


class _Storage:
    def __init__(self, book: Book) -> None:
        self.book = book
        self.saved: list[Book] = []
        self.saved_pages: list[Page] = []

    def load_book(self, book_id: str) -> Book | None:
        return self.book if book_id == self.book.id else None

    def save_book(self, book: Book) -> None:
        self.book = book.model_copy(deep=True)
        self.saved.append(self.book)

    def save_page(self, page: Page) -> None:
        self.saved_pages.append(page)


class _RouterEngine:
    def __init__(self, storage: _Storage) -> None:
        self.storage = storage

    def load_book(self, book_id: str) -> Book | None:
        return self.storage.load_book(book_id)

    async def confirm_spine(self, **_kwargs) -> list[Page]:
        assert self.storage.book.metadata["block_types"] == ["section", "quiz"]
        return []

    async def rebuild_book(self, **_kwargs) -> list[Page]:
        assert "block_types" not in self.storage.book.metadata
        return []


@pytest.mark.asyncio
async def test_router_normalizes_block_types_and_explicit_empty_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _Storage(Book(id="bk_blocks"))
    engine = _RouterEngine(storage)
    resolved = SimpleNamespace(engine=engine)
    monkeypatch.setattr(book_router, "_resolve_book_or_404", lambda *_args, **_kwargs: resolved)
    monkeypatch.setattr(book_router, "_claim_content_mutation", lambda *_args, **_kwargs: 2)

    await book_router.confirm_spine(
        book_router.ConfirmSpineRequest(
            book_id="bk_blocks",
            block_types=["QUIZ", "nonsense", "quiz"],
        )
    )

    assert storage.book.metadata["block_types"] == ["section", "quiz"]

    await book_router.rebuild_book(
        book_router.RebuildBookRequest(book_id="bk_blocks", block_types=[])
    )

    assert "block_types" not in storage.book.metadata


@pytest.mark.asyncio
async def test_block_type_catalog_matches_the_architect() -> None:
    response = await book_router.block_types()
    by_value = {entry["value"]: entry["planner_default"] for entry in response["block_types"]}

    assert set(by_value) == {block_type.value for block_type in page_planner.PLANNABLE_BLOCK_TYPES}
    assert by_value[BlockType.TEXT.value] is False
    assert by_value[BlockType.QUIZ.value] is True


class _Architect:
    def __init__(self) -> None:
        self.allowed: set[BlockType] | None = None

    async def plan_blocks_async(self, _chapter: Chapter, **kwargs):
        self.allowed = kwargs["allowed"]
        return []


class _Stream:
    async def book_event(self, *_args, **_kwargs) -> None:
        return None


@pytest.mark.asyncio
async def test_compiler_passes_defensively_parsed_block_types() -> None:
    storage = _Storage(Book(id="bk_blocks", metadata={"block_types": ["QUIZ", "unknown", 7]}))
    compiler = BookCompiler.__new__(BookCompiler)
    compiler.storage = storage
    compiler.architect = _Architect()

    await compiler._plan_if_needed(
        "bk_blocks",
        _chapter(),
        Page(id="pg_blocks", book_id="bk_blocks"),
        _Stream(),
    )

    assert compiler.architect.allowed == {BlockType.QUIZ}
