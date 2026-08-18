"""Deterministic protection for non-prose translation fragments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any, Callable

_PROTECTED_PATTERNS = [
    re.compile(r"(?is)```.*?```"),
    re.compile(r"(?is)~~~.*?~~~"),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"(?s)\$\$.*?\$\$"),
    re.compile(r"\$[^$\n]+\$"),
    re.compile(r"https?://[^\s<>)]+"),
    re.compile(r"</?[A-Za-z][^>\n]*>"),
]


class TranslationProtectionError(ValueError):
    """Raised when a model did not preserve every protected placeholder."""


def _placeholder(index: int) -> str:
    return f"[[DT-KEEP-{index}]]"


def protect_translation_text(
    text: str, glossary: Sequence[Mapping[str, Any]] | None = None
) -> tuple[str, list[str]]:
    """Replace code, math, URLs, HTML, and protected terms with placeholders."""
    fragments: list[str] = []

    def protect(match: re.Match[str]) -> str:
        fragments.append(match.group(0))
        return _placeholder(len(fragments) - 1)

    masked = text
    for pattern in _PROTECTED_PATTERNS:
        masked = pattern.sub(protect, masked)

    terms = sorted(
        {
            str(entry.get("term", ""))
            for entry in (glossary or [])
            if entry.get("protected") and str(entry.get("term", "")).strip()
        },
        key=len,
        reverse=True,
    )
    for term in terms:
        masked = re.sub(re.escape(term), protect, masked)

    return masked, fragments


def restore_translation_text(translated: str, fragments: Sequence[str]) -> str:
    """Restore placeholders in source order and reject missing/duplicate text."""
    found = re.findall(r"\[\[DT-KEEP-(\d+)\]\]", translated)
    expected = [str(index) for index in range(len(fragments))]
    if found != expected:
        raise TranslationProtectionError(
            "Protected code, formula, or markup was changed by the model"
        )

    def restore(match: re.Match[str]) -> str:
        return fragments[int(match.group(1))]

    return re.sub(r"\[\[DT-KEEP-(\d+)\]\]", restore, translated)


def translate_with_protection(
    source: str,
    target_language: str,
    glossary: Sequence[Mapping[str, Any]],
    translate: Callable[..., str],
) -> str:
    """Call a translation callback with one deterministic retry."""
    masked, fragments = protect_translation_text(source, glossary)
    args = (masked, target_language, glossary) if glossary else (masked, target_language)
    raw = translate(*args)
    try:
        return restore_translation_text(raw, fragments)
    except TranslationProtectionError:
        raw = translate(*args)
        return restore_translation_text(raw, fragments)
