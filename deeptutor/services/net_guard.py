"""Refusing to fetch things a server should not fetch.

Why this is not a regex over the URL
------------------------------------
An SSRF check that inspects the string is defeated by the string: `127.0.0.1`
has a dozen spellings, `127.1` is valid, `0x7f000001` resolves, IPv6 has
`[::1]` and `[::ffff:127.0.0.1]`, and any hostname can resolve to a private
address a second after the check passes. The defence that actually holds is to
resolve the name, check the *addresses*, and then connect to the address that
was checked -- otherwise DNS answers twice and the second answer wins.

This module does the first two. The third is why :func:`resolve_and_check`
returns the resolved addresses: a caller that connects to them itself cannot be
redirected by a second DNS answer, which is the gap between "we validated a URL"
and "we validated what we connected to".

What is blocked
---------------
* loopback, private, link-local, and unique-local addresses, IPv4 and IPv6
* the cloud metadata address (169.254.169.254) and its IPv6 forms, which is the
  single most valuable SSRF target because it hands out credentials
* unresolved names, because a name that does not resolve cannot be validated
* non-HTTP schemes, because file:// and gopher:// are not "fetching a URL"

Redirects are followed *manually* by the caller: an allow-list checked once
before a request is not an allow-list for the redirect that request returns.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlparse

#: Metadata services. Blocked by address rather than by name, because the name
#: is resolved by whoever runs the DNS and the addresses are the thing that
#: actually reachs the credits.
METADATA_ADDRESSES: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS / GCP / Azure / DigitalOcean
        "169.254.170.2",  # ECS task metadata
        "100.100.100.200",  # Alibaba Cloud
        "fd00:ec2::254",  # AWS IMDS over IPv6
    }
)

ALLOWED_SCHEMES = frozenset({"http", "https"})


class BlockedTarget(ValueError):
    """A destination that must not be reached, and why."""

    def __init__(self, rule: str, message: str, *, target: str = "") -> None:
        super().__init__(message)
        self.rule = rule
        self.target = target
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "message": self.message, "target": self.target}


@dataclass(frozen=True)
class Resolution:
    """A validated destination: the host, the port, and the addresses checked."""

    url: str
    host: str
    port: int
    addresses: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "host": self.host,
            "port": self.port,
            "addresses": list(self.addresses),
        }


def _is_forbidden(address: str) -> str:
    """Return the rule that forbids this address, or '' if it is allowed."""
    if address in METADATA_ADDRESSES:
        return "metadata_endpoint"
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return "unparseable_address"

    # An IPv4-mapped IPv6 address (`::ffff:127.0.0.1`) is loopback wearing a
    # different hat; checking only the IPv6 properties would miss it.
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped is not None:
        return _is_forbidden(str(mapped))

    if parsed.is_loopback:
        return "loopback"
    # Checked before is_private: CPython counts 169.254.0.0/16 as private as
    # well, so the broader test would swallow the more specific answer and a
    # link-local refusal would be reported as a generic private range.
    if parsed.is_link_local:
        return "link_local"
    if parsed.is_private:
        return "private_range"
    if parsed.is_reserved:
        return "reserved_range"
    if parsed.is_multicast:
        return "multicast"
    if parsed.is_unspecified:
        return "unspecified"
    return ""


def check_url(url: str, *, allow_hosts: frozenset[str] | None = None) -> Resolution:
    """Validate a URL's destination, resolving it once.

    The returned addresses are the ones that were checked. A caller that then
    connects to ``resolution.addresses`` cannot be tricked by a second DNS
    answer, which is the difference between validating a string and validating a
    connection.
    """
    text = str(url or "").strip()
    if not text:
        raise BlockedTarget("empty_url", "a provider needs a base URL")

    parsed = urlparse(text)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedTarget(
            "forbidden_scheme",
            f"{parsed.scheme or '(none)'} is not fetchable; use http or https",
            target=text,
        )
    host = (parsed.hostname or "").strip()
    if not host:
        raise BlockedTarget("no_host", "the URL has no host", target=text)

    if allow_hosts is not None and host.lower() not in allow_hosts:
        raise BlockedTarget(
            "host_not_allowed",
            f"{host} is not on the allow-list",
            target=text,
        )

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        # A name that does not resolve cannot be validated. Treating it as
        # allowed would mean the check passes now and the connection happens to
        # whatever the name means later.
        raise BlockedTarget(
            "unresolvable", f"{host} does not resolve: {exc}", target=text
        ) from exc

    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        rule = _is_forbidden(address)
        if rule:
            raise BlockedTarget(
                rule,
                f"{host} resolves to {address}, which is {rule.replace('_', ' ')}",
                target=text,
            )
        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise BlockedTarget("unresolvable", f"{host} resolved to nothing", target=text)

    return Resolution(url=text, host=host, port=port, addresses=tuple(addresses))


def check_redirect(location: str, *, original: str, allow_hosts: frozenset[str] | None = None) -> Resolution:
    """Validate a redirect target as strictly as the original.

    A redirect is a second request to a destination nobody vetted. Following it
    because the first hop was allowed is the mistake this function exists to
    make impossible: the original URL is checked already, the new one is not.
    """
    target = str(location or "").strip()
    if not target:
        raise BlockedTarget("empty_redirect", "a redirect with no location")
    lowered = target.lower()
    if lowered.startswith(("http://", "https://")):
        return check_url(target, allow_hosts=allow_hosts)
    # A relative Location is same-origin by definition; it still goes through
    # the address check once resolved, which the caller does by joining it
    # against the original before calling this.
    raise BlockedTarget(
        "relative_redirect",
        "resolve the Location against the original URL, then re-check it",
        target=target,
    )


__all__ = [
    "ALLOWED_SCHEMES",
    "METADATA_ADDRESSES",
    "BlockedTarget",
    "Resolution",
    "check_redirect",
    "check_url",
]
