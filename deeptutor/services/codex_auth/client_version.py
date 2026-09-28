"""Read only the official CLI package metadata, never CLI code or OAuth state."""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from .constants import (
    CODEX_MAX_VERSION_BYTES,
    CODEX_NPM_LATEST_URL,
    CODEX_STABLE_VERSION_PATTERN,
    CODEX_VERSION_TIMEOUT_SECONDS,
)


async def latest_client_version(http: httpx.AsyncClient | None = None) -> str | None:
    """Return a validated stable version, or None when discovery is unavailable.

    A separate default client and a standalone request prevent OAuth headers,
    client auth and cookies from being inherited. Redirects are never followed.
    The deadline bounds the entire exchange, including streamed response bytes.
    """
    if http is None:
        async with httpx.AsyncClient(timeout=CODEX_VERSION_TIMEOUT_SECONDS) as client:
            return await latest_client_version(client)
    try:
        async with asyncio.timeout(CODEX_VERSION_TIMEOUT_SECONDS):
            request = httpx.Request(
                "GET", CODEX_NPM_LATEST_URL, headers={"Accept": "application/json"}
            )
            response = await http.send(request, auth=None, follow_redirects=False, stream=True)
            try:
                response.raise_for_status()
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > CODEX_MAX_VERSION_BYTES:
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > CODEX_MAX_VERSION_BYTES:
                        return None
                    content.extend(chunk)
                payload = json.loads(content)
            finally:
                await response.aclose()
        if not isinstance(payload, dict) or payload.get("name") != "@openai/codex":
            return None
        version = payload.get("version")
        if isinstance(version, str) and re.fullmatch(CODEX_STABLE_VERSION_PATTERN, version):
            return version
    except (httpx.HTTPError, TimeoutError, ValueError, RecursionError):
        return None
    return None
