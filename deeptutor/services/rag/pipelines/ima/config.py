"""Per-KB connection config for the Tencent IMA engine.

IMA credentials (``client_id`` + ``api_key``, issued at
https://ima.qq.com/agent-interface) identify a *person*, and a knowledge base id
identifies one of that person's libraries. Both are stored per-KB in
``kb_config.json`` — the same place a ``lightrag-server`` KB keeps its endpoint —
rather than as one global account key:

* on a multi-user deployment each user connects their own IMA account, so
  nobody retrieves through somebody else's credentials;
* connecting is self-contained, with no separate global settings surface to fill
  in first.

This module is the single seam that reads that binding into a typed config; it
holds no global state and imports no HTTP client (the client lives in
``client.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# IMA exposes exactly one retrieval call (``search_knowledge``) with no mode
# knob, so a KB bound to this engine has no per-KB search mode to pick. The
# empty tuple keeps the shared provider-mode plumbing happy while telling the
# UI there is nothing to offer.
SUPPORTED_MODES: tuple[str, ...] = ()
DEFAULT_MODE = ""


class ImaNotConfiguredError(RuntimeError):
    """Raised when a KB is missing the credentials or the knowledge base id."""


@dataclass(frozen=True)
class ImaConfig:
    """A KB's resolved connection to one Tencent IMA knowledge base."""

    client_id: str
    api_key: str
    knowledge_base_id: str


def config_from_entry(entry: dict[str, Any]) -> ImaConfig:
    """Build an :class:`ImaConfig` from a ``kb_config.json`` KB entry.

    Raises :class:`ImaNotConfiguredError` when any of the three required fields
    is missing, so retrieval fails with a clear message instead of an opaque
    HTTP error from IMA.
    """
    client_id = str(entry.get("client_id") or "").strip()
    api_key = str(entry.get("api_key") or "").strip()
    knowledge_base_id = str(entry.get("knowledge_base_id") or "").strip()
    missing = [
        label
        for label, value in (
            ("client ID", client_id),
            ("API key", api_key),
            ("knowledge base ID", knowledge_base_id),
        )
        if not value
    ]
    if missing:
        raise ImaNotConfiguredError(
            "This knowledge base is not fully connected to Tencent IMA "
            f"(missing {', '.join(missing)}). Re-create it with complete credentials."
        )
    return ImaConfig(
        client_id=client_id,
        api_key=api_key,
        knowledge_base_id=knowledge_base_id,
    )


__all__ = [
    "SUPPORTED_MODES",
    "DEFAULT_MODE",
    "ImaNotConfiguredError",
    "ImaConfig",
    "config_from_entry",
]
