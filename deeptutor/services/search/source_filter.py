"""Reference safety filtering shared by every web-search provider."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

from .types import Citation, SearchResult, WebSearchResponse

_ALLOWED_PORTS = frozenset({80, 443})
_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")


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


def filter_web_search_response(
    response: WebSearchResponse,
    *,
    enabled: bool = True,
    blocked_domains: Any = None,
    trusted_domains: Any = None,
) -> WebSearchResponse:
    """Drop unsafe or disallowed references from a provider response.

    Citation ids and reference labels stay unchanged when an item is removed.
    Provider-authored answers already cite those labels, so renumbering here
    would turn a harmless gap into incorrect citations.
    """
    if not enabled:
        return response

    blocked = _domains(blocked_domains)
    trusted = _domains(trusted_domains)
    kept_citations: list[Citation] = []
    kept_results: list[SearchResult] = []
    removed_citations = 0
    removed_results = 0
    answer_invalidated = False
    rejected_hosts: list[str] = []

    for citation in response.citations:
        reason, host = _rejection_reason(
            citation.url,
            blocked_domains=blocked,
            trusted_domains=trusted,
        )
        if reason:
            removed_citations += 1
            if host and host not in rejected_hosts:
                rejected_hosts.append(host)
        else:
            kept_citations.append(citation)

    for result in response.search_results:
        reason, host = _rejection_reason(
            result.url,
            blocked_domains=blocked,
            trusted_domains=trusted,
        )
        if reason:
            removed_results += 1
            if host and host not in rejected_hosts:
                rejected_hosts.append(host)
        else:
            kept_results.append(result)

    if not removed_citations and not removed_results:
        return response

    if removed_citations and response.answer.strip():
        # Provider-authored prose is indivisible: even if it cites only one of
        # the retained labels explicitly, it may have synthesized claims from
        # every returned source. The caller will rebuild an answer solely from
        # the retained raw results.
        response.answer = ""
        answer_invalidated = True

    response.citations = kept_citations
    response.search_results = kept_results
    response.metadata["source_filter"] = {
        "removed_citations": removed_citations,
        "removed_search_results": removed_results,
        "rejected_hosts": rejected_hosts,
        "answer_invalidated": answer_invalidated,
    }
    return response


def settings_from_config(config: Any) -> dict[str, Any]:
    """Read the optional ``tools.web_search.source_filtering`` config section."""
    raw = config.get("source_filtering", {}) if isinstance(config, dict) else {}
    settings = raw if isinstance(raw, dict) else {}
    return {
        "enabled": _as_bool(settings.get("enabled"), True),
        "blocked_domains": _domains(settings.get("blocked_domains")),
        "trusted_domains": _domains(settings.get("trusted_domains")),
    }


__all__ = ["filter_web_search_response", "settings_from_config"]
