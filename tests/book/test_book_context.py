from __future__ import annotations

from deeptutor.book.context import build_book_context, normalize_book_references
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    Chapter,
    Page,
    PageStatus,
    Spine,
)


class FakeBookStorage:
    def __init__(self) -> None:
        self.book = Book(
            id="book-1",
            title="Fourier Notes",
            description="A compact guide",
            language="en",
        )
        self.spine = Spine(
            book_id="book-1",
            chapters=[
                Chapter(
                    id="ch-1",
                    title="Signals",
                    summary="Signals are decomposed into bases.",
                    learning_objectives=["Define a signal", "Explain basis functions"],
                )
            ],
            exploration_summary="The source material emphasizes intuition.",
        )
        self.page = Page(
            id="page-1",
            book_id="book-1",
            chapter_id="ch-1",
            title="Signal Basics",
            learning_objectives=["Understand time and frequency domains"],
            status=PageStatus.READY,
            blocks=[
                Block(
                    type=BlockType.TEXT,
                    status=BlockStatus.READY,
                    title="Intro",
                    payload={
                        "body": "A signal maps time to values. <think>hidden reasoning</think>",
                    },
                ),
                Block(
                    type=BlockType.SECTION,
                    status=BlockStatus.READY,
                    title="Core idea",
                    payload={
                        "intro": "We compare signals with reusable patterns.",
                        "subsections": [
                            {
                                "heading": "Basis",
                                "body": "A basis lets us rebuild complex signals.",
                            }
                        ],
                        "key_takeaway": "A coefficient measures alignment.",
                    },
                ),
                Block(
                    type=BlockType.CODE,
                    status=BlockStatus.READY,
                    title="Demo",
                    payload={
                        "language": "python",
                        "explanation": "Sample a sine wave.",
                        "code": "print('sample')\n" * 200,
                    },
                ),
                Block(
                    type=BlockType.INTERACTIVE,
                    status=BlockStatus.READY,
                    title="Widget",
                    payload={
                        "description": "Drag frequency to see phase changes.",
                        "code": {"content": "<html>" + ("x" * 5000) + "</html>"},
                    },
                ),
                Block(
                    type=BlockType.QUIZ,
                    status=BlockStatus.ERROR,
                    title="Check",
                    error="provider timeout",
                ),
            ],
        )

    def load_book(self, book_id: str) -> Book | None:
        return self.book if book_id == "book-1" else None

    def load_spine(self, book_id: str) -> Spine | None:
        return self.spine if book_id == "book-1" else None

    def load_page(self, book_id: str, page_id: str) -> Page | None:
        return self.page if book_id == "book-1" and page_id == "page-1" else None


def test_normalize_book_references_merges_and_filters() -> None:
    refs = normalize_book_references(
        [
            {"book_id": "book-1", "page_ids": ["page-1", "page-1", "page-2"]},
            {"book_id": "", "page_ids": ["x"]},
            {"book_id": "book-1", "page_ids": ["page-3"]},
            {"book_id": "book-2", "page_ids": "bad"},
        ]
    )

    assert [ref.model_dump() for ref in refs] == [
        {"book_id": "book-1", "page_ids": ["page-1", "page-2", "page-3"]}
    ]


def test_build_book_context_serializes_readable_page_content() -> None:
    result = build_book_context(
        [{"book_id": "book-1", "page_ids": ["page-1"]}],
        storage=FakeBookStorage(),  # type: ignore[arg-type]
        max_chars=8000,
        block_char_limit=1500,
    )

    assert result.references == [{"book_id": "book-1", "page_ids": ["page-1"]}]
    assert result.warnings == []
    assert "# Book: Fourier Notes" in result.text
    assert "Chapter: Signals" in result.text
    assert "A signal maps time to values." in result.text
    assert "hidden reasoning" not in result.text
    assert "A basis lets us rebuild complex signals." in result.text
    assert "Code (python):" in result.text
    assert "...[truncated]" in result.text
    assert "Drag frequency to see phase changes." in result.text
    assert "<html>" not in result.text
    assert "Status: error" in result.text
    assert "provider timeout" in result.text


def test_build_book_context_reports_missing_refs() -> None:
    result = build_book_context(
        [{"book_id": "missing", "page_ids": ["page-1"]}],
        storage=FakeBookStorage(),  # type: ignore[arg-type]
    )

    assert result.text == ""
    assert result.warnings == ["book_not_found:missing"]
