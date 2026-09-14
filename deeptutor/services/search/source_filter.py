"""Reference safety filtering shared by every web-search provider."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import threading
import time
from typing import Any
from urllib.parse import quote, urlparse
import urllib.request

from .types import Citation, SearchResult, WebSearchResponse

_logger = logging.getLogger(__name__)

_ALLOWED_PORTS = frozenset({80, 443})
_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")

# Opt-in educational allowlist (#375). Enabled only when
# ``use_educational_trusted_domains`` is true — never silently replaces an
# empty trusted list.
EDUCATIONAL_TRUSTED_DOMAINS: tuple[str, ...] = (
    "wikipedia.org",
    "wikimedia.org",
    "khanacademy.org",
    "britannica.com",
    "arxiv.org",
    "nih.gov",
    "nasa.gov",
    "edu",
    "ac.uk",
    "gov",
    "scholastic.com",
    "coursera.org",
    "edx.org",
    "mit.edu",
    "stanford.edu",
    "harvard.edu",
    "ox.ac.uk",
    "cam.ac.uk",
)

# Title / snippet / URL-path heuristics. Prefer strong tokens over soft words
# that collide with educational topics (e.g. bare "sex" in sex education).
_UNSAFE_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bporn(?:ography|ographic|hub|tube|o)?\b",
        r"\bxnxx\b",
        r"\bxvideos?\b",
        r"\bonlyfans\b",
        r"\bnsfw\b",
        r"\bxxx\b",
        r"\berotic(?:a)?\b",
        r"\bcamgirl(?:s)?\b",
        r"\bescor(?:t|ts)\b",
        r"\bonline\s+casino\b",
        r"\bgambling\b",
        r"\bbetting\s+odds\b",
        r"\bslot\s+machines?\b",
        r"\bdrug\s+marketplace\b",
        r"\bbuy\s+(?:weed|cocaine|fentanyl)\b",
    )
)

_UNSAFE_URL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"/(?:porn|xxx|sexcam|escort|casino|gambling)(?:/|$)",
        r"\.(?:xxx)(?:/|$)",
    )
)

_MODERATION_URL = "https://api.openai.com/v1/moderations"
_MODERATION_TIMEOUT_S = 8.0

# Google Web Risk Lookup (#375 stage 3). Opt-in via ``use_web_risk`` plus an
# API key; the free tier is the 100k lookups/month the issue pinned its hopes
# on, so results are cached briefly and shared lookups are deduplicated.
_WEB_RISK_URL = "https://webrisk.googleapis.com/v1/uris:search"
_WEB_RISK_TIMEOUT_S = 5.0
_WEB_RISK_THREAT_TYPES = ("MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE")
_WEB_RISK_CACHE_TTL_S = 900.0
_WEB_RISK_CACHE_MAX = 1024
_web_risk_cache: dict[str, tuple[float, bool]] = {}
_web_risk_cache_lock = threading.Lock()


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


def _domains(value: Any) -> tuple[str, ...]:
    """Normalize a YAML domain list into lowercase registry-compatible hosts."""
    rows: list[Any] | tuple[Any, ...]
    if isinstance(value, str):
        rows = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple)):
        rows = value
    else:
        return ()

    normalized: list[str] = []
    for row in rows:
        raw = str(row or "").strip().lower().rstrip(".")
        if raw.startswith("*."):
            raw = raw[1:]
        if not raw:
            continue
        try:
            host = raw.encode("idna").decode("ascii").lstrip(".").rstrip(".")
        except UnicodeError:
            host = raw.lstrip(".").rstrip(".")
        if host and host not in normalized:
            normalized.append(host)
    return tuple(normalized)


def _merge_domains(*groups: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    for group in groups:
        for host in group:
            if host and host not in merged:
                merged.append(host)
    return tuple(merged)


def _matches_domain(host: str, patterns: tuple[str, ...]) -> bool:
    return any(host == pattern or host.endswith(f".{pattern}") for pattern in patterns)


def _rejection_reason(
    url: str,
    *,
    blocked_domains: tuple[str, ...],
    trusted_domains: tuple[str, ...],
) -> tuple[str, str]:
    """Return ``(reason, host)`` for a reference URL that must not be surfaced."""
    candidate = str(url or "").strip()
    if not candidate:
        return "missing_url", ""
    if any(character.isspace() or ord(character) < 0x20 for character in candidate):
        return "malformed_url", ""

    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError:
        return "malformed_url", ""

    if parsed.scheme.lower() not in {"http", "https"}:
        return "unsupported_scheme", ""
    if not parsed.hostname:
        return "missing_hostname", ""

    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return "malformed_hostname", ""

    if parsed.username is not None or parsed.password is not None:
        return "embedded_credentials", host
    if port is not None and port not in _ALLOWED_PORTS:
        return "unsupported_port", host

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return "non_public_address", host
    if address is None and (
        host == "localhost" or not host or "." not in host or host.endswith(_PRIVATE_HOST_SUFFIXES)
    ):
        return "non_public_hostname", host

    if _matches_domain(host, blocked_domains):
        return "blocked_domain", host
    if trusted_domains and not _matches_domain(host, trusted_domains):
        return "untrusted_domain", host
    return "", host


def _content_rejection_reason(*, title: str, snippet: str, url: str) -> str:
    """Heuristic title/snippet/path check for clearly non-educational material."""
    haystack = f"{title}\n{snippet}".strip()
    if haystack:
        for pattern in _UNSAFE_CONTENT_PATTERNS:
            if pattern.search(haystack):
                return "unsafe_content"
    path = ""
    try:
        path = urlparse(str(url or "")).path or ""
    except ValueError:
        path = str(url or "")
    combined = f"{path}\n{url}"
    for pattern in _UNSAFE_URL_PATH_PATTERNS:
        if pattern.search(combined):
            return "unsafe_content"
    return ""


def _moderation_rejections(
    texts: list[str],
    *,
    api_key: str,
    request_moderation: Any | None = None,
) -> dict[str, bool]:
    """Return batched Moderation decisions keyed by the submitted text.

    Fail open on transport/API errors so a Moderation outage does not blank
    every web-search turn — heuristics already ran.
    """
    payloads = list(dict.fromkeys(text.strip()[:4000] for text in texts if text.strip()))
    if not payloads or not api_key:
        return {}
    requester = request_moderation or _request_openai_moderation
    try:
        flagged = requester(payloads, api_key=api_key)
        if not isinstance(flagged, (list, tuple)) or len(flagged) != len(payloads):
            raise ValueError("Moderation returned an unexpected result count")
    except Exception as exc:  # noqa: BLE001 — network / JSON / provider quirks
        _logger.warning("OpenAI Moderation skipped after error: %s", exc)
        return {}
    return {text: bool(decision) for text, decision in zip(payloads, flagged, strict=True)}


def _request_openai_moderation(texts: list[str], *, api_key: str) -> list[bool]:
    body = json.dumps({"input": texts}).encode("utf-8")
    request = urllib.request.Request(
        _MODERATION_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DeepTutor-source-filter/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_MODERATION_TIMEOUT_S) as response:  # nosec B310 - hardcoded https constant URL
        raw = json.loads(response.read().decode("utf-8"))
    results = raw.get("results") if isinstance(raw, dict) else None
    if not isinstance(results, list) or len(results) != len(texts):
        raise ValueError("Moderation returned an unexpected result count")
    return [bool(isinstance(result, dict) and result.get("flagged")) for result in results]


def _request_web_risk(url: str, *, api_key: str) -> bool:
    """Return True when the Web Risk Lookup API flags ``url`` as a threat."""
    parts = [f"threatTypes={threat}" for threat in _WEB_RISK_THREAT_TYPES]
    parts.append(f"uri={quote(url, safe='')}")
    parts.append(f"key={quote(api_key, safe='')}")
    request = urllib.request.Request(
        f"{_WEB_RISK_URL}?{'&'.join(parts)}",
        headers={"User-Agent": "DeepTutor-source-filter/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=_WEB_RISK_TIMEOUT_S) as response:  # nosec B310 - hardcoded https constant URL
        raw = json.loads(response.read().decode("utf-8"))
    threat = raw.get("threat") if isinstance(raw, dict) else None
    return bool(isinstance(threat, dict) and threat)


def _web_risk_rejections(
    urls: list[str],
    *,
    api_key: str,
    request_web_risk: Any | None = None,
) -> set[str]:
    """Return the subset of ``urls`` flagged by Web Risk.

    Fail open on transport/API errors so an outage or exhausted quota never
    blanks every web-search turn — heuristics and Moderation already ran.
    """
    unique = list(dict.fromkeys(url for url in urls if url))
    if not unique or not api_key:
        return set()
    requester = request_web_risk or _request_web_risk
    flagged: set[str] = set()
    now = time.monotonic()
    pending: list[str] = []
    with _web_risk_cache_lock:
        for url in unique:
            entry = _web_risk_cache.get(url)
            if entry is not None and now - entry[0] < _WEB_RISK_CACHE_TTL_S:
                if entry[1]:
                    flagged.add(url)
            else:
                pending.append(url)
    for url in pending:
        try:
            is_flagged = bool(requester(url, api_key=api_key))
        except Exception as exc:  # noqa: BLE001 — network / JSON / quota quirks
            _logger.warning("Web Risk lookup skipped after error: %s", exc)
            continue
        with _web_risk_cache_lock:
            if len(_web_risk_cache) >= _WEB_RISK_CACHE_MAX:
                for stale in list(_web_risk_cache)[: len(_web_risk_cache) // 2]:
                    _web_risk_cache.pop(stale, None)
            _web_risk_cache[url] = (time.monotonic(), is_flagged)
        if is_flagged:
            flagged.add(url)
    return flagged


def _reference_text(*, title: str = "", snippet: str = "", content: str = "") -> str:
    parts = [str(title or "").strip(), str(snippet or "").strip(), str(content or "").strip()]
    return "\n".join(part for part in parts if part)


def filter_web_search_response(
    response: WebSearchResponse,
    *,
    enabled: bool = True,
    blocked_domains: Any = None,
    trusted_domains: Any = None,
    content_filtering: bool = True,
    use_educational_trusted_domains: bool = False,
    use_moderation: bool = False,
    moderation_api_key: str | None = None,
    request_moderation: Any | None = None,
    use_web_risk: bool = False,
    web_risk_api_key: str | None = None,
    request_web_risk: Any | None = None,
) -> WebSearchResponse:
    """Drop unsafe or disallowed references from a provider response.

    When citations are removed, the retained ones are renumbered ``1..k``:
    the provider prose citing the old labels is discarded (the caller rebuilds
    the answer from the retained raw results, whose markers are positional
    ``[i]``), so a contiguous reference list is strictly more truthful than
    keeping stale ids that point at dropped URLs. Removals that leave all
    citations intact keep every label unchanged — the prose still cites them.

    Stages (in order):
    1. URL hygiene / domain policy (existing)
    2. Title + snippet heuristics (``content_filtering``, on by default)
    3. Optional OpenAI Moderation when ``use_moderation`` and a key are set
    4. Optional Google Web Risk Lookup when ``use_web_risk`` and a key are set
    """
    if not enabled:
        return response

    blocked = _domains(blocked_domains)
    trusted = _domains(trusted_domains)
    if use_educational_trusted_domains:
        trusted = _merge_domains(trusted, EDUCATIONAL_TRUSTED_DOMAINS)

    moderation_key = str(moderation_api_key or "").strip()
    moderation_active = bool(use_moderation and moderation_key)
    web_risk_key = str(web_risk_api_key or "").strip()
    web_risk_active = bool(use_web_risk and web_risk_key)

    citation_rows: list[list[Any]] = []
    result_rows: list[list[Any]] = []

    for citation in response.citations:
        reason, host = _rejection_reason(
            citation.url,
            blocked_domains=blocked,
            trusted_domains=trusted,
        )
        if not reason and content_filtering:
            reason = _content_rejection_reason(
                title=citation.title,
                snippet="\n".join(part for part in (citation.snippet, citation.content) if part),
                url=citation.url,
            )
        moderation_text = (
            _reference_text(
                title=citation.title,
                snippet=citation.snippet,
                content=citation.content,
            )[:4000]
            if not reason and moderation_active
            else ""
        )
        citation_rows.append([citation, reason, host, moderation_text])

    for result in response.search_results:
        reason, host = _rejection_reason(
            result.url,
            blocked_domains=blocked,
            trusted_domains=trusted,
        )
        if not reason and content_filtering:
            reason = _content_rejection_reason(
                title=result.title,
                snippet="\n".join(part for part in (result.snippet, result.content) if part),
                url=result.url,
            )
        moderation_text = (
            _reference_text(
                title=result.title,
                snippet=result.snippet,
                content=result.content,
            )[:4000]
            if not reason and moderation_active
            else ""
        )
        result_rows.append([result, reason, host, moderation_text])

    moderation_decisions = _moderation_rejections(
        [row[3] for row in (*citation_rows, *result_rows) if row[3]],
        api_key=moderation_key,
        request_moderation=request_moderation,
    )

    for row in (*citation_rows, *result_rows):
        if not row[1] and moderation_decisions.get(row[3], False):
            row[1] = "moderation_flagged"

    web_risk_flagged: set[str] = set()
    if web_risk_active:
        # Only look up URLs that survived every earlier stage — moderation-
        # flagged or heuristic-rejected rows must not burn lookup quota.
        web_risk_flagged = _web_risk_rejections(
            [row[0].url for row in (*citation_rows, *result_rows) if not row[1]],
            api_key=web_risk_key,
            request_web_risk=request_web_risk,
        )

    kept_citations: list[Citation] = []
    kept_results: list[SearchResult] = []
    removed_citations = 0
    removed_results = 0
    answer_invalidated = False
    rejected_hosts: list[str] = []
    rejected_reasons: list[str] = []

    def _record_reason(reason: str, host: str = "") -> None:
        if reason and reason not in rejected_reasons:
            rejected_reasons.append(reason)
        if host and host not in rejected_hosts:
            rejected_hosts.append(host)

    for row in citation_rows:
        citation, reason, host = row[0], row[1], row[2]
        if not reason and citation.url in web_risk_flagged:
            reason = "web_risk_threat"
        if reason:
            removed_citations += 1
            _record_reason(reason, host)
        else:
            kept_citations.append(citation)

    for row in result_rows:
        result, reason, host = row[0], row[1], row[2]
        if not reason and result.url in web_risk_flagged:
            reason = "web_risk_threat"
        if reason:
            removed_results += 1
            _record_reason(reason, host)
        else:
            kept_results.append(result)

    policy_meta = {
        "removed_citations": removed_citations,
        "removed_search_results": removed_results,
        "rejected_hosts": rejected_hosts,
        "rejected_reasons": rejected_reasons,
        "answer_invalidated": answer_invalidated,
        "content_filtering": content_filtering,
        "moderation_enabled": moderation_active,
        "web_risk_enabled": web_risk_active,
        "educational_trusted_domains": use_educational_trusted_domains,
    }

    if not removed_citations and not removed_results:
        # Still record policy flags so callers / Settings can introspect.
        response.metadata["source_filter"] = policy_meta
        return response

    if removed_citations and response.answer.strip():
        # Provider-authored prose is indivisible: even if it cites only one of
        # the retained labels explicitly, it may have synthesized claims from
        # every returned source. The caller will rebuild an answer solely from
        # the retained raw results.
        response.answer = ""
        answer_invalidated = True
        policy_meta["answer_invalidated"] = True

    if removed_citations:
        # The prose citing the old labels is gone, so renumber the retained
        # citations to match the positional [i] markers the consolidator
        # writes when it rebuilds the answer from raw results.
        for index, citation in enumerate(kept_citations, 1):
            citation.id = index
            citation.reference = f"[{index}]"
        policy_meta["citations_renumbered"] = True

    response.citations = kept_citations
    response.search_results = kept_results
    response.metadata["source_filter"] = policy_meta
    return response


def resolve_moderation_api_key() -> str:
    """Pick a Moderation bearer token from the process environment."""
    for name in ("OPENAI_API_KEY", "DEEPTUTOR_OPENAI_API_KEY"):
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def resolve_web_risk_api_key() -> str:
    """Pick a Web Risk API key from the process environment."""
    for name in ("GOOGLE_WEB_RISK_API_KEY", "WEB_RISK_API_KEY"):
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def settings_from_config(config: Any) -> dict[str, Any]:
    """Read the optional ``tools.web_search.source_filtering`` config section."""
    raw = config.get("source_filtering", {}) if isinstance(config, dict) else {}
    settings = raw if isinstance(raw, dict) else {}
    use_moderation = _as_bool(settings.get("use_moderation"), False)
    moderation_key = resolve_moderation_api_key()
    use_web_risk = _as_bool(settings.get("use_web_risk"), False)
    web_risk_key = resolve_web_risk_api_key()
    return {
        "enabled": _as_bool(settings.get("enabled"), True),
        "blocked_domains": _domains(settings.get("blocked_domains")),
        "trusted_domains": _domains(settings.get("trusted_domains")),
        "content_filtering": _as_bool(settings.get("content_filtering"), True),
        "use_educational_trusted_domains": _as_bool(
            settings.get("use_educational_trusted_domains"),
            False,
        ),
        "use_moderation": use_moderation,
        "moderation_api_key": moderation_key if use_moderation else "",
        "use_web_risk": use_web_risk,
        "web_risk_api_key": web_risk_key if use_web_risk else "",
    }


__all__ = [
    "EDUCATIONAL_TRUSTED_DOMAINS",
    "filter_web_search_response",
    "resolve_moderation_api_key",
    "resolve_web_risk_api_key",
    "settings_from_config",
]
