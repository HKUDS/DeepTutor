"""Deterministic language selection for book creation."""

from __future__ import annotations

import re
import unicodedata

from deeptutor.services.prompt.language import normalize_language

_AUTO_LANGUAGE = "auto"

# Only phrased requests are treated as explicit language selection. Merely
# mentioning "Japanese history" must not force a Japanese book.
_LANGUAGE_CUES: tuple[tuple[str, str], ...] = (
    ("zh-tw", r"(?:繁體中文|正體中文|traditional\s+chinese)"),
    ("zh", r"(?:用(?:简体中文|中文|汉语)|以(?:中文|汉语)|in\s+chinese|in\s+mandarin)"),
    ("ja", r"(?:日本語で|用(?:日语|日文)|in\s+japanese)"),
    ("ko", r"(?:한국어로|用(?:韩语|韓語)|in\s+korean)"),
    ("ru", r"(?:по-русски|на\s+русском|in\s+russian)"),
    ("es", r"(?:en\s+español|en\s+espanol|in\s+spanish|castellano|用(?:西班牙语|西班牙文))"),
    ("fr", r"(?:en\s+français|en\s+francais|in\s+french|用(?:法语|法文))"),
    ("de", r"(?:auf\s+deutsch|in\s+german|用(?:德语|德文))"),
    ("pt", r"(?:em\s+português|em\s+portugues|in\s+portuguese|用(?:葡萄牙语|葡萄牙文))"),
    ("it", r"(?:in\s+italiano|in\s+italian|用(?:意大利语|意大利文))"),
    ("en", r"(?:in\s+english|英語で|用(?:英语|英文)|en\s+anglais|en\s+inglés)"),
)

_COMPILED_CUES = tuple(
    (language, re.compile(pattern, re.IGNORECASE | re.UNICODE))
    for language, pattern in _LANGUAGE_CUES
)


def _explicit_language(user_intent: str) -> str | None:
    """Return the last explicit language request in the intent."""
    matches: list[tuple[int, str]] = []
    for language, pattern in _COMPILED_CUES:
        for match in pattern.finditer(user_intent):
            matches.append((match.start(), language))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def _script_language(user_intent: str) -> str | None:
    """Infer high-confidence scripts without a language-detection dependency."""
    counts = {"latin": 0, "han": 0, "kana": 0, "hangul": 0, "cyrillic": 0}

    for char in user_intent:
        if not char.isalpha():
            continue
        script = unicodedata.name(char, "").split(" ", 1)[0]
        if script == "LATIN":
            counts["latin"] += 1
        elif script in {"HIRAGANA", "KATAKANA"}:
            counts["kana"] += 1
        elif script == "HANGUL":
            counts["hangul"] += 1
        elif script == "CYRILLIC":
            counts["cyrillic"] += 1
        elif (
            "\u3400" <= char <= "\u4dbf"
            or "\u4e00" <= char <= "\u9fff"
            or "\uf900" <= char <= "\ufaff"
        ):
            counts["han"] += 1

    # Han characters are ambiguous between Chinese and Japanese. Kana resolves
    # that ambiguity; Kanji-only Japanese remains intentionally conservative.
    if counts["kana"]:
        return "ja"
    if counts["hangul"] > max(counts["latin"], counts["han"], counts["cyrillic"]):
        return "ko"
    if counts["cyrillic"] > counts["latin"]:
        return "ru"
    if counts["han"] > max(counts["latin"], counts["hangul"], counts["cyrillic"]):
        return "zh"
    return None


def resolve_book_language(
    *,
    user_intent: str,
    requested_language: str | None = "auto",
    fallback_language: str | None = "en",
) -> str:
    """Resolve a concrete book language before any generation stage runs.

    Explicit selections always win. ``auto`` uses an explicit request cue, then
    a high-confidence script signal, then the caller's fallback (normally the
    interface language).
    """
    requested = normalize_language(requested_language)
    fallback = normalize_language(fallback_language)
    if requested not in {_AUTO_LANGUAGE, "automatic", "detect"}:
        return requested

    intent = user_intent or ""
    return _explicit_language(intent) or _script_language(intent) or fallback


__all__ = ["resolve_book_language"]
