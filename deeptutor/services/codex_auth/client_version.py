"""Read only the official CLI package metadata, never CLI code or OAuth state."""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from .constants import (
    CODEX_GITHUB_LATEST_RELEASE_URL,
    CODEX_GITHUB_MAX_RELEASE_BYTES,
    CODEX_VERSION_TOTAL_TIMEOUT_SECONDS,
    CODEX_MAX_VERSION_BYTES,
    CODEX_NPM_LATEST_URL,
    CODEX_STABLE_VERSION_PATTERN,
    CODEX_VERSION_TIMEOUT_SECONDS,
)



def parse_stable_version(value: str | None) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not re.fullmatch(CODEX_STABLE_VERSION_PATTERN, value):
        return None
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def max_stable_version(*versions: str | None) -> str | None:
    valid = [(parsed, v) for v in versions if (parsed := parse_stable_version(v)) is not None]
    return max(valid)[1] if valid else None


async def _source_version(http: httpx.AsyncClient, source: str) -> str | None:
    url = CODEX_NPM_LATEST_URL if source == "npm" else CODEX_GITHUB_LATEST_RELEASE_URL
    max_bytes = CODEX_MAX_VERSION_BYTES if source == "npm" else CODEX_GITHUB_MAX_RELEASE_BYTES
    headers = {"Accept": "application/json"} if source == "npm" else {
        "Accept": "application/vnd.github+json", "User-Agent": "DeepTutor"
    }
    try:
        async with asyncio.timeout(CODEX_VERSION_TIMEOUT_SECONDS):
            # Standalone requests never inherit client cookies, headers or auth.
            response = await http.send(
                httpx.Request("GET", url, headers=headers),
                auth=None, follow_redirects=False, stream=True,
            )
            try:
                response.raise_for_status()
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > max_bytes:
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        return None
                    content.extend(chunk)
                payload = json.loads(content)
            finally:
                await response.aclose()
        if not isinstance(payload, dict):
            return None
        if source == "npm":
            version = payload.get("version") if payload.get("name") == "@openai/codex" else None
        else:
            if payload.get("draft") is not False or payload.get("prerelease") is not False:
                return None
            tag = payload.get("tag_name")
            version = tag[6:] if isinstance(tag, str) and tag.startswith("rust-v") else None
        return version if parse_stable_version(version) is not None else None
    except (httpx.HTTPError, TimeoutError, ValueError, RecursionError):
        return None


async def discover_client_version(http: httpx.AsyncClient | None = None) -> tuple[str | None, str | None]:
    if http is None:
        async with httpx.AsyncClient(timeout=CODEX_VERSION_TIMEOUT_SECONDS) as client:
            return await discover_client_version(client)
    try:
        async with asyncio.timeout(CODEX_VERSION_TOTAL_TIMEOUT_SECONDS):
            for source in ("npm", "github"):
                version = await _source_version(http, source)
                if version is not None:
                    return version, source
    except TimeoutError:
        pass
    return None, None


async def latest_client_version(http: httpx.AsyncClient | None = None) -> str | None:
    return (await discover_client_version(http))[0]
