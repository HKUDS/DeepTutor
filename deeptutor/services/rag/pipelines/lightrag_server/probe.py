"""Probe an external LightRAG server before connecting a KB to it.

Connecting is cheap and reversible, but a typo'd URL or a wrong API key should
fail loudly at connect time rather than silently at every later query. This
module answers, in one round-trip pair, the questions the UI needs to confirm:

1. **Reachable, and is it actually a LightRAG server?** ``GET /auth-status`` is
   whitelisted on the server, so it answers without credentials; its LightRAG-
   specific keys confirm we're talking to the right kind of server.
2. **Does it require an API key, and is ours accepted?** When auth is enabled we
   validate the key against the read-only ``GET /documents/pipeline_status``.

Always returns a :class:`ServerProbe` (never raises); ``ok`` is the single
boolean the caller gates on, with ``error`` explaining any failure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from .client import LightRagServerClient
from .config import LightRagServerConfig, normalize_base_url


@dataclass
class ServerProbe:
    base_url: str
    ok: bool = False
    reachable: bool = False
    auth_required: bool = False
    auth_ok: bool = False
    core_version: Optional[str] = None
    api_version: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def probe_server(
    server_url: str,
    api_key: str = "",
    *,
    client_factory=None,
) -> ServerProbe:
    """Inspect ``server_url`` for a reachable, authorised LightRAG server.

    ``client_factory`` (config → client) is an injection seam for tests; in
    production it defaults to a real :class:`LightRagServerClient`.
    """
    base_url = normalize_base_url(server_url)
    probe = ServerProbe(base_url=base_url)
    if not base_url:
        probe.error = "Server URL is required."
        return probe
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        probe.error = "Server URL must start with http:// or https://."
        return probe

    config = LightRagServerConfig(base_url=base_url, api_key=(api_key or "").strip())
    client = client_factory(config) if client_factory else LightRagServerClient(config)

    try:
        status = await client.auth_status()
    except Exception as exc:
        probe.error = f"Could not reach a LightRAG server at {base_url}: {exc}"
        return probe

    # ``auth_configured`` is LightRAG-specific; its absence means we reached
    # something that isn't a LightRAG server.
    if "auth_configured" not in status:
        probe.error = f"{base_url} responded but does not look like a LightRAG server."
        return probe

    probe.reachable = True
    probe.core_version = _opt_str(status.get("core_version"))
    probe.api_version = _opt_str(status.get("api_version"))
    probe.auth_required = bool(status.get("auth_configured"))

    if not probe.auth_required:
        # Open server — nothing to validate. A stray key is simply ignored.
        probe.auth_ok = True
        probe.ok = True
        return probe

    try:
        probe.auth_ok = await client.verify_key()
    except Exception as exc:
        probe.error = f"Reached the server but could not validate the API key: {exc}"
        return probe

    if not probe.auth_ok:
        probe.error = (
            "This server requires an API key and the one provided was rejected."
            if api_key
            else "This server requires an API key. Provide one to connect."
        )
        return probe

    probe.ok = True
    return probe


def _opt_str(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


__all__ = ["ServerProbe", "probe_server"]
