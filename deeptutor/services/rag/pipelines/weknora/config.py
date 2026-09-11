"""Per-KB connection configuration for Tencent WeKnora."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class WeKnoraNotConfiguredError(RuntimeError):
    """Raised when a KB lacks the fields needed to reach WeKnora."""


@dataclass(frozen=True)
class WeKnoraConfig:
    base_url: str
    api_key: str
    knowledge_base_id: str


def normalize_base_url(url: str | None) -> str:
    normalized = (url or "").strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    return normalized


def config_from_entry(entry: dict[str, Any]) -> WeKnoraConfig:
    base_url = normalize_base_url(entry.get("server_url"))
    api_key = str(entry.get("api_key") or "").strip()
    knowledge_base_id = str(entry.get("knowledge_base_id") or "").strip()
    if not base_url or not knowledge_base_id:
        raise WeKnoraNotConfiguredError(
            "This knowledge base is not connected to WeKnora "
            "(server URL and knowledge base ID are required)."
        )
    if not api_key:
        raise WeKnoraNotConfiguredError("A WeKnora API key is required for retrieval.")
    return WeKnoraConfig(
        base_url=base_url,
        api_key=api_key,
        knowledge_base_id=knowledge_base_id,
    )


__all__ = [
    "WeKnoraConfig",
    "WeKnoraNotConfiguredError",
    "config_from_entry",
    "normalize_base_url",
]
