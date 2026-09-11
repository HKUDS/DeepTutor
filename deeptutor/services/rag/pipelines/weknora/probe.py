"""Validate a WeKnora endpoint, API key, and knowledge-base binding."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from .client import WeKnoraClient
from .config import WeKnoraConfig, normalize_base_url


@dataclass
class WeKnoraProbe:
    base_url: str
    knowledge_base_id: str
    ok: bool = False
    reachable: bool = False
    credentials_ok: bool = False
    knowledge_base_found: bool = False
    knowledge_base_name: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def probe_weknora(
    server_url: str,
    api_key: str,
    knowledge_base_id: str,
    *,
    client_factory=None,
) -> WeKnoraProbe:
    base_url = normalize_base_url(server_url)
    knowledge_base_id = (knowledge_base_id or "").strip()
    api_key = (api_key or "").strip()
    probe = WeKnoraProbe(base_url=base_url, knowledge_base_id=knowledge_base_id)

    if not base_url or not knowledge_base_id or not api_key:
        probe.error = "Server URL, API key, and knowledge base ID are required."
        return probe

    # WeKnora is administrator-configured and often lives on the deployment's
    # private network, so loopback/LAN remain valid. Link-local, metadata and
    # malformed targets are still forbidden, and the client repeats this check
    # at every retrieval request to narrow DNS-rebinding exposure.
    from deeptutor.services.mcp.network import validate_mcp_url_async

    safe, error = await validate_mcp_url_async(base_url)
    if not safe:
        probe.error = f"Unsafe WeKnora server URL: {error}"
        return probe

    config = WeKnoraConfig(
        base_url=base_url,
        api_key=api_key,
        knowledge_base_id=knowledge_base_id,
    )
    client = client_factory(config) if client_factory else WeKnoraClient(config)
    try:
        knowledge_bases = await client.list_knowledge_bases()
    except Exception as exc:
        probe.error = f"Could not validate the WeKnora connection: {exc}"
        return probe

    probe.reachable = True
    probe.credentials_ok = True
    matches = [item for item in knowledge_bases if str(item.get("id") or "") == knowledge_base_id]
    if not matches:
        probe.error = f"Knowledge base {knowledge_base_id} is not visible to this WeKnora API key."
        return probe

    probe.knowledge_base_found = True
    name = str(matches[0].get("name") or "").strip()
    probe.knowledge_base_name = name or None
    probe.ok = True
    return probe


__all__ = ["WeKnoraProbe", "probe_weknora"]
