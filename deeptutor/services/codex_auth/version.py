"""Metadata-only discovery of the stable Codex npm client version."""

from __future__ import annotations

from collections.abc import Callable
import json
from re import fullmatch
from typing import Any

import httpx

from .constants import (
    CODEX_MAX_VERSION_BYTES,
    CODEX_MAX_VERSION_LENGTH,
    CODEX_NPM_METADATA_URL,
    CODEX_VERSION_TIMEOUT_SECONDS,
)
from .contracts import CodexAuthError

_SEMVER = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"


def validate_stable_version(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > CODEX_MAX_VERSION_LENGTH
        or fullmatch(_SEMVER, value) is None
    ):
        raise CodexAuthError(
            "client_version_invalid",
            "Codex published an invalid client version.",
            502,
        )
    return value


class CodexClientVersionDiscovery:
    """Fetch one bounded package-metadata document per explicit refresh.

    Discovery intentionally creates a private HTTP client. The OAuth and
    catalog clients may carry authorization state, and package metadata must
    never inherit it.
    """

    def __init__(
        self,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._client_factory = client_factory or self._default_client

    @staticmethod
    def _default_client() -> httpx.AsyncClient:
        timeout = httpx.Timeout(CODEX_VERSION_TIMEOUT_SECONDS)
        return httpx.AsyncClient(follow_redirects=False, timeout=timeout)

    async def discover(self) -> str:
        try:
            async with self._client_factory() as http:
                async with http.stream(
                    "GET",
                    CODEX_NPM_METADATA_URL,
                    headers={"Accept": "application/vnd.npm.install-v1+json"},
                ) as response:
                    if response.is_redirect:
                        raise CodexAuthError(
                            "client_version_redirect",
                            "Codex version discovery was redirected.",
                            502,
                        )
                    if response.status_code == 429:
                        raise CodexAuthError(
                            "client_version_rate_limited",
                            "Codex version discovery is temporarily rate limited.",
                            429,
                        )
                    if response.status_code in {401, 403}:
                        raise CodexAuthError(
                            "client_version_forbidden",
                            "Codex version metadata is not available.",
                            502,
                        )
                    response.raise_for_status()
                    payload = await self._bounded_json(response)
        except httpx.TimeoutException as exc:
            raise CodexAuthError(
                "client_version_timeout",
                "Codex version discovery timed out.",
                504,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise CodexAuthError(
                "client_version_unavailable",
                "Codex version metadata is temporarily unavailable.",
                503,
            ) from exc
        except httpx.RequestError as exc:
            raise CodexAuthError(
                "client_version_unavailable",
                "Codex version metadata is temporarily unavailable.",
                503,
            ) from exc
        return self._version_from_metadata(payload)

    @staticmethod
    async def _bounded_json(response: httpx.Response) -> Any:
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > CODEX_MAX_VERSION_BYTES:
            raise CodexAuthError(
                "client_version_too_large",
                "Codex version metadata exceeded DeepTutor's safety limit.",
                502,
            )
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > CODEX_MAX_VERSION_BYTES:
                raise CodexAuthError(
                    "client_version_too_large",
                    "Codex version metadata exceeded DeepTutor's safety limit.",
                    502,
                )
            chunks.append(chunk)
        try:
            return json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexAuthError(
                "client_version_invalid",
                "Codex returned invalid version metadata.",
                502,
            ) from exc

    @staticmethod
    def _version_from_metadata(payload: object) -> str:
        if not isinstance(payload, dict):
            raise CodexAuthError(
                "client_version_invalid",
                "Codex returned invalid version metadata.",
                502,
            )
        return validate_stable_version(payload.get("version"))
