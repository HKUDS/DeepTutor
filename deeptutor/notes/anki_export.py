"""Render notebook flashcards as Anki's tab-separated import text.

The format follows Anki 2.1.55+ header lines so File -> Import creates Basic
notes in a deck named after each note. GUIDs are the stable review ``card_id``
values, so a later import updates the same cards instead of duplicating them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import html
import re
from typing import Any

from deeptutor.co_writer.storage import CoWriterDocument, CoWriterStorage
from deeptutor.notes.review import page_cards

ANKI_HEADERS: tuple[str, ...] = (
    "#separator:tab",
    "#html:true",
    "#notetype:Basic",
    "#deck column:3",
    "#tags column:4",
    "#guid column:5",
)

_PROTECTED_SPANS = re.compile(
    r"(?P<fence>```[\s\S]*?```)|(?P<code>`[^`]+`)|"
    r"(?P<block_math>\$\$[\s\S]+?\$\$)|(?P<math>(?<!\$)\$(?!\$)[^$\n]+?\$)"
)
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(
    r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<![A-Za-z0-9_])_(?!_)(.+?)(?<!_)_(?![A-Za-z0-9_])"
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SLUG_SPLIT = re.compile(r"[^\w]+", flags=re.UNICODE)
_SLOT = re.compile(r"\x00(\d+)\x00")


def deck_name(title: str) -> str:
    """Return the Anki deck name ``DeepTutor::<note title>``.

    Args:
        title: Note title. ``::`` is replaced so it cannot create extra decks.

    Returns:
        A sanitised hierarchical deck name.
    """
    cleaned = _CONTROL_CHARS.sub("", (title or "").strip()) or "Untitled"
    cleaned = cleaned.replace("::", " — ")
    return f"DeepTutor::{cleaned}"


def note_tags(title: str) -> str:
    """Return space-separated Anki tags for a note.

    Args:
        title: Note title, turned into a slug after the ``deeptutor`` tag.

    Returns:
        ``deeptutor`` plus an optional title slug.
    """
    slug = _SLUG_SPLIT.sub("-", (title or "").strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-").lower()
    if not slug or slug == "deeptutor":
        return "deeptutor"
    return f"deeptutor {slug}"


def markdown_to_anki_html(text: str) -> str:
    """Convert card Markdown to minimal HTML Anki can import safely.

    Paragraphs, bold, italic, code, and line breaks are preserved. ``$...$`` /
    ``$$...$$`` become Anki MathJax ``\\(...\\)`` / ``\\[...\\]``. Existing
    markup is escaped so it cannot run as HTML.

    Args:
        text: Flashcard front or back, as stored on the note.

    Returns:
        HTML with no raw tab or newline characters.
    """
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    slots: list[str] = []

    def stash(fragment: str) -> str:
        slots.append(fragment)
        return f"\x00{len(slots) - 1}\x00"

    def protect(match: re.Match[str]) -> str:
        raw = match.group()
        if match.lastgroup == "fence":
            body = html.escape(raw[3:-3].strip("\n")).replace("\n", "<br>")
            return stash(f"<pre><code>{body}</code></pre>")
        if match.lastgroup == "code":
            return stash(f"<code>{html.escape(raw[1:-1])}</code>")
        if match.lastgroup == "block_math":
            return stash(rf"\[{html.escape(raw[2:-2].strip())}\]")
        return stash(rf"\({html.escape(raw[1:-1].strip())}\)")

    # Match spans once: code inside math (or math inside code) is literal,
    # never a nested placeholder. NUL is removed above before reserving slots.
    protected = _PROTECTED_SPANS.sub(protect, normalized)
    escaped = html.escape(protected)
    marked = _BOLD.sub(lambda match: f"<b>{match.group(1) or match.group(2)}</b>", escaped)
    marked = _ITALIC.sub(lambda match: f"<i>{match.group(1) or match.group(2)}</i>", marked)
    html_body = _paragraphs(marked)
    html_body = _SLOT.sub(lambda match: slots[int(match.group(1))], html_body)
    return _anki_field(html_body)


def cards_from_document(doc: CoWriterDocument) -> list[dict[str, Any]]:
    """Return flashcards from one note, skipping malformed blocks.

    Args:
        doc: Loaded notebook page.

    Returns:
        Cards in ``page_cards`` order.
    """
    return list(page_cards(doc))


def cards_from_storage(storage: CoWriterStorage) -> list[dict[str, Any]]:
    """Return flashcards from every note in the active workspace.

    Args:
        storage: Per-user notebook store.

    Returns:
        Cards grouped by the store's document list order.
    """
    cards: list[dict[str, Any]] = []
    for summary in storage.list_documents():
        doc = storage.load_document(summary.id)
        if doc is None:
            continue
        cards.extend(page_cards(doc))
    return cards


def render_anki_export(cards: Sequence[Mapping[str, Any]]) -> str:
    """Render cards as Anki 2.1.55+ tab-separated import text.

    Args:
        cards: Mapping with ``front``, ``back``, ``page_title``, and ``card_id``.

    Returns:
        UTF-8 text with header lines, one row per card, and a trailing newline.
    """
    lines = list(ANKI_HEADERS)
    for card in cards:
        title = str(card.get("page_title", ""))
        front = markdown_to_anki_html(str(card.get("front", "")))
        back = markdown_to_anki_html(str(card.get("back", "")))
        deck = _anki_field(deck_name(title))
        tags = _anki_field(note_tags(title))
        guid = _anki_field(str(card.get("card_id", "")))
        lines.append("\t".join((front, back, deck, tags, guid)))
    return "\n".join(lines) + "\n"


def _paragraphs(text: str) -> str:
    chunks = re.split(r"\n{2,}", text.strip())
    parts = [f"<p>{chunk.replace(chr(10), '<br>')}</p>" for chunk in chunks if chunk != ""]
    return "".join(parts)


def _anki_field(value: str) -> str:
    return value.replace("\t", " ").replace("\r", "").replace("\n", "")
