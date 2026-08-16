"""Terminology extraction and translation prompt guardrails."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any

_CODE_AND_MATH = re.compile(
    r"(?s)(```.*?```|~~~.*?~~~|`[^`\n]+`|\$\$.*?\$\$|\$[^$\n]+\$)", re.MULTILINE
)
_API_TOKEN = re.compile(
    r"`([^`\n]{2,120})`|\b([A-Za-z][A-Za-z0-9]*(?:[._][A-Za-z0-9]+)+(?:\(\))?)\b"
)
_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]{2,}(?:[ -][A-Z][a-z]{2,}){0,4}\b")
_ENGLISH_STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "before",
    "being",
    "below",
    "chapter",
    "every",
    "first",
    "great",
    "having",
    "their",
    "there",
    "these",
    "those",
    "through",
    "under",
    "until",
    "where",
    "which",
    "while",
    "whose",
}


def _clean_text(text: str) -> str:
    return _CODE_AND_MATH.sub(" ", text)


def extract_glossary_candidates(
    texts: Iterable[str], *, limit: int = 200
) -> list[dict[str, Any]]:
    """Extract recurring proper nouns, role names, and API identifiers.

    Code and math are excluded from prose extraction, while explicit inline-code
    and dotted/call-shaped identifiers are retained as protected terms.
    """
    corpus = "\n\n".join(text for text in texts if text)
    frequencies: Counter[str] = Counter()
    kinds: dict[str, str] = {}

    for match in _API_TOKEN.finditer(corpus):
        term = (match.group(1) or match.group(2) or "").strip("`")
        if not term or any(char.isspace() for char in term) and "`" not in match.group(0):
            continue
        term = term.strip()
        if 2 <= len(term) <= 120:
            frequencies[term] += 1
            kinds.setdefault(term, "api_identifier")

    prose = _clean_text(corpus)
    for match in _PROPER_NOUN.finditer(prose):
        term = " ".join(match.group(0).split())
        if term.casefold() in _ENGLISH_STOPWORDS or term.istitle() is False:
            continue
        if 3 <= len(term) <= 120:
            frequencies[term] += 1
            kinds.setdefault(term, "proper_noun")

    ranked = sorted(
        frequencies.items(),
        key=lambda item: (
            -item[1],
            0 if kinds.get(item[0]) == "api_identifier" else 1,
            item[0].casefold(),
        ),
    )
    return [
        {
            "term": term,
            "translation": term,
            "kind": kinds.get(term, "proper_noun"),
            "frequency": count,
            "protected": kinds.get(term) == "api_identifier",
            "approved": False,
        }
        for term, count in ranked[: max(1, min(limit, 500))]
        if count >= 2 or kinds.get(term) == "api_identifier"
    ]


def merge_glossary(
    existing: Iterable[Mapping[str, Any]], candidates: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Merge candidates while preserving reviewed mappings and custom entries."""
    merged: dict[str, dict[str, Any]] = {}
    for entry in existing:
        term = str(entry.get("term", "")).strip()
        if not term:
            continue
        current = dict(entry)
        current.update(
            term=term,
            translation=str(entry.get("translation") or term).strip() or term,
            kind=str(entry.get("kind") or "custom"),
            frequency=max(0, int(entry.get("frequency", 0))),
            protected=bool(entry.get("protected")),
            approved=bool(entry.get("approved")),
        )
        merged[term.casefold()] = current

    for candidate in candidates:
        term = str(candidate.get("term", "")).strip()
        if not term:
            continue
        key = term.casefold()
        current = merged.setdefault(
            key,
            {
                "term": term,
                "translation": term,
                "kind": str(candidate.get("kind") or "proper_noun"),
                "frequency": 0,
                "protected": False,
                "approved": False,
            },
        )
        current["frequency"] = max(
            int(current.get("frequency", 0)), int(candidate.get("frequency", 0))
        )
        if not current.get("approved"):
            current["kind"] = str(candidate.get("kind") or current.get("kind"))
            current["protected"] = bool(candidate.get("protected")) or bool(
                current.get("protected")
            )
    return sorted(merged.values(), key=lambda item: item["term"].casefold())


def terms_for_text(
    glossary: Iterable[Mapping[str, Any]], text: str, *, limit: int = 120
) -> list[dict[str, Any]]:
    haystack = text.casefold()
    selected = [
        dict(entry)
        for entry in glossary
        if str(entry.get("term", "")).strip().casefold() in haystack
    ]
    return sorted(
        selected,
        key=lambda item: (
            not bool(item.get("approved")),
            not bool(item.get("protected")),
            -int(item.get("frequency", 0)),
            str(item.get("term", "")).casefold(),
        ),
    )[: max(0, limit)]


def build_translation_guardrail(
    target_language: str, glossary: Sequence[Mapping[str, Any]] | None
) -> str:
    parts = [
        f"Target language: {target_language}",
        "Terminology and formatting rules:",
        "- Use the translation shown for every listed term, exactly and consistently.",
        "- Terms marked protected must remain byte-for-byte unchanged.",
        "- Preserve fenced code blocks, inline code, URLs, HTML tags, and Markdown syntax.",
        "- Preserve inline math ($...$), display math ($$...$$), and LaTeX commands unchanged.",
        "- Translate only natural-language prose and never add commentary.",
    ]
    terms = [
        entry
        for entry in (glossary or [])
        if str(entry.get("term", "")).strip()
        and str(entry.get("translation", "")).strip()
    ]
    if terms:
        lines = ["", "Glossary (source => required translation; protected=yes means unchanged):"]
        for entry in terms:
            marker = "yes" if entry.get("protected") else "no"
            lines.append(
                f"- {entry['term']} => {entry['translation']} [protected={marker}]"
            )
        parts.extend(lines)
    return "\n".join(parts)
