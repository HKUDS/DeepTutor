"""Utilities for turning selected book pages into chat context.

The chat runtime consumes this module from two places:

* the main chat page when a user picks pages via ``@book``;
* the book reader side panel, which automatically references the current page.

Keep this module pure and storage-backed only. It should not call an LLM or
depend on FastAPI so it remains cheap to unit test and reuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Sequence

from .models import Block, BlockStatus, BlockType, Book, Chapter, Page, Spine
from .storage import BookStorage, get_book_storage

DEFAULT_MAX_CONTEXT_CHARS = 32_000
DEFAULT_MAX_PAGE_CHARS = 12_000
DEFAULT_MAX_BLOCK_CHARS = 4_000

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class NormalizedBookReference:
    """One selected book with the page ids that should be sent to chat."""

    book_id: str
    page_ids: list[str]

    def model_dump(self) -> dict[str, Any]:
        return {"book_id": self.book_id, "page_ids": list(self.page_ids)}


@dataclass
class BookContextResult:
    """Serialized book context plus non-fatal issues encountered while loading."""

    text: str = ""
    references: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_book_references(value: Any) -> list[NormalizedBookReference]:
    """Validate and de-duplicate the public ``book_references`` payload."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []

    refs: list[NormalizedBookReference] = []
    seen_books: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        book_id = str(item.get("book_id") or "").strip()
        raw_page_ids = item.get("page_ids") or []
        if (
            not book_id
            or not isinstance(raw_page_ids, Sequence)
            or isinstance(raw_page_ids, (str, bytes, bytearray))
        ):
            continue

        page_ids: list[str] = []
        seen_pages: set[str] = set()
        for raw_page_id in raw_page_ids:
            page_id = str(raw_page_id or "").strip()
            if not page_id or page_id in seen_pages:
                continue
            seen_pages.add(page_id)
            page_ids.append(page_id)

        if book_id in seen_books:
            existing = next((ref for ref in refs if ref.book_id == book_id), None)
            if existing is not None:
                for page_id in page_ids:
                    if page_id not in existing.page_ids:
                        existing.page_ids.append(page_id)
            continue

        seen_books.add(book_id)
        refs.append(NormalizedBookReference(book_id=book_id, page_ids=page_ids))

    return refs


def build_book_context(
    book_references: Any,
    *,
    storage: BookStorage | None = None,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    page_char_limit: int = DEFAULT_MAX_PAGE_CHARS,
    block_char_limit: int = DEFAULT_MAX_BLOCK_CHARS,
) -> BookContextResult:
    """Load selected book pages and serialize them into compact LLM context."""

    refs = normalize_book_references(book_references)
    if not refs:
        return BookContextResult()

    store = storage or get_book_storage()
    warnings: list[str] = []
    sections: list[str] = []

    for ref in refs:
        book = store.load_book(ref.book_id)
        if book is None:
            warnings.append(f"book_not_found:{ref.book_id}")
            continue

        spine = store.load_spine(ref.book_id)
        page_sections: list[str] = []
        for page_id in ref.page_ids:
            page = store.load_page(ref.book_id, page_id)
            if page is None:
                warnings.append(f"page_not_found:{ref.book_id}:{page_id}")
                continue
            chapter = spine.chapter_by_id(page.chapter_id) if spine else None
            page_text = _serialize_page(
                book=book,
                spine=spine,
                chapter=chapter,
                page=page,
                page_char_limit=page_char_limit,
                block_char_limit=block_char_limit,
            )
            if page_text:
                page_sections.append(page_text)

        if page_sections:
            sections.append(_serialize_book_header(book) + "\n\n" + "\n\n".join(page_sections))

    text = _clip("\n\n---\n\n".join(sections), max_chars)
    references = [ref.model_dump() for ref in refs]
    return BookContextResult(text=text, references=references, warnings=warnings)


def _serialize_book_header(book: Book) -> str:
    lines = [f"# Book: {_clean(book.title) or book.id}"]
    if book.description:
        lines.append(f"Description: {_clip(_clean(book.description), 800)}")
    if book.language:
        lines.append(f"Language: {_clean(book.language)}")
    return "\n".join(lines)


