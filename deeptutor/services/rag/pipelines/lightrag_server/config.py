"""Per-KB connection config and retrieval modes for the LightRAG Server engine.

Unlike the hosted PageIndex engine (one global account key shared by every KB),
each LightRAG Server KB points at its OWN server instance — a standalone LightRAG
server's ``--workspace`` is fixed at startup, so one server instance = one
workspace = one knowledge base. The endpoint (base URL + optional API key) is
therefore stored per-KB in ``kb_config.json`` (the same place the KB's
``search_mode`` lives), exactly like a ``linked`` KB stores its ``external_path``.

This module is the single seam that reads that binding into a typed config; it
holds no global state and imports no HTTP client (the client lives in
``client.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# LightRAG's ``/query`` retrieval modes. ``bypass`` is intentionally omitted: it
# skips retrieval entirely, which is meaningless for a knowledge base. ``mix``
# (knowledge-graph + vector + chunks) is the server's own default and the safest
# general choice, matching the shared per-KB ``search_mode`` default.
SUPPORTED_MODES = ("naive", "local", "global", "hybrid", "mix")
DEFAULT_MODE = "mix"


class LightRagServerNotConfiguredError(RuntimeError):
    """Raised when a KB has no LightRAG server URL bound to it."""


@dataclass(frozen=True)
class LightRagServerConfig:
    """A KB's resolved connection to an external LightRAG server."""

    base_url: str
    api_key: str


def normalize_base_url(url: str | None) -> str:
    """Trim and drop any trailing slash so endpoint paths join cleanly."""
    return (url or "").strip().rstrip("/")


def config_from_entry(entry: dict[str, Any]) -> LightRagServerConfig:
    """Build a :class:`LightRagServerConfig` from a ``kb_config.json`` KB entry.

    Raises :class:`LightRagServerNotConfiguredError` when no ``server_url`` is
    present, so retrieval fails with a clear message instead of an opaque
    connection error.
    """
    base_url = normalize_base_url(entry.get("server_url"))
    if not base_url:
        raise LightRagServerNotConfiguredError(
            "This knowledge base is not connected to a LightRAG server "
            "(no server URL configured). Re-create it with a valid server URL."
        )
    return LightRagServerConfig(base_url=base_url, api_key=str(entry.get("api_key") or "").strip())


__all__ = [
    "SUPPORTED_MODES",
    "DEFAULT_MODE",
    "LightRagServerNotConfiguredError",
    "LightRagServerConfig",
    "normalize_base_url",
    "config_from_entry",
]
