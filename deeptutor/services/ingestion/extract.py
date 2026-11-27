"""Turn a parsed document into chapter-aware, page-located chunks.

Why this is not just "split the markdown"
-----------------------------------------
A citation must say ``[نام کتاب | فصل]`` (D-009), and a chapter is not something
you can recover from a flat markdown blob without guessing. So the extractor has
two jobs, in order:

1. **Find the chapter boundaries.** It prefers the parser's structured
   ``blocks`` (MinerU's content list carries ``text_level``, which marks a
   heading), and falls back to scanning the markdown for heading lines. A
   document with neither yields chunks with an empty chapter -- which downgrades
   the citation to the book name rather than inventing a chapter. That fallback
   is the important behaviour: a wrong chapter is worse than no chapter, because
   a student cannot tell it is wrong.

2. **Carry page provenance through.** Every chunk remembers ``page_index`` (the
   physical PDF page) and ``page_label`` (what is printed on it). A citation
   never shows either, but the eval harness and the audit need them, and losing
   them at this stage is unrecoverable.

Persian specifics that are easy to get wrong
--------------------------------------------
* Heading detection must accept Persian numerals and RTL punctuation, so the
  digit class is not ``[0-9]``.
* A heading like "فصل ۱: مجموعه‌ها" must yield the chapter title *including* the
  number, because that is what the student sees in the book.
* ZWNJ (U+200C) is normal in Persian text and must **not** be stripped here.
  Phase 2's ``normalize_profile`` rejects it for profile *input*; ingested text
  is a different path and stripping it would corrupt every word like «کتاب‌ها».

Nothing here calls a model. Extraction is deterministic so a golden test can
assert an exact chunk boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Any, Sequence
import unicodedata

logger = logging.getLogger(__name__)

#: Above this many characters a block is split at sentence boundaries. Chosen so
#: a chunk is comfortably inside a typical embedding window while still holding a
#: full paragraph and its context.
MAX_CHUNK_CHARS = 1200

#: Below this a block is merged into the next one rather than emitted alone: a
#: five-character chunk ("۱-۲") embeds into noise and retrieves badly.
MIN_CHUNK_CHARS = 40

#: Heading patterns, in the order they are tried. Persian numerals are included
#: because the books use them, and Arabic-Indic digits appear in some reprints.
_HEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s{0,3}#{1,4}\s+(?P<title>.+?)\s*#*\s*$"),
    re.compile(r"^\s*(?P<title>(?:فصل|بخش|درس|پودمان|گفتار)\s*[۰-۹0-9]+[^\n]{0,120})$"),
    re.compile(r"^\s*(?P<title>[۰-۹0-9]{1,2}\s*[-–.]\s*[^\n]{2,120})$"),
)

_WS_RE = re.compile(r"[ \t\u00a0]+")


def _normalize_line(line: str) -> str:
    """Collapse whitespace but keep ZWNJ and every Persian character.

    ``unicodedata.normalize("NFC", ...)`` is applied because the same Persian
    word can arrive composed or decomposed, and two spellings of one word create
    two chunks that should have been one.
    """
    return _WS_RE.sub(" ", unicodedata.normalize("NFC", line)).strip()


def is_heading(line: str) -> str | None:
    """The heading text if ``line`` is a heading, else ``None``."""
    text = _normalize_line(line)
    if not text:
        return None
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(text)
        if match:
            return match.group("title").strip()
    return None


def split_long(text: str, *, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split at sentence boundaries, never mid-sentence unless a sentence alone
    exceeds the limit.

    Persian sentence terminators are ``.``, ``؟``, ``!`` and the Arabic full stop
    ``۔``. Splitting on ``.`` alone would miss most questions, and splitting on
    newlines alone would leave a long poem as one chunk.
    """
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = re.split(r"(?<=[.؟!۔])\s+", text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        # A single sentence longer than the limit: hard-wrap it. This is the
        # only place a chunk boundary may fall inside a sentence, and it is
        # recorded so the caller knows the chunk is not semantically whole.
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        current = sentence
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


@dataclass
class ExtractedChunk:
    """One retrievable unit, with both physical and logical provenance."""

    page_index: int
    ordinal: int
    text: str
    page_label: str = ""
    chapter_index: int | None = None
    chapter_title: str = ""
    section_title: str = ""
    block_kind: str = "text"

    def as_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "ordinal": self.ordinal,
            "text": self.text,
            "page_label": self.page_label,
            "chapter_index": self.chapter_index,
            "chapter_title": self.chapter_title,
            "section_title": self.section_title,
            "block_kind": self.block_kind,
        }


@dataclass
class ExtractionResult:
    chunks: list[ExtractedChunk] = field(default_factory=list)
    chapter_count: int = 0
    #: True when chapter boundaries came from structure, false when the document
    #: had none and the citations will be book-only.
    has_chapters: bool = False

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def _block_kind(block: dict[str, Any]) -> str:
    """Map a parser block type onto our vocabulary.

    Unknown types default to ``text`` rather than being dropped: losing a block
    silently is how a whole section of a book disappears from retrieval, and a
    mislabelled one is far easier to notice.
    """
    raw = str(block.get("type") or block.get("block_type") or "").lower()
    if raw in {"table", "table_body"}:
        return "table"
    if raw in {"image", "figure", "img"}:
        return "figure"
    if raw in {"equation", "formula", "interline_equation"}:
        return "formula"
    return "text"