def _serialize_page(
    *,
    book: Book,
    spine: Spine | None,
    chapter: Chapter | None,
    page: Page,
    page_char_limit: int,
    block_char_limit: int,
) -> str:
    lines: list[str] = []
    chapter_title = chapter.title if chapter else ""
    lines.append(f"## Page: {_clean(page.title) or page.id}")
    if chapter_title:
        lines.append(f"Chapter: {_clean(chapter_title)}")
    if chapter and chapter.summary:
        lines.append(f"Chapter summary: {_clip(_clean(chapter.summary), 1200)}")
    objectives = page.learning_objectives or (chapter.learning_objectives if chapter else [])
    if objectives:
        lines.append("Learning objectives:")
        lines.extend(f"- {_clip(_clean(obj), 300)}" for obj in objectives if _clean(obj))
    if page.status:
        lines.append(f"Page status: {getattr(page.status, 'value', page.status)}")
    if spine and spine.exploration_summary:
        lines.append(f"Book source summary: {_clip(_clean(spine.exploration_summary), 1000)}")

    block_texts = [
        serialized
        for block in page.blocks
        if (serialized := _serialize_block(block, block_char_limit=block_char_limit))
    ]
    if block_texts:
        lines.append("Page content:")
        lines.extend(block_texts)
    if page.error:
        lines.append(f"Page error: {_clip(_clean(page.error), 600)}")
    return _clip("\n".join(lines), page_char_limit)


def _serialize_block(block: Block, *, block_char_limit: int) -> str:
    block_type = _enum_value(block.type)
    status = _enum_value(block.status)
    if status == BlockStatus.HIDDEN.value:
        return ""

    heading = f"### Block: {_clean(block.title) or block_type}"
    if block_type:
        heading += f" ({block_type})"

    if status != BlockStatus.READY.value:
        details = [heading, f"Status: {status or 'unknown'}"]
        if block.error:
            details.append(f"Error: {_clip(_clean(block.error), 500)}")
        return "\n".join(details)

    payload = block.payload if isinstance(block.payload, dict) else {}
    body = _payload_for_type(block_type, payload)
    if not body and block.error:
        body = f"Error: {_clip(_clean(block.error), 500)}"
    if not body:
        return ""
    return _clip(f"{heading}\n{body}", block_char_limit)


def _payload_for_type(block_type: str, payload: dict[str, Any]) -> str:
    bridge = _join_text_fields(payload, ("bridge_text", "transition_in"))
    main = ""
    if block_type in {BlockType.TEXT.value, BlockType.USER_NOTE.value}:
        main = _join_text_fields(payload, ("content", "body", "text", "markdown"))
    elif block_type == BlockType.CALLOUT.value:
        label = _clean(payload.get("label"))
        body = _clean(payload.get("body"))
        main = "\n".join(part for part in (label, body) if part)
    elif block_type == BlockType.SECTION.value:
        main = _format_section(payload)
    elif block_type == BlockType.QUIZ.value:
        main = _format_quiz(payload)
    elif block_type == BlockType.FLASH_CARDS.value:
        main = _format_flash_cards(payload)
    elif block_type == BlockType.TIMELINE.value:
        main = _format_timeline(payload)
    elif block_type == BlockType.CODE.value:
        main = _format_code(payload)
    elif block_type == BlockType.DEEP_DIVE.value:
        main = _format_deep_dive(payload)
    elif block_type in {
        BlockType.FIGURE.value,
        BlockType.INTERACTIVE.value,
        BlockType.ANIMATION.value,
        BlockType.CONCEPT_GRAPH.value,
    }:
        main = _format_visual_summary(payload)
    else:
        main = _safe_payload_summary(payload)

    return "\n".join(part for part in (bridge, main) if part)


