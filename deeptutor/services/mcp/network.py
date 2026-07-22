"""
Network guards for remote MCP servers (SSRF protection).

Adapted from nanobot's ``security/network.py``. The posture is calibrated to
DeepTutor's current trust model — every user may configure MCP servers,
including stdio (host subprocess), so the URL guard exists to stop
*accidental* dangerous targets rather than a determined insider:

* loopback and RFC1918 LAN ranges are ALLOWED — self-hosted deployments
  legitimately run MCP servers on the same box or LAN;
* link-local / cloud-metadata ranges (169.254.0.0/16, fe80::/10) and the
  0.0.0.0/8 "this network" range stay BLOCKED — there is no legitimate MCP
  use case for them and 169.254.169.254 is the classic credential-theft
  target.

Tighten ``_BLOCKED_NETWORKS`` when per-user permissions arrive.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("fe80::/10"),  # link-local v6
]


def _normalize_addr(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Normalize IPv6-mapped IPv4 addresses (``::ffff:169.254.x.x``) to IPv4."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _is_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    normalized = _normalize_addr(addr)
    return any(normalized in net for net in _BLOCKED_NETWORKS)


def validate_mcp_url(url: str) -> tuple[bool, str]:
    """Validate a remote MCP server URL: scheme, hostname, resolved IPs.

    Returns ``(ok, error_message)``; ``error_message`` is empty when ok.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, str(exc)

    if parsed.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got {parsed.scheme or 'none'!r}"
    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname"

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_blocked(addr):
            return False, (f"Blocked: {hostname} resolves to link-local/metadata address {addr}")
    return True, ""


__all__ = ["validate_mcp_url"]
