"""Locator-addressed full-text search over one material.

This is what replaces retrieval inside immersive reading. A material lives in a
few hundred unit files at most, so a linear scan is milliseconds — and unlike a
vector search, **every hit already carries its locator**, which is the whole
point: the model can cite "page 12" because that is literally what it searched.

Matching is deliberately layered, cheapest first, and reports which layer fired
so the model can tell a verbatim hit from a loose one:

1. ``exact`` — the query as written, case-insensitive.
2. ``normalised`` — whitespace collapsed and punctuation-insensitive, so a
   quote copied out of a PDF still matches text that wrapped mid-phrase.
3. ``terms`` — units ranked by how many of the query's terms they contain.
   The fallback that keeps a natural-language question from returning nothing.

Pure functions over ``(locator, text)`` pairs: no store, no I/O, no config.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal, Sequence

from deeptutor.reading.models import SearchHit

MatchMode = Literal["exact", "normalised", "terms"]

DEFAULT_LIMIT = 12
SNIPPET_RADIUS = 140

# Characters that differ between "the same" text in a PDF and in a chat message:
# any whitespace run, and the punctuation families that get transliterated
# (curly vs straight quotes, en/em dashes, CJK vs ASCII commas).
_WS_RUN = re.compile(r"\s+")
_SOFT_PUNCT = re.compile(r"[‘’“”–—\-_'\"`,，、;；:：.。!！?？()（）\[\]【】]")
# ``\w`` is Unicode-aware for str patterns, so this keeps CJK together too.
_TERM_SPLIT = re.compile(r"\W+", re.UNICODE)
# Terms this short carry no signal in the ranking fallback (English stop-ish
# noise and single CJK particles), so they are dropped rather than diluting it.
_MIN_TERM_LEN = 2
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿぀-ヿ]")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Hits for one query, plus which matching layer produced them."""

    hits: tuple[SearchHit, ...]
    mode: MatchMode | None
    truncated: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.hits

    def to_dict(self) -> dict[str, object]:
        return {
            "hits": [hit.to_dict() for hit in self.hits],
            "mode": self.mode,
            "truncated": self.truncated,
        }


def normalise(text: str) -> str:
    """Collapse whitespace and soften punctuation for tolerant comparison."""
    return _WS_RUN.sub(" ", _SOFT_PUNCT.sub("", text or "")).strip().lower()


def terms_of(query: str) -> tuple[str, ...]:
    """Split *query* into ranking terms, dropping noise-length fragments.

    CJK runs have no word separators, so ``\\W+`` alone would yield one giant
    term and the ranking layer would degenerate into exact matching. Runs of
    three or more CJK characters are therefore expanded into overlapping
    bigrams, which is what lets a Chinese query match partially.
    """
    raw = [term for term in _TERM_SPLIT.split((query or "").lower()) if term]
    expanded: list[str] = []
    for term in raw:
        if len(term) >= 3 and _CJK.search(term):
            expanded.extend(term[i : i + 2] for i in range(len(term) - 1))
        elif len(term) >= _MIN_TERM_LEN:
            expanded.append(term)
    # Preserve first-seen order while de-duplicating overlapping bigrams.
    return tuple(dict.fromkeys(expanded))


def search_units(
    units: Iterable[tuple[int, str]],
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> SearchResult:
    """Search *units* for *query*, escalating through the matching layers.

    ``units`` is consumed once, so a generator straight off the store is fine.
    """
    needle = (query or "").strip()
    if not needle:
        return SearchResult(hits=(), mode=None)

    materialised = [(locator, text or "") for locator, text in units]
    bounded = max(1, int(limit))

    for mode in ("exact", "normalised"):
        hits = _literal_hits(materialised, needle, mode=mode, limit=bounded + 1)
        if hits:
            return SearchResult(
                hits=tuple(hits[:bounded]),
                mode=mode,  # type: ignore[arg-type]
                truncated=len(hits) > bounded,
            )

    ranked = _term_hits(materialised, needle, limit=bounded + 1)
    if not ranked:
        return SearchResult(hits=(), mode=None)
    return SearchResult(
        hits=tuple(ranked[:bounded]),
        mode="terms",
        truncated=len(ranked) > bounded,
    )


def locate_quote(text: str, quote: str) -> int:
    """Character offset of *quote* in *text*, or -1.

    Used to verify a model-supplied quote actually appears on the unit it
    claims, before the reader is told to jump there. Falls back to the
    normalised comparison so a quote that lost a line-break still verifies —
    the offset then points at the normalised position, which is close enough
    for "is this real?" but is not used for geometry.
    """
    if not text or not quote:
        return -1
    direct = text.lower().find(quote.lower())
    if direct >= 0:
        return direct
    return normalise(text).find(normalise(quote))


def _literal_hits(
    units: Sequence[tuple[int, str]],
    needle: str,
    *,
    mode: str,
    limit: int,
) -> list[SearchHit]:
    hits: list[SearchHit] = []
    target = needle.lower() if mode == "exact" else normalise(needle)
    if not target:
        return hits
    for locator, text in units:
        haystack = text.lower() if mode == "exact" else normalise(text)
        position = haystack.find(target)
        if position < 0:
            continue
        # Snippet always comes from the ORIGINAL text: a normalised offset does
        # not index the original, so for that layer we anchor on the first term
        # instead of trusting the position.
        anchor = position if mode == "exact" else _first_term_offset(text, needle)
        hits.append(
            SearchHit(
                locator=locator,
                snippet=_snippet(text, anchor, len(needle)),
                offset=max(0, anchor),
                match=needle,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _term_hits(
    units: Sequence[tuple[int, str]],
    needle: str,
    *,
    limit: int,
) -> list[SearchHit]:
    query_terms = terms_of(needle)
    if not query_terms:
        return []
    scored: list[tuple[int, int, SearchHit]] = []
    for locator, text in units:
        lowered = text.lower()
        present = [term for term in query_terms if term in lowered]
        if not present:
            continue
        anchor = min(lowered.find(term) for term in present)
        scored.append(
            (
                len(present),
                -locator,
                SearchHit(
                    locator=locator,
                    snippet=_snippet(text, anchor, len(present[0])),
                    offset=max(0, anchor),
                    match=" ".join(present),
                ),
            )
        )
    # Most terms matched wins; ties resolve to the earlier locator so results
    # read in document order rather than arbitrarily.
    scored.sort(key=lambda row: (-row[0], -row[1]))
    return [hit for _, _, hit in scored[:limit]]


def _first_term_offset(text: str, needle: str) -> int:
    lowered = text.lower()
    for term in terms_of(needle):
        found = lowered.find(term)
        if found >= 0:
            return found
    return 0


def _snippet(text: str, offset: int, match_len: int) -> str:
    """A one-line window around *offset*, with ellipses when clipped."""
    if not text:
        return ""
    start = max(0, offset - SNIPPET_RADIUS)
    end = min(len(text), offset + max(1, match_len) + SNIPPET_RADIUS)
    window = _WS_RUN.sub(" ", text[start:end]).strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{window}{suffix}"


__all__ = [
    "DEFAULT_LIMIT",
    "MatchMode",
    "SearchResult",
    "locate_quote",
    "normalise",
    "search_units",
    "terms_of",
]
