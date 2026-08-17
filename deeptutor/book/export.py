"""
Markdown export
===============

Render a compiled book as one self-contained Markdown document.

A generated book that can only be read inside the app it was generated in is
half a deliverable. Markdown is the format that travels: it opens in an editor,
converts to PDF or EPUB with any of the usual tools, and diffs in git.

Every block type gets a text projection. Blocks whose value is inherently
visual (a rendered video, an interactive widget) degrade to their description
plus a pointer rather than being dropped silently — a reader scanning the export
should be able to tell that something was there.
"""

from __future__ import annotations

import re
from typing import Any

from .models import Block, BlockStatus, BlockType, Book, Page, Spine

_SAFE_FILENAME = re.compile(r"[^\w.-]+")

# Structural labels the export adds around generated content. The book's own
# prose is already in its language; these must follow, or a Chinese book exports
# with English scaffolding. Keyed by the same language codes the prompt layer
# uses (deeptutor/services/prompt/language.py), falling back to English.
_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "takeaway": "Key takeaway",
        "answer": "Answer",
        "front": "Front",
        "back": "Back",
        "sources": "Sources",
        "chapters": "Chapters",
        "note": "Note",
        "untitled_book": "Untitled book",
        "untitled_chapter": "Untitled chapter",
        "not_generated": "(This chapter has not been generated yet.)",
        "omitted": "({kind} omitted — it has no text representation.)",
    },
    "zh": {
        "takeaway": "要点",
        "answer": "答案",
        "front": "正面",
        "back": "背面",
        "sources": "来源",
        "chapters": "章节",
        "note": "提示",
        "untitled_book": "未命名书籍",
        "untitled_chapter": "未命名章节",
        "not_generated": "（本章尚未生成。）",
        "omitted": "（{kind} 无法用文本表示，已省略。）",
    },
}


def _labels(language: str | None) -> dict[str, str]:
    code = (language or "en").strip().lower()
    return _LABELS.get(code) or _LABELS.get(code.split("-", 1)[0]) or _LABELS["en"]


def export_filename(book: Book) -> str:
    """A filesystem- and header-safe ``.md`` name for *book*."""
    stem = _SAFE_FILENAME.sub("-", (book.title or "book").strip()).strip("-")
    return f"{stem or 'book'}.md"


