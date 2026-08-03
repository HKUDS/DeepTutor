"""Probe a Tencent IMA knowledge base before connecting a KB to it.

Connecting is cheap and reversible, but wrong credentials or a mistyped
knowledge base id should fail loudly at connect time rather than silently at
every later query. One ``get_knowledge_base`` round-trip answers both questions
the UI needs to confirm: are the credentials accepted, and does the id resolve to
a library we can name back to the user?

Always returns an :class:`ImaProbe` (never raises); ``ok`` is the single boolean
the caller gates on, with ``error`` explaining any failure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from .client import ImaAuthError, ImaClient
from .config import ImaConfig


@dataclass
class ImaProbe:
    knowledge_base_id: str
    ok: bool = False
    credentials_ok: bool = False
    knowledge_base_name: Optional[str] = None
    description: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def probe_knowledge_base(
    client_id: str,
    api_key: str,
    knowledge_base_id: str,
    *,
    client_factory=None,
) -> ImaProbe:
    """Check that *knowledge_base_id* is reachable with the given credentials.

    ``client_factory`` (config → client) is an injection seam for tests; in
    production it defaults to a real :class:`ImaClient`.
    """
    client_id = (client_id or "").strip()
    api_key = (api_key or "").strip()
    knowledge_base_id = (knowledge_base_id or "").strip()

    probe = ImaProbe(knowledge_base_id=knowledge_base_id)
    missing = [
        label
        for label, value in (
            ("Client ID", client_id),
            ("API key", api_key),
            ("knowledge base ID", knowledge_base_id),
        )
        if not value
    ]
    if missing:
        probe.error = f"{', '.join(missing)} is required."
        return probe

    config = ImaConfig(
        client_id=client_id,
        api_key=api_key,
        knowledge_base_id=knowledge_base_id,
    )
    client = client_factory(config) if client_factory else ImaClient(config)

    try:
        info = await client.get_knowledge_base()
    except ImaAuthError as exc:
        probe.error = f"IMA rejected these credentials: {exc}"
        return probe
    except Exception as exc:
        probe.error = f"Could not reach Tencent IMA: {exc}"
        return probe

    # The call is credential-gated, so reaching this point means they were
    # accepted — an unknown id just yields no entry.
    probe.credentials_ok = True
    if not info:
        probe.error = (
            "The credentials work, but no knowledge base matches this ID. "
            "Check the ID in IMA and try again."
        )
        return probe

    probe.knowledge_base_name = _opt_str(info.get("name"))
    probe.description = _opt_str(info.get("description"))
    probe.ok = True
    return probe


def _opt_str(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


__all__ = ["ImaProbe", "probe_knowledge_base"]
