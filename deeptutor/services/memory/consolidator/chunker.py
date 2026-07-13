"""Character-based chunking with boundary expansion.

The L2 / L3 update flow concatenates inputs into one string, then
:func:`chunk_with_boundary` cuts it into ≤ budget pieces. Each piece's
right edge is extended forward to the next paragraph or sentence
boundary — content is **never truncated mid-statement**. Adjacent
chunks overlap by a percentage of the target size so a fact straddling
a cut still gets a fair read.

Pure functions: no I/O, no LLM. Easy to unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

Boundary = Literal["paragraph", "sentence"]

# Paragraph boundary: one or more blank lines.
_PARA_BOUNDARY = re.compile(r"\n\s*\n+")
# Sentence boundary: terminal punctuation followed by space/newline.
# Covers ASCII (.!?) and CJK (。！？).
_SENT_BOUNDARY = re.compile(r"[.!?。！？](?:[\")»」』]+)?(?=\s|$)")


@dataclass(frozen=True)
class ChunkSpan:
    """One chunk's coordinates inside the source text.

    ``start`` is inclusive, ``end`` exclusive. ``index`` is the 0-based
    position in the returned list (useful for events).
    """

    index: int
    start: int
    end: int
    text: str


def chunk_with_boundary(
    text: str,
    *,
    budget: int,
    overlap_ratio: float,
    min_chunk_chars: int,
    max_chunk_chars: int,
    boundary: Boundary = "paragraph",
) -> list[ChunkSpan]:
    """Cut ``text`` into ≤ ``budget`` chunks aligned to natural boundaries.

    * Target size = ``clamp(ceil(len(text) / budget), min, max)``.
    * Right edge of each chunk is extended forward to the next
      ``boundary`` so no sentence/paragraph is split.
    * Adjacent chunks overlap by ``round(target * overlap_ratio)`` chars.
    * If the input is short enough to fit in a single chunk, returns
      one ``ChunkSpan`` covering everything.
    """
    if not text.strip():
        return []
    if budget < 1:
        budget = 1

    n = len(text)
    target = math.ceil(n / budget)
    target = max(min_chunk_chars, min(max_chunk_chars, target))
    overlap = max(0, min(target - 1, round(target * overlap_ratio)))

    # Short-circuit: input fits in one chunk.
    if n <= target:
        return [ChunkSpan(index=0, start=0, end=n, text=text)]

    # Hard cap on how far the right edge can be pulled to find a
    # boundary. Beyond this we accept a non-boundary cut so chunks
    # never grow past ``max_chunk_chars`` even in degenerate input
    # (e.g. a single long line with no paragraph/sentence breaks).
    spans: list[ChunkSpan] = []
    cursor = 0
    while cursor < n:
        target_end = min(n, cursor + target)
        hard_cap = min(n, cursor + max_chunk_chars)
        if target_end >= n:
            end = n
        else:
            end = _expand_to_boundary(text, target_end, boundary, limit=hard_cap)
        # Guarantee forward motion: the boundary expansion may pull us
        # to len(text), or — degenerate input — to ``target_end`` itself.
        if end <= cursor:
            end = min(n, cursor + max(1, target))
        spans.append(
            ChunkSpan(
                index=len(spans),
                start=cursor,
                end=end,
                text=text[cursor:end],
            )
        )
        if end >= n:
            break
        next_cursor = end - overlap
        # No infinite loop: must advance by at least one char even with
        # huge overlap.
        if next_cursor <= cursor:
            next_cursor = cursor + 1
        cursor = next_cursor

    return spans


# ── Internals ───────────────────────────────────────────────────────────


def _expand_to_boundary(text: str, target_end: int, boundary: Boundary, *, limit: int) -> int:
    """Push ``target_end`` forward to the next natural boundary.

    The search is bounded by ``limit`` (exclusive). If no boundary is
    found within that window the function returns ``limit`` — a non-
    boundary cut, but a bounded one. Without this the chunker can
    inflate a single chunk to the end of the input on pathological
    text with no paragraph/sentence markers.
    """
    pattern = _PARA_BOUNDARY if boundary == "paragraph" else _SENT_BOUNDARY
    match = pattern.search(text, target_end, limit)
    if match is None:
        return limit
    return match.end()


__all__ = ["Boundary", "ChunkSpan", "chunk_with_boundary"]