def _payload_text(payload: dict[str, Any], *keys: str) -> str:
    """First non-empty string among *keys*."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _render_section(payload: dict[str, Any], labels: dict[str, str]) -> str:
    parts: list[str] = []
    intro = _payload_text(payload, "intro")
    if intro:
        parts.append(intro)

    subsections = payload.get("subsections")
    if isinstance(subsections, list):
        for sub in subsections:
            if not isinstance(sub, dict):
                continue
            heading = _payload_text(sub, "heading")
            body = _payload_text(sub, "body")
            if heading:
                parts.append(f"### {heading}")
            if body:
                parts.append(body)

    body = _payload_text(payload, "body")
    if body and not subsections:
        parts.append(body)

    takeaway = _payload_text(payload, "key_takeaway")
    if takeaway:
        parts.append(f"> **{labels['takeaway']}** — {takeaway}")
    return "\n\n".join(parts)


def _render_quiz(payload: dict[str, Any], labels: dict[str, str]) -> str:
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return ""
    parts: list[str] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        parts.append(f"**{index}. {_payload_text(question, 'question')}**")
        options = question.get("options")
        if isinstance(options, dict) and options:
            parts.append(
                "\n".join(f"- **{key.upper()}.** {value}" for key, value in options.items())
            )
        answer = _payload_text(question, "correct_answer")
        if answer:
            parts.append(
                f"<details><summary>{labels['answer']}</summary>\n\n{answer}\n\n</details>"
            )
        explanation = _payload_text(question, "explanation")
        if explanation:
            parts.append(f"_{explanation}_")
    return "\n\n".join(parts)


def _render_flash_cards(payload: dict[str, Any], labels: dict[str, str]) -> str:
    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        return ""
    rows = [f"| {labels['front']} | {labels['back']} |", "| --- | --- |"]
    for card in cards:
        if not isinstance(card, dict):
            continue
        front = _payload_text(card, "front").replace("|", "\\|")
        back = _payload_text(card, "back").replace("|", "\\|")
        rows.append(f"| {front} | {back} |")
    return "\n".join(rows) if len(rows) > 2 else ""


def _render_timeline(payload: dict[str, Any]) -> str:
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return ""
    lines: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        date = _payload_text(event, "date")
        title = _payload_text(event, "title")
        description = _payload_text(event, "description")
        head = " — ".join(part for part in (date, title) if part)
        lines.append(f"- **{head}**" + (f"  \n  {description}" if description else ""))
    return "\n".join(lines)


def _render_code(payload: dict[str, Any]) -> str:
    code = _payload_text(payload, "code")
    if not code:
        return ""
    language = _payload_text(payload, "language")
    parts = [f"```{language}\n{code}\n```"]
    explanation = _payload_text(payload, "explanation")
    if explanation:
        parts.append(explanation)
    return "\n\n".join(parts)


def _render_visual(payload: dict[str, Any], kind: str, labels: dict[str, str]) -> str:
    """Figures, interactives and animations — keep whatever text survives."""
    parts: list[str] = []
    description = _payload_text(payload, "description", "summary")
    if description:
        parts.append(description)

    code = payload.get("code")
    if isinstance(code, dict):
        content = _payload_text(code, "content")
        language = _payload_text(code, "language")
        if content:
            parts.append(f"```{language}\n{content}\n```")
    elif _payload_text(payload, "mermaid"):
        parts.append(f"```mermaid\n{_payload_text(payload, 'mermaid')}\n```")

    video = _payload_text(payload, "video_url")
    if video:
        parts.append(f"[▶ {kind}]({video})")

    if not parts:
        parts.append("_" + labels["omitted"].format(kind=kind) + "_")
    return "\n\n".join(parts)


def _render_deep_dive(payload: dict[str, Any]) -> str:
    """Suggested follow-up topics.

    The generator emits ``{"topic", "rationale"}`` dicts — never bare strings —
    so a string-only filter matched nothing and dropped the block entirely.
    """
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, list):
        return ""
    lines: list[str] = []
    for item in suggestions:
        if isinstance(item, str) and item.strip():
            lines.append(f"- {item.strip()}")
        elif isinstance(item, dict):
            topic = _payload_text(item, "topic")
            rationale = _payload_text(item, "rationale")
            if not topic:
                continue
            lines.append(f"- **{topic}**" + (f" — {rationale}" if rationale else ""))
    return "\n".join(lines)


def render_block(block: Block, language: str = "en") -> str:
    """Markdown for one block, or ``""`` when it has nothing to contribute."""
    if block.status != BlockStatus.READY:
        return ""

    payload = block.payload or {}
    labels = _labels(language)
    bridge = _payload_text(payload, "bridge_text")

    if block.type in (BlockType.TEXT, BlockType.USER_NOTE):
        body = _payload_text(payload, "body", "content")
    elif block.type == BlockType.SECTION:
        body = _render_section(payload, labels)
    elif block.type == BlockType.CALLOUT:
        label = _payload_text(payload, "label")
        text = _payload_text(payload, "body")
        body = f"> **{label or labels['note']}** — {text}" if text else ""
    elif block.type == BlockType.QUIZ:
        body = _render_quiz(payload, labels)
    elif block.type == BlockType.FLASH_CARDS:
        body = _render_flash_cards(payload, labels)
    elif block.type == BlockType.TIMELINE:
        body = _render_timeline(payload)
    elif block.type == BlockType.CODE:
        body = _render_code(payload)
    elif block.type in (BlockType.FIGURE, BlockType.CONCEPT_GRAPH):
        body = _render_visual(payload, "figure", labels)
    elif block.type == BlockType.INTERACTIVE:
        body = _render_visual(payload, "interactive widget", labels)
    elif block.type == BlockType.ANIMATION:
        body = _render_visual(payload, "animation", labels)
    elif block.type == BlockType.DEEP_DIVE:
        body = _render_deep_dive(payload)
    else:
        body = _payload_text(payload, "body", "content")

    if not body:
        return ""

    parts: list[str] = []
    if bridge:
        parts.append(bridge)
    # The overview intro already opens with its own H1.
    if block.title and block.type not in (BlockType.TEXT, BlockType.SECTION):
        parts.append(f"#### {block.title}")
    parts.append(body)
    return "\n\n".join(parts)


def render_book_markdown(book: Book, spine: Spine | None, pages: list[Page]) -> str:
    """The whole book as one Markdown document."""
    labels = _labels(book.language)
    out: list[str] = [f"# {book.title or labels['untitled_book']}"]

    if book.description:
        out.append(f"*{book.description}*")

    meta: list[str] = []
    if book.knowledge_bases:
        meta.append(f"**{labels['sources']}:** {', '.join(book.knowledge_bases)}")
    if spine and spine.chapters:
        meta.append(f"**{labels['chapters']}:** {len(spine.chapters)}")
    if meta:
        out.append(" · ".join(meta))

    out.append("---")

    for page in sorted(pages, key=lambda p: (p.order, p.created_at)):
        out.append(f"## {page.title or labels['untitled_chapter']}")

        if page.learning_objectives:
            out.append("\n".join(f"- {objective}" for objective in page.learning_objectives))

        rendered = [render_block(block, book.language) for block in page.blocks]
        body = [chunk for chunk in rendered if chunk]
        if body:
            out.extend(body)
        else:
            out.append(f"_{labels['not_generated']}_")

    return "\n\n".join(out).rstrip() + "\n"


__all__ = ["render_block", "render_book_markdown", "export_filename"]
