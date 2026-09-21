"""Per-crawl robots rules and host pacing for documentation sync (#1429)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from fnmatch import translate
import math
import re
import time
from urllib.parse import quote, urljoin, urlsplit

import httpx

from deeptutor.tools.web_fetch import (
    DEFAULT_USER_AGENT,
    MAX_RESPONSE_BYTES,
    _bounded_read,
    _is_disallowed_host,
)

DEFAULT_REQUEST_INTERVAL_S = 0.125
_UNRESERVED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")


def _normalise_path(value: str) -> str:
    # Compare UTF-8 octets while preserving escaped reserved characters.
    value = quote(value, safe="/%:@!$&'()*+,;=-._~?")
    return re.sub(
        r"%([0-9a-fA-F]{2})",
        lambda match: (
            chr(int(match[1], 16)) if chr(int(match[1], 16)) in _UNRESERVED else match[0].upper()
        ),
        value,
    )


@dataclass(frozen=True)
class RobotsPolicy:
    rules: tuple[tuple[str, bool], ...] = ()
    crawl_delay_s: float = 0.0
    available: bool = True

    def permits(self, url: str) -> bool:
        if not self.available:
            return False
        parsed = urlsplit(url)
        path = _normalise_path((parsed.path or "/") + ("?" + parsed.query if parsed.query else ""))
        if parsed.path == "/robots.txt":
            return True
        matches: list[tuple[int, bool]] = []
        for rule, allowed in self.rules:
            anchored = rule.endswith("$")
            pattern = rule[:-1] if anchored else rule
            # fnmatch's atomic wildcard matching avoids exponential regex
            # backtracking on an untrusted rule with many stars. Robots only
            # gives '*' wildcard meaning; brackets and '?' remain literal.
            glob = pattern.replace("[", "[[]").replace("?", "[?]")
            expression = translate(glob + ("" if anchored else "*"))
            if re.match(expression, path):
                matches.append((len(rule.encode("utf-8")), allowed))
        # Longest match wins; Allow wins ties (RFC 9309).
        return max(matches, default=(0, True))[1]


def parse_robots_txt(raw: str) -> RobotsPolicy:
    groups: list[tuple[list[str], list[tuple[str, bool]], list[float]]] = []
    agents: list[str] = []
    rules: list[tuple[str, bool]] = []
    delays: list[float] = []
    has_directive = False
    for line in raw.splitlines():
        key, sep, value = line.split("#", 1)[0].partition(":")
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if has_directive:
                groups.append((agents, rules, delays))
                agents, rules, delays = [], [], []
                has_directive = False
            if value:
                agents.append(value.lower())
        elif agents:
            has_directive = True
            if key in {"allow", "disallow"} and value.startswith("/"):
                rules.append((_normalise_path(value), key == "allow"))
            elif key == "crawl-delay":
                try:
                    delay = float(value)
                except ValueError:
                    continue
                if math.isfinite(delay) and delay >= 0:
                    delays.append(delay)
    groups.append((agents, rules, delays))
    product = DEFAULT_USER_AGENT.split("/", 1)[0].lower()
    selected = [group for group in groups if product in group[0]]
    selected = selected or [group for group in groups if "*" in group[0]]
    return RobotsPolicy(
        rules=tuple(rule for _, rules, _ in selected for rule in rules),
        crawl_delay_s=max((delay for _, _, delays in selected for delay in delays), default=0.0),
    )


class CrawlAccess:
    """Cache by origin; serialize request starts per host, including redirects."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._policies: dict[str, RobotsPolicy] = {}
        self._policy_locks: dict[str, asyncio.Lock] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._intervals: dict[str, float] = {}

    async def _pace(self, url: str, delay: float = 0.0) -> None:
        host = urlsplit(url).hostname or ""
        self._intervals[host] = max(self._intervals.get(host, DEFAULT_REQUEST_INTERVAL_S), delay)
        async with self._host_locks.setdefault(host, asyncio.Lock()):
            last = self._last_request.get(host)
            if last is not None:
                wait = self._intervals[host] - (time.monotonic() - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_request[host] = time.monotonic()

    async def _fetch_policy(self, url: str) -> RobotsPolicy:
        # robots redirects do not recursively request another robots file, but
        # every hop retains the same SSRF checks as page requests.
        for _ in range(6):
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or _is_disallowed_host(parsed.hostname)
            ):
                return RobotsPolicy(available=False)
            await self._pace(url)
            try:
                async with self.client.stream(
                    "GET",
                    url,
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/plain,*/*"},
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location", "").strip()
                        if not location:
                            return RobotsPolicy(available=False)
                        url = urljoin(url, location)
                        continue
                    if response.status_code >= 500 or response.status_code == 429:
                        return RobotsPolicy(available=False)
                    if response.status_code >= 400:
                        return RobotsPolicy()
                    return parse_robots_txt(await _bounded_read(response, MAX_RESPONSE_BYTES))
            except httpx.HTTPError:
                return RobotsPolicy(available=False)
        return RobotsPolicy(available=False)

    async def policy_for(self, url: str) -> RobotsPolicy:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        async with self._policy_locks.setdefault(origin, asyncio.Lock()):
            if origin not in self._policies:
                self._policies[origin] = await self._fetch_policy(origin + "/robots.txt")
        return self._policies[origin]

    async def permits_request(self, url: str) -> bool:
        policy = await self.policy_for(url)
        if not policy.permits(url):
            return False
        await self._pace(url, policy.crawl_delay_s)
        return True
