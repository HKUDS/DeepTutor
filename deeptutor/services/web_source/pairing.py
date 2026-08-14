"""Language inference and source pairing for bilingual documentation sites.

Two sources that share the same host and the same base path (after stripping a
Chinese language prefix like ``/zh-cn``) are automatically paired.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

ZH_PREFIXES = ("zh-cn", "zh-hans", "zh-tw", "zh-hant", "zh")


# -- Language inference -------------------------------------------------

def infer_language(url: str) -> str:
    """Return ``"zh"`` if *url* starts with a Chinese prefix, else ``"en"``."""
    path = (urlparse(url).path or "/").strip("/")
    first = path.split("/")[0] if path else ""
    return "zh" if first.lower() in ZH_PREFIXES else "en"


def language_prefix(url: str) -> str:
    """Return the Chinese language-prefix segment (e.g. ``"zh-cn"``), or ``""``."""
    path = (urlparse(url).path or "/").strip("/")
    first = path.split("/")[0] if path else ""
    return first if first.lower() in ZH_PREFIXES else ""


def normalize_origin(url: str) -> str:
    """Return ``host + path`` with any Chinese language prefix stripped."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = (parsed.path or "/").strip("/")
    segments = [s for s in path.split("/") if s]
    if segments and segments[0].lower() in ZH_PREFIXES:
        segments = segments[1:]
    return host + "/" + "/".join(segments)


# -- File-path pairing --------------------------------------------------

def strip_lang_prefix_from_path(file_path: str, lang_prefix: str) -> str:
    """Remove a language prefix from a raw-file relative path.

    Handles two conventions from the crawler's ``_to_filename``:
    ``zh-cn/explore/book.md`` -> ``explore/book.md``  (nested)
    ``zh-cn.md`` -> ``index.md``  (homepage, flat)
    """
    if not lang_prefix:
        return file_path
    nested = lang_prefix + "/"
    if file_path.startswith(nested):
        return file_path[len(nested):]
    if file_path == lang_prefix + ".md":
        return "index.md"
    return file_path


def pair_file_paths(
    en_files: list[str],
    zh_files: list[str],
    zh_lang_prefix: str,
) -> list[tuple[str, str | None]]:
    """Match EN file paths with their ZH counterparts.

    Returns ``[(en_path, zh_path_or_None), ...]``.
    """
    zh_by_base: dict[str, str] = {}
    for zf in zh_files:
        base = strip_lang_prefix_from_path(zf, zh_lang_prefix)
        zh_by_base[base] = zf

    result: list[tuple[str, str | None]] = []
    for ef in en_files:
        result.append((ef, zh_by_base.get(ef)))
    return result


# -- Source grouping ----------------------------------------------------

@dataclass
class LanguagePair:
    """A pair of sources (one EN, one ZH) sharing the same origin."""

    origin: str
    en_source: dict | None = None
    zh_source: dict | None = None
    zh_lang_prefix: str = ""

    @property
    def is_pair(self) -> bool:
        return self.en_source is not None and self.zh_source is not None


def group_sources_by_origin(sources: list[dict]) -> list[LanguagePair]:
    """Group web sources by their normalized origin."""
    groups: dict[str, LanguagePair] = {}
    unpaired: list[LanguagePair] = []

    for src in sources:
        origin = normalize_origin(src.get("url", ""))
        lang = infer_language(src.get("url", ""))

        if origin not in groups:
            groups[origin] = LanguagePair(origin=origin)
        pair = groups[origin]

        if lang == "zh":
            if pair.zh_source is None:
                pair.zh_source = src
                pair.zh_lang_prefix = language_prefix(src.get("url", ""))
            else:
                unpaired.append(LanguagePair(
                    origin=origin,
                    zh_source=src,
                    zh_lang_prefix=language_prefix(src.get("url", "")),
                ))
        else:
            if pair.en_source is None:
                pair.en_source = src
            else:
                unpaired.append(LanguagePair(origin=origin, en_source=src))

    return list(groups.values()) + unpaired


# -- Pair-key generation ------------------------------------------------

def pair_key_for(origin: str) -> str:
    """Stable filesystem-safe key from an origin string."""
    import re
    key = re.sub(r"[^A-Za-z0-9._-]", "-", origin)
    return key.strip("-") or "default"


@dataclass
class PairStatus:
    """Summary of pairing state for a set of sources."""

    pair_key: str
    origin: str
    status: str  # "bilingual" | "en_only" | "zh_only"
    en_source_id: str = ""
    zh_source_id: str = ""
    en_url: str = ""
    zh_url: str = ""
    paired_pages: int = 0
    en_only_pages: int = 0
    zh_only_pages: int = 0


def compute_pair_status(pair: LanguagePair) -> PairStatus:
    """Compute a serializable pair status from a :class:`LanguagePair`."""
    origin = pair.origin
    status = "bilingual" if pair.is_pair else ("en_only" if pair.en_source else "zh_only")
    return PairStatus(
        pair_key=pair_key_for(origin),
        origin=origin,
        status=status,
        en_source_id=(pair.en_source or {}).get("id", ""),
        zh_source_id=(pair.zh_source or {}).get("id", ""),
        en_url=(pair.en_source or {}).get("url", ""),
        zh_url=(pair.zh_source or {}).get("url", ""),
    )
