"""Synthetic-address (Fake-IP) and private-network policy for every SSRF guard.

Two knobs, both read at call time, both off by default in the sense that
DeepTutor behaves exactly as before unless an operator opts in.

**1. Declared synthetic ranges** (``network_synthetic_ranges``).

A local TUN/DNS proxy in Fake-IP mode — Clash/Mihomo, Loon, Surge, sing-box —
answers *public* hostnames with synthetic addresses from a private block
(Clash uses ``198.18.0.0/15``, Loon hands out ``fd27:712::/32`` for IPv6) and
then routes the connection by hostname. Every guard in DeepTutor resolves the
hostname first and refuses private answers, so one proxy configuration breaks
all three gates at once: MCP Store installs, ``web_fetch`` and partner media
downloads (#2789, #2739, #2889).

A synthetic answer is byte-for-byte indistinguishable from a real private
destination, so this module does not try to detect one. The operator declares
the ranges their proxy synthesises, in any of:

* ``data/user/settings/system.json`` → ``"network_synthetic_ranges": [...]``
* ``DEEPTUTOR_SSRF_SYNTHETIC_RANGES`` — deployment override, comma separated
* ``DEEPTUTOR_MCP_FAKE_IP_RANGES`` — the MCP-only name introduced by PR #2857,
  still honoured so an existing deployment does not have to migrate

A *hostname* answer inside a declared range is then treated as public. What the
declaration never unlocks:

* **IP-literal URLs.** ``https://[fd27:712::1]/mcp`` or
  ``https://198.18.0.1/`` get no exemption: no hostname was resolved, so no
  proxy could have synthesised that address.
* **Loopback, link-local, cloud-metadata and unassigned answers**, even when a
  declared range covers them (:data:`_ALWAYS_REFUSED`).
* **Mixed answers.** One synthetic record does not launder a genuine ``10.x``
  record returned for the same hostname; the guards still reject on it.

**2. The private-network layer** (``ssrf_protection_enabled``).

Self-hosted deployments behind a proxy, a VPN or a single LAN often *do* want
the app process to reach a private MCP server or an intranet page, and the
per-user/per-call policy above cannot express that. Setting
``"ssrf_protection_enabled": false`` (or ``DEEPTUTOR_SSRF_PROTECTION_ENABLED=0``)
drops only the RFC1918/CGNAT/ULA layer: loopback, link-local, cloud-metadata
and unassigned answers stay refused, so the worst case is reaching a host on
the local network, never the machine itself or its cloud credentials.

That is deliberately *not* a "turn the guard off" switch. A URL the model picks
— or a malicious MCP catalog entry — reaching ``169.254.169.254`` is a
credential-theft primitive, and no tutoring scenario needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SYNTHETIC_RANGES_ENV = "DEEPTUTOR_SSRF_SYNTHETIC_RANGES"
PROTECTION_ENABLED_ENV = "DEEPTUTOR_SSRF_PROTECTION_ENABLED"

#: Names earlier work used for the same idea. Merged, never overriding: a
#: deployment that already set one keeps working after an upgrade.
COMPATIBLE_ENV_NAMES = ("DEEPTUTOR_MCP_FAKE_IP_RANGES",)

#: ``system.json`` keys holding the same values.
SETTING_KEY = "network_synthetic_ranges"
PROTECTION_ENABLED_SETTING_KEY = "ssrf_protection_enabled"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address

#: Answers no proxy legitimately synthesises and no self-hosted deployment
#: needs to reach through the app process: the machine itself, the cloud
#: metadata endpoint, link-local and the unassigned ranges. Refused even with
#: both knobs thrown, so declaring ``fc00::/7`` or disabling the private layer
#: cannot turn ``::1`` or ``fd00:ec2::254`` back on.
_ALWAYS_REFUSED: tuple[Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.100.100.200/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class NetPolicy:
    """One snapshot of the two knobs, read once per validation."""

    protection_enabled: bool
    synthetic: tuple[Network, ...]

    def allows_private(self) -> bool:
        return not self.protection_enabled


def normalize_addr(addr: Address) -> Address:
    """Unmap ``::ffff:127.0.0.1`` to its IPv4 form before comparing."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def is_ip_literal(host: str) -> bool:
    """Whether *host* is an address rather than a name."""
    try:
        ipaddress.ip_address(host.strip().strip("[]"))
    except ValueError:
        return False
    return True


