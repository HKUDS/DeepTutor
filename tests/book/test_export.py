"""Markdown export — a generated book has to be able to leave the app."""

from deeptutor.book.export import export_filename, render_block, render_book_markdown
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    Page,
)


def _ready(block_type: BlockType, payload: dict, **kwargs) -> Block:
    return Block(type=block_type, status=BlockStatus.READY, payload=payload, **kwargs)


def test_section_renders_intro_subsections_and_takeaway() -> None:
    md = render_block(
        _ready(
            BlockType.SECTION,
            {
                "intro": "Opening paragraph.",
                "subsections": [{"heading": "First", "body": "Body one."}],
                "key_takeaway": "The thing to remember.",
            },
        )
    )
    assert "Opening paragraph." in md
    assert "### First" in md
    assert "Body one." in md
    assert "> **Key takeaway** — The thing to remember." in md


def test_quiz_hides_the_answer_behind_a_details_block() -> None:
    md = render_block(
        _ready(
            BlockType.QUIZ,
            {
                "questions": [
                    {
                        "question": "What is 2+2?",
                        "options": {"a": "3", "b": "4"},
                        "correct_answer": "B",
                        "explanation": "Addition.",
                    }
                ]
            },
        )
    )
    assert "**1. What is 2+2?**" in md
    assert "- **A.** 3" in md
    assert "<details><summary>Answer</summary>" in md
    assert "_Addition._" in md


def test_flash_cards_become_a_table_with_escaped_pipes() -> None:
    md = render_block(
        _ready(
            BlockType.FLASH_CARDS,
            {"cards": [{"front": "a|b", "back": "c"}]},
        )
    )
    assert "| Front | Back |" in md
    assert r"a\|b" in md


def test_unrendered_blocks_contribute_nothing() -> None:
    pending = Block(type=BlockType.TEXT, status=BlockStatus.PENDING, payload={"body": "x"})
    assert render_block(pending) == ""
    assert render_block(_ready(BlockType.TEXT, {})) == ""


def test_a_visual_with_no_text_says_so_rather_than_vanishing() -> None:
    md = render_block(_ready(BlockType.ANIMATION, {}))
    assert "animation" in md.lower()


def test_bridge_text_precedes_the_block_it_introduces() -> None:
    md = render_block(
        _ready(
            BlockType.CALLOUT,
            {"bridge_text": "Which brings us to…", "label": "Key idea", "body": "It matters."},
        )
    )
    assert md.index("Which brings us to…") < md.index("Key idea")


def test_whole_book_carries_title_chapters_and_objectives() -> None:
    book = Book(title="My Book", description="A guide.", page_count=1)
    page = Page(
        id="pg_1",
        book_id=book.id,
        title="Chapter One",
        learning_objectives=["Understand X"],
        blocks=[_ready(BlockType.TEXT, {"body": "Hello."})],
    )
    md = render_book_markdown(book, None, [page])

    assert md.startswith("# My Book")
    assert "*A guide.*" in md
    assert "## Chapter One" in md
    assert "- Understand X" in md
    assert "Hello." in md
    assert md.endswith("\n")


def test_an_ungenerated_chapter_is_marked_rather_than_dropped() -> None:
    book = Book(title="My Book")
    page = Page(id="pg_1", book_id=book.id, title="Not yet")
    md = render_book_markdown(book, None, [page])
    assert "## Not yet" in md
    assert "not been generated" in md


def test_chapters_export_in_reading_order() -> None:
    book = Book(title="B")
    pages = [
        Page(id="pg_2", book_id=book.id, title="Second", order=2),
        Page(id="pg_1", book_id=book.id, title="First", order=1),
    ]
    md = render_book_markdown(book, None, pages)
    assert md.index("## First") < md.index("## Second")


def test_filenames_survive_cjk_and_punctuation() -> None:
    assert export_filename(Book(title="Agentic RAG: 从静态到自治")) == (
        "Agentic-RAG-从静态到自治.md"
    )
    assert export_filename(Book(title="   ")) == "book.md"
    assert export_filename(Book(title="///")) == "book.md"


# ── Language awareness + header safety ──────────────────────────────────


def test_a_chinese_book_exports_with_chinese_scaffolding() -> None:
    book = Book(title="智能体检索增强", language="zh", knowledge_bases=["kb1"])
    page = Page(
        id="pg_1",
        book_id=book.id,
        title="第一章",
        blocks=[
            _ready(BlockType.SECTION, {"intro": "导言", "key_takeaway": "记住这个"}),
            _ready(BlockType.FLASH_CARDS, {"cards": [{"front": "问", "back": "答"}]}),
            _ready(BlockType.QUIZ, {"questions": [{"question": "Q", "correct_answer": "A"}]}),
        ],
    )
    md = render_book_markdown(book, None, [page])

    assert "**来源:**" in md and "**Sources:**" not in md
    assert "> **要点** —" in md and "Key takeaway" not in md
    assert "| 正面 | 背面 |" in md and "| Front | Back |" not in md
    assert "<details><summary>答案</summary>" in md


def test_an_unknown_language_falls_back_to_english() -> None:
    book = Book(title="Buch", language="de")
    page = Page(
        id="pg_1",
        book_id=book.id,
        title="Kapitel",
        blocks=[_ready(BlockType.SECTION, {"intro": "x", "key_takeaway": "y"})],
    )
    assert "> **Key takeaway** —" in render_book_markdown(book, None, [page])


def test_deep_dive_suggestions_render_as_the_generator_emits_them() -> None:
    """The generator produces dicts; a string-only filter dropped the block."""
    md = render_block(
        _ready(
            BlockType.DEEP_DIVE,
            {"suggestions": [{"topic": "Attention", "rationale": "the core idea"}]},
        )
    )
    assert "**Attention**" in md
    assert "the core idea" in md


def test_export_filenames_survive_a_latin_1_hostile_title() -> None:
    from deeptutor.api.utils.http_headers import content_disposition

    header = content_disposition(
        export_filename(Book(title="智能体检索增强")), disposition="attachment"
    )
    # HTTP/1.1 headers are latin-1; this used to raise UnicodeEncodeError and 500.
    header.encode("latin-1")
    assert "filename*=UTF-8''" in header