def _format_section(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    if intro := _clean(payload.get("intro")):
        lines.append(intro)
    subsections = payload.get("subsections")
    if isinstance(subsections, list):
        for item in subsections:
            if not isinstance(item, dict):
                continue
            heading = _clean(item.get("heading"))
            body = _clean(item.get("body"))
            focus = _clean(item.get("focus"))
            if heading:
                lines.append(f"#### {heading}")
            if focus:
                lines.append(f"Focus: {focus}")
            if body:
                lines.append(body)
    if takeaway := _clean(payload.get("key_takeaway")):
        lines.append(f"Key takeaway: {takeaway}")
    return "\n".join(lines)


def _format_quiz(payload: dict[str, Any]) -> str:
    questions = payload.get("questions")
    if not isinstance(questions, list):
        return _join_text_fields(payload, ("topic", "question", "explanation"))
    lines: list[str] = []
    for idx, item in enumerate(questions[:8], start=1):
        if not isinstance(item, dict):
            continue
        question = _clean(item.get("question"))
        if not question:
            continue
        lines.append(f"Q{idx}: {question}")
        options = item.get("options")
        if isinstance(options, dict) and options:
            option_text = "; ".join(
                f"{_clean(key)}. {_clean(value)}" for key, value in options.items()
            )
            if option_text:
                lines.append(f"Options: {option_text}")
        if answer := _clean(item.get("correct_answer")):
            lines.append(f"Answer: {answer}")
        if explanation := _clean(item.get("explanation")):
            lines.append(f"Explanation: {explanation}")
    return "\n".join(lines)


def _format_flash_cards(payload: dict[str, Any]) -> str:
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return ""
    lines: list[str] = []
    for idx, item in enumerate(cards[:12], start=1):
        if not isinstance(item, dict):
            continue
        front = _clean(item.get("front"))
        back = _clean(item.get("back"))
        hint = _clean(item.get("hint"))
        if front and back:
            suffix = f" Hint: {hint}" if hint else ""
            lines.append(f"Card {idx}: {front} -> {back}{suffix}")
    return "\n".join(lines)


def _format_timeline(payload: dict[str, Any]) -> str:
    events = payload.get("events")
    if not isinstance(events, list):
        return ""
    lines: list[str] = []
    for item in events[:10]:
        if not isinstance(item, dict):
            continue
        date = _clean(item.get("date"))
        title = _clean(item.get("title"))
        description = _clean(item.get("description"))
        line = " - ".join(part for part in (date, title, description) if part)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _format_code(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    if intent := _clean(payload.get("intent")):
        lines.append(f"Intent: {intent}")
    if explanation := _clean(payload.get("explanation")):
        lines.append(f"Explanation: {explanation}")
    code = _clean(payload.get("code"))
    if code:
        language = _clean(payload.get("language")) or "code"
        lines.append(f"Code ({language}):\n{_clip(code, 1200)}")
    return "\n".join(lines)


def _format_deep_dive(payload: dict[str, Any]) -> str:
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, list):
        return ""
    lines: list[str] = []
    for item in suggestions[:6]:
        if not isinstance(item, dict):
            continue
        topic = _clean(item.get("topic"))
        rationale = _clean(item.get("rationale"))
        if topic:
            lines.append(f"- {topic}" + (f": {rationale}" if rationale else ""))
    return "\n".join(lines)


def _format_visual_summary(payload: dict[str, Any]) -> str:
    lines = [_join_text_fields(payload, ("description", "summary", "caption", "chart_type"))]
    key_points = payload.get("key_points")
    if isinstance(key_points, list):
        for point in key_points[:8]:
            if text := _clean(point):
                lines.append(f"- {text}")
    return "\n".join(part for part in lines if part)


def _safe_payload_summary(payload: dict[str, Any]) -> str:
    return "\n".join(_iter_safe_strings(payload, max_items=16))


def _iter_safe_strings(value: Any, *, max_items: int) -> Iterable[str]:
    emitted = 0

    def walk(node: Any, key: str = "") -> Iterable[str]:
        nonlocal emitted
        if emitted >= max_items:
            return
        lowered = key.lower()
        if lowered in {"code", "html", "svg", "content", "artifact", "artifacts"}:
            return
        if isinstance(node, str):
            text = _clean(node)
            if text:
                emitted += 1
                yield _clip(text, 500)
            return
        if isinstance(node, dict):
            for child_key, child_value in node.items():
                yield from walk(child_value, str(child_key))
                if emitted >= max_items:
                    break
        elif isinstance(node, list):
            for child in node:
                yield from walk(child, key)
                if emitted >= max_items:
                    break

    yield from walk(value)


def _join_text_fields(payload: dict[str, Any], keys: Sequence[str]) -> str:
    return "\n".join(text for key in keys if (text := _clean(payload.get(key))))


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _clean(value: Any) -> str:
    text = str(value or "")
    text = _THINK_RE.sub("", text)
    text = text.replace("</think>", "").replace("<think>", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clip(text: str, limit: int) -> str:
    text = _clean(text)
    if limit <= 0 or len(text) <= limit:
        return text
    head = max(0, limit - 40)
    return text[:head].rstrip() + "\n...[truncated]"


__all__ = [
    "BookContextResult",
    "NormalizedBookReference",
    "build_book_context",
    "normalize_book_references",
]