def parse_ranges(values: Any) -> tuple[Network, ...]:
    """Parse CIDRs from a list, a comma/newline separated string, or ``None``.

    Invalid entries are logged and skipped rather than raising: this is read on
    the request path, and a typo in an operator's settings file must not turn
    every fetch into a 500.
    """
    items: list[Any] = []
    stack = list(values) if isinstance(values, (list, tuple, set)) else [values]
    while stack:
        item = stack.pop(0)
        if item is None:
            continue
        if isinstance(item, (list, tuple, set)):
            stack[0:0] = list(item)
            continue
        items.append(item)

    networks: list[Network] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        for chunk in text.replace(";", ",").replace("\n", ",").split(","):
            cidr = chunk.strip()
            if not cidr or cidr in seen:
                continue
            try:
                network = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                logger.warning("Ignoring invalid synthetic network range %r", cidr)
                continue
            seen.add(cidr)
            networks.append(network)
    return tuple(networks)


def parse_bool(value: Any, default: bool) -> bool:
    """Coerce a settings/env value to a bool, keeping *default* when unsure."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    return default


def _settings() -> dict[str, Any]:
    """``system.json`` as effective settings, or ``{}`` when unreadable."""
    try:
        from deeptutor.services.config.runtime_settings import load_system_settings

        return load_system_settings() or {}
    except Exception:  # pragma: no cover - settings must never break a guard
        logger.debug("Cannot read SSRF policy from system settings", exc_info=True)
        return {}


def current_policy() -> NetPolicy:
    """Resolve both knobs from settings, with process env taking precedence."""
    settings = _settings()

    enabled = parse_bool(settings.get(PROTECTION_ENABLED_SETTING_KEY), True)
    if override := os.environ.get(PROTECTION_ENABLED_ENV):
        enabled = parse_bool(override, enabled)

    declared: list[Any] = []
    if configured := settings.get(SETTING_KEY):
        declared.append(configured)
    for name in (SYNTHETIC_RANGES_ENV, *COMPATIBLE_ENV_NAMES):
        if raw := os.environ.get(name):
            declared.append(raw)

    return NetPolicy(protection_enabled=enabled, synthetic=parse_ranges(declared))


def protection_enabled(policy: NetPolicy | None = None) -> bool:
    """Whether the RFC1918/CGNAT/ULA layer is still refused."""
    return (policy or current_policy()).protection_enabled


def synthetic_ranges(policy: NetPolicy | None = None) -> tuple[Network, ...]:
    """Declared synthetic ranges, from settings plus any process override."""
    return (policy or current_policy()).synthetic


def is_always_refused(addr: Address) -> bool:
    """Whether *addr* stays refused however the operator configures anything."""
    normalized = normalize_addr(addr)
    return any(normalized in network for network in _ALWAYS_REFUSED)


def is_synthetic_answer(addr: Address, *, host: str, policy: NetPolicy | None = None) -> bool:
    """Whether *addr* is a proxy answer for *host* and may be treated as public.

    Returning ``True`` means "this address is a declared Fake-IP synthesis for a
    hostname, and exempting it reveals nothing about the machine". It is
    ``False`` for IP-literal hosts, for the always-refused answers above, and
    when no range is declared.
    """
    if is_ip_literal(host):
        return False
    normalized = normalize_addr(addr)
    if is_always_refused(normalized):
        return False
    networks = (policy or current_policy()).synthetic
    return any(normalized in network for network in networks)


__all__ = [
    "COMPATIBLE_ENV_NAMES",
    "NetPolicy",
    "PROTECTION_ENABLED_ENV",
    "PROTECTION_ENABLED_SETTING_KEY",
    "SETTING_KEY",
    "SYNTHETIC_RANGES_ENV",
    "current_policy",
    "is_always_refused",
    "is_ip_literal",
    "is_synthetic_answer",
    "normalize_addr",
    "parse_bool",
    "parse_ranges",
    "protection_enabled",
    "synthetic_ranges",
]
