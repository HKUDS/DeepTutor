"""Bilingual source pairing and language variant alignment for web sources.

Detects language variants (via hreflang links or URL language patterns),
associates variant pages with canonical source pages, and prepares pairing
records for storage and API exposure.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

# Canonical supported language codes and their common regional/script aliases.
_CANONICAL_LANGUAGES: dict[str, str] = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "en-au": "en",
    "en-ca": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-sg": "zh",
    "zh-tw": "zh",
    "zh-hant": "zh",
    "zh-hk": "zh",
    "ja": "ja",
    "ja-jp": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "fr": "fr",
    "fr-fr": "fr",
    "fr-ca": "fr",
    "de": "de",
    "de-de": "de",
    "de-at": "de",
    "de-ch": "de",
    "es": "es",
    "es-es": "es",
    "es-419": "es",
    "es-mx": "es",
    "ru": "ru",
    "ru-ru": "ru",
    "pt": "pt",
    "pt-br": "pt",
    "pt-pt": "pt",
    "it": "it",
    "it-it": "it",
}

_KNOWN_LANG_CODES = frozenset(_CANONICAL_LANGUAGES.keys())

SUPPORTED_LANGUAGE_PAIRS = frozenset(
    {
        frozenset({"en", "zh"}),
        frozenset({"en", "ja"}),
        frozenset({"en", "ko"}),
        frozenset({"en", "fr"}),
        frozenset({"en", "de"}),
        frozenset({"en", "es"}),
        frozenset({"en", "ru"}),
        frozenset({"en", "pt"}),
        frozenset({"en", "it"}),
    }
)


def normalize_language(code: str | None) -> str:
    """Normalize a language tag to its canonical primary language code.

    Examples:
        'zh-CN' -> 'zh'
        'en-US' -> 'en'
        'zh-Hans' -> 'zh'
        'FR' -> 'fr'
        'x-default' -> ''
    """
    if not code:
        return ""
    cleaned = code.strip().lower().replace("_", "-")
    if cleaned in ("x-default", "default"):
        return ""
    if cleaned in _CANONICAL_LANGUAGES:
        return _CANONICAL_LANGUAGES[cleaned]
    primary = cleaned.split("-", 1)[0]
    return _CANONICAL_LANGUAGES.get(primary, primary)


def is_supported_pair(lang_a: str, lang_b: str) -> bool:
    """Check if two languages form a supported bilingual pairing."""
    if not lang_a or not lang_b or lang_a == lang_b:
        return False
    pair = frozenset({lang_a, lang_b})
    if pair in SUPPORTED_LANGUAGE_PAIRS:
        return True
    return "en" in pair or "zh" in pair


def extract_url_language_and_stem(url: str) -> tuple[str, str]:
    """Extract language code (if in URL path) and the language-agnostic stem path.

    Handles leading language segments (/zh/docs/intro -> ("zh", "/docs/intro"))
    and common nested prefixes (/docs/zh/intro -> ("zh", "/docs/intro")).
    """
    parsed = urlparse(url)
    raw_path = parsed.path.rstrip("/")
    if not raw_path:
        return "", "/"

    segments = [s for s in raw_path.split("/") if s]
    if not segments:
        return "", "/"

    first_norm = normalize_language(segments[0])
    if segments[0].lower() in _KNOWN_LANG_CODES or first_norm in SUPPORTED_LANGUAGE_PAIRS:
        stem = "/" + "/".join(segments[1:])
        return first_norm, stem or "/"

    if len(segments) >= 2:
        second_norm = normalize_language(segments[1])
        if segments[1].lower() in _KNOWN_LANG_CODES or second_norm in SUPPORTED_LANGUAGE_PAIRS:
            stem = f"/{segments[0]}" + ("/" + "/".join(segments[2:]) if len(segments) > 2 else "")
            return second_norm, stem or "/"

    return "", raw_path or "/"


def detect_bilingual_pairings(
    pages: list[Any],
    page_file_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Detect bilingual page pairings among crawled pages.

    Uses both explicit hreflang alternate declarations and URL language prefix
    patterns. Returns a deduplicated, deterministically sorted list of pairing
    records.
    """
    if not pages:
        return []

    file_map = page_file_map or {}
    pages_by_url = {page.url: page for page in pages}
    pairings: dict[str, dict[str, Any]] = {}

    # 1. Hreflang alternate links (highest confidence)
    for page in pages:
        p1_lang = (
            normalize_language(getattr(page, "language", ""))
            or extract_url_language_and_stem(page.url)[0]
            or "en"
        )
        alternate_links: dict[str, str] = getattr(page, "alternate_links", {})
        for hreflang, target_url in alternate_links.items():
            if target_url not in pages_by_url or target_url == page.url:
                continue
            target_page = pages_by_url[target_url]
            p2_lang = (
                normalize_language(hreflang)
                or normalize_language(getattr(target_page, "language", ""))
                or extract_url_language_and_stem(target_url)[0]
                or "zh"
            )
            if not is_supported_pair(p1_lang, p2_lang):
                continue

            if p1_lang == "en":
                src, tgt = page, target_page
                s_lang, t_lang = p1_lang, p2_lang
            elif p2_lang == "en":
                src, tgt = target_page, page
                s_lang, t_lang = p2_lang, p1_lang
            elif page.url <= target_page.url:
                src, tgt = page, target_page
                s_lang, t_lang = p1_lang, p2_lang
            else:
                src, tgt = target_page, page
                s_lang, t_lang = p2_lang, p1_lang

            pairing_id = hashlib.sha256(f"{src.url}::{tgt.url}".encode("utf-8")).hexdigest()[:16]
            pairings[pairing_id] = {
                "pairing_id": pairing_id,
                "source_url": src.url,
                "target_url": tgt.url,
                "source_file": file_map.get(src.url, ""),
                "target_file": file_map.get(tgt.url, ""),
                "source_lang": s_lang,
                "target_lang": t_lang,
                "pairing_method": "hreflang",
            }

    # 2. URL language stem pattern matching
    stem_groups: dict[str, list[tuple[Any, str]]] = {}
    for page in pages:
        url_lang, stem = extract_url_language_and_stem(page.url)
        page_lang = normalize_language(getattr(page, "language", "")) or url_lang
        stem_groups.setdefault(stem, []).append((page, page_lang))

    for stem, group in stem_groups.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                p1, l1 = group[i]
                p2, l2 = group[j]

                # If one page is unprefixed and the other has a language tag,
                # infer default 'en' for the unprefixed base documentation page.
                if not l1 and l2 and l2 != "en":
                    l1 = "en"
                elif not l2 and l1 and l1 != "en":
                    l2 = "en"

                if not is_supported_pair(l1, l2):
                    continue

                if l1 == "en":
                    src, tgt = p1, p2
                    s_lang, t_lang = l1, l2
                elif l2 == "en":
                    src, tgt = p2, p1
                    s_lang, t_lang = l2, l1
                elif p1.url <= p2.url:
                    src, tgt = p1, p2
                    s_lang, t_lang = l1, l2
                else:
                    src, tgt = p2, p1
                    s_lang, t_lang = l2, l1

                pairing_id = hashlib.sha256(f"{src.url}::{tgt.url}".encode("utf-8")).hexdigest()[
                    :16
                ]
                if pairing_id not in pairings:
                    pairings[pairing_id] = {
                        "pairing_id": pairing_id,
                        "source_url": src.url,
                        "target_url": tgt.url,
                        "source_file": file_map.get(src.url, ""),
                        "target_file": file_map.get(tgt.url, ""),
                        "source_lang": s_lang,
                        "target_lang": t_lang,
                        "pairing_method": "url_pattern",
                    }

    result = list(pairings.values())
    result.sort(key=lambda item: (item["source_url"], item["target_url"]))
    return result


__all__ = [
    "detect_bilingual_pairings",
    "extract_url_language_and_stem",
    "is_supported_pair",
    "normalize_language",
]
