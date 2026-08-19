"""Shaping IMA search results into the grounded context the ``rag`` tool expects.

IMA answers a search with one *highlight snippet* per matched item — often a
single sentence, and nothing at all when the match was on the title. Handing
those straight to the model is what made a connected IMA library feel thin
compared to an indexed KB, whose chunks are whole passages.

So retrieval has two stages, and this module owns the policy for the second:

1. map matched documents into DeepTutor's ``sources`` shape;
2. decide which of them are worth spending a full-text fetch on
   (:func:`hydration_targets`) — items with *no* snippet first, then items whose
   snippet is too thin to reason from, best-ranked first, bounded by a budget so
   one search cannot turn into a dozen downloads.

Kept separate from :mod:`.pipeline` (which orchestrates the calls) and
:mod:`.client` (which makes them) so the retrieval policy can be reasoned about
and tested without a transport.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .models import ImaDocument

# A snippet shorter than this is treated as a hint that a document matched, not
# as usable evidence, so it is a candidate for full-text hydration.
MIN_USEFUL_SNIPPET_CHARS = 240

# How many documents one retrieval may fetch in full. Bounds both the network
# cost and the prompt footprint even when ``top_k`` is large.
DEFAULT_HYDRATION_BUDGET = 4

# Per-document character cap for hydrated full text.
MAX_FULLTEXT_CHARS = 12_000


def documents_to_sources(documents: Iterable[ImaDocument]) -> list[dict[str, Any]]:
    """Map matched IMA documents into DeepTutor's ``sources`` shape.

    Items whose match was on the title alone carry no snippet and are still
    listed, so the model can see the document exists even before (or without)
    hydration.
    """
    sources: list[dict[str, Any]] = []
    for document in documents:
        title = document.title or document.media_id
        if not title:
            continue
        sources.append(
            {
                "title": title,
                "content": document.highlight,
                "source": title,
                "chunk_id": document.media_id,
            }
        )
    return sources


def hydration_targets(
    sources: Sequence[dict[str, Any]],
    *,
    budget: int = DEFAULT_HYDRATION_BUDGET,
    min_chars: int = MIN_USEFUL_SNIPPET_CHARS,
) -> list[int]:
    """Indices of the sources worth fetching in full, in priority order.

    Snippet-less matches come first (they carry no evidence at all), then thin
    snippets in rank order. Sources without an item id cannot be fetched and are
    never returned.
    """
    if budget <= 0:
        return []
    empty: list[int] = []
    thin: list[int] = []
    for index, source in enumerate(sources):
        if not source.get("chunk_id"):
            continue
        content = str(source.get("content") or "").strip()
        if not content:
            empty.append(index)
        elif len(content) < min_chars:
            thin.append(index)
    return (empty + thin)[:budget]


def render_context(sources: Sequence[dict[str, Any]]) -> str:
    """Flatten retrieved snippets into the grounded context block."""
    blocks = [
        f"[{index}] {source.get('title') or ''}\n{source.get('content') or ''}".rstrip()
        for index, source in enumerate(sources, start=1)
    ]
    return "\n\n".join(blocks)


__all__ = [
    "DEFAULT_HYDRATION_BUDGET",
    "MAX_FULLTEXT_CHARS",
    "MIN_USEFUL_SNIPPET_CHARS",
    "documents_to_sources",
    "hydration_targets",
    "render_context",
]