def _block_text(block: dict[str, Any]) -> str:
    """Best-effort text of a block, without inventing content.

    A figure with no caption contributes no text: emitting the alt-text of an
    unlabelled image would create a chunk that says nothing and still counts as
    a retrievable unit, which pollutes the index.
    """
    for key in ("text", "content", "caption", "table_caption"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_line(value)
    body = block.get("table_body")
    if isinstance(body, str) and body.strip():
        return _normalize_line(body)
    return ""


def extract_from_blocks(blocks: Sequence[dict[str, Any]]) -> ExtractionResult:
    """Extract from a structured block list (preferred path)."""
    result = ExtractionResult()
    chapter_index: int | None = None
    chapter_title = ""
    section_title = ""
    ordinal_by_page: dict[int, int] = {}
    buffer: list[str] = []

    def flush(page: int, kind: str) -> None:
        if not buffer:
            return
        text = " ".join(buffer).strip()
        buffer.clear()
        if len(text) < MIN_CHUNK_CHARS and kind == "text":
            # A short *prose* fragment embeds into noise, so it joins the
            # previous chunk rather than standing alone.
            #
            # Non-prose kinds are deliberately excluded from this merge. A
            # three-cell table or a one-line formula is genuinely short, and
            # folding it into the surrounding paragraph destroys the only
            # signal that says "this is tabular data" -- which is exactly the
            # signal a student asking about a table needs. Length is a bad
            # proxy for meaning for structured blocks.
            if result.chunks and result.chunks[-1].page_index == page:
                result.chunks[-1].text = f"{result.chunks[-1].text} {text}".strip()
                return
        for piece in split_long(text):
            ordinal = ordinal_by_page.get(page, 0)
            ordinal_by_page[page] = ordinal + 1
            result.chunks.append(
                ExtractedChunk(
                    page_index=page,
                    ordinal=ordinal,
                    text=piece,
                    chapter_index=chapter_index,
                    chapter_title=chapter_title,
                    section_title=section_title,
                    block_kind=kind,
                )
            )

    for block in blocks:
        if not isinstance(block, dict):
            continue
        page = block.get("page_idx", block.get("page_index", 0))
        page = page if isinstance(page, int) and page >= 0 else 0
        kind = _block_kind(block)
        text = _block_text(block)
        if not text:
            continue
        level = block.get("text_level")
        heading = is_heading(text)
        # MinerU marks headings with text_level; a markdown heading is also one.
        is_head = bool(heading) and (
            (isinstance(level, int) and level >= 1) or text.lstrip().startswith("#")
        )
        if is_head:
            flush(page, kind)
            chapter_index = 0 if chapter_index is None else chapter_index + 1
            chapter_title = heading or text
            section_title = ""
            result.has_chapters = True
            result.chapter_count += 1
            continue
        buffer.append(text)
        flush(page, kind)
    flush(0, "text")
    return result


def extract_from_markdown(markdown: str) -> ExtractionResult:
    """Extract from markdown when no structured blocks are available.

    There is no page information in markdown, so every chunk gets
    ``page_index = 0``. That is honest: a citation from this path can name the
    book and chapter but not a page, which is exactly what D-009 allows.
    """
    result = ExtractionResult()
    chapter_index: int | None = None
    chapter_title = ""
    section_title = ""
    ordinal = 0
    buffer: list[str] = []

    def flush() -> None:
        nonlocal ordinal
        if not buffer:
            return
        text = " ".join(buffer).strip()
        buffer.clear()
        if len(text) < MIN_CHUNK_CHARS:
            if result.chunks and result.chunks[-1].chapter_title == chapter_title:
                result.chunks[-1].text = f"{result.chunks[-1].text} {text}".strip()
                return
        for piece in split_long(text):
            result.chunks.append(
                ExtractedChunk(
                    page_index=0,
                    ordinal=ordinal,
                    text=piece,
                    chapter_index=chapter_index,
                    chapter_title=chapter_title,
                    section_title=section_title,
                )
            )
            ordinal += 1

    for raw_line in (markdown or "").splitlines():
        line = _normalize_line(raw_line)
        if not line:
            flush()
            continue
        heading = is_heading(raw_line)
        if heading:
            flush()
            chapter_index = 0 if chapter_index is None else chapter_index + 1
            chapter_title = heading
            section_title = ""
            result.has_chapters = True
            result.chapter_count += 1
            continue
        buffer.append(line)
    flush()
    return result


def extract(parsed: Any) -> ExtractionResult:
    """Prefer structure; fall back to markdown; never fail on an empty document."""
    blocks = getattr(parsed, "blocks", None)
    if blocks:
        result = extract_from_blocks(blocks)
        if result.chunks:
            return result
        logger.info("structured blocks produced no chunks; falling back to markdown")
    markdown = getattr(parsed, "markdown", "") or ""
    return extract_from_markdown(markdown)
