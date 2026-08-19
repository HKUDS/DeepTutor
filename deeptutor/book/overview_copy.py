"""Reader-facing copy for the engine-injected Overview chapter.

This one page is built **deterministically** — no LLM call — so its wording
cannot come from the model the way every other block's does. It used to live as
``"中文" if book.language == "zh" else "English"`` conditionals scattered through
``engine.py``, which meant the language picker could offer eleven languages
while the book's own front page only ever spoke two.

Collecting it here does not by itself translate the page, but it turns "add a
language" from an edit across two functions into one entry in this table, and
it makes the gap visible instead of implicit: anything not listed falls back to
English, and :func:`missing_languages` reports what is still owed.
"""

from __future__ import annotations

from typing import Any

# Keys every entry must define. Kept explicit so a partial translation fails
# loudly in tests rather than rendering a stray English string mid-page.
REQUIRED_KEYS = frozenset(
    {
        "chapter_title",
        "chapter_summary",
        "objectives",
        "intro_title",
        "intro_body",
        "untitled_book",
        "concept_map_title",
        "chapter_index_title",
        "chapter_index_heading",
    }
)

_COPY: dict[str, dict[str, Any]] = {
    "en": {
        "chapter_title": "How to read this book",
        "chapter_summary": (
            "Auto-generated overview of the book's concept graph and chapter index."
        ),
        "objectives": [
            "See the full chapter map at a glance",
            "Understand how concepts depend on each other",
            "Pick the reading path that fits your goals",
        ],
        "intro_title": "How to read this book",
        "intro_body": (
            "The diagram below maps the {concepts} core concepts in this book and "
            "how they depend on each other. The chapter index that follows lists "
            "all {chapters} chapters — read top-to-bottom for the recommended "
            "path, or jump straight to whatever you're most curious about."
        ),
        "untitled_book": "This book",
        "concept_map_title": "Concept map",
        "chapter_index_title": "Chapter index",
        "chapter_index_heading": "## Chapter index",
    },
    "zh": {
        "chapter_title": "本书导览",
        "chapter_summary": "自动生成的概念图与章节索引，作为本书的入口。",
        "objectives": [
            "了解整本书的章节脉络",
            "掌握各章之间的概念依赖关系",
            "选择最合适的阅读顺序",
        ],
        "intro_title": "如何阅读这本书",
        "intro_body": (
            "下方的概念图展示了本书 {concepts} 个核心概念以及它们之间的依赖关系；"
            "再下方是 {chapters} 个章节的入口。"
            "你可以按从上到下的顺序阅读，也可以根据自己的兴趣或先验知识选择切入点。"
        ),
        "untitled_book": "本书",
        "concept_map_title": "概念图",
        "chapter_index_title": "章节索引",
        "chapter_index_heading": "## 章节索引",
    },
}


def overview_copy(language: str | None) -> dict[str, Any]:
    """Copy for *language*, falling back to English (then to the base tag).

    ``zh-tw`` finds no exact entry, tries ``zh``, and only then falls back —
    matching how the prompt layer resolves language tags.
    """
    code = (language or "en").strip().lower()
    return _COPY.get(code) or _COPY.get(code.split("-", 1)[0]) or _COPY["en"]


def missing_languages(supported: list[str]) -> list[str]:
    """Which of *supported* still render the Overview page in English.

    Not a failure — the page stays readable — but a book generated in a
    language listed here has an English front page in front of prose that is
    not English. Used by tests to keep the gap honest and countable.
    """
    return [
        code
        for code in supported
        if code.strip().lower() not in _COPY and code.strip().lower().split("-", 1)[0] not in _COPY
    ]


__all__ = ["REQUIRED_KEYS", "missing_languages", "overview_copy"]
