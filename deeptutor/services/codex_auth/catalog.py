"""Account-scoped live model catalog for Codex OAuth."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import hashlib
import ssl
import time
from typing import Any

import httpx

from .client_version import latest_client_version
from .constants import (
    CODEX_CLIENT_VERSION,
    CODEX_FRESH_CACHE_SECONDS,
    CODEX_MAX_CATALOG_BYTES,
    CODEX_MAX_MODELS,
    CODEX_MODELS_URL,
    CODEX_STALE_CACHE_SECONDS,
)
from .contracts import CatalogSnapshot, CodexAuthError, CodexCredentials, CodexModel
from .storage import CodexCredentialStore


def parse_models_response(payload: Mapping[str, Any]) -> tuple[CodexModel, ...]:
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raise CodexAuthError(
            "catalog_invalid",
            "Codex returned an invalid model catalog.",
            502,
        )
    if len(raw_models) > CODEX_MAX_MODELS:
        raise CodexAuthError(
            "catalog_too_large",
            "The Codex model catalog exceeded DeepTutor's safety limit.",
            502,
        )

    models: list[CodexModel] = []
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            raise CodexAuthError(
                "catalog_invalid",
                "Codex returned an invalid model catalog.",
                502,
            )
        if raw_model.get("visibility") != "list":
            continue
        slug = raw_model.get("slug")
        display_name = raw_model.get("display_name")
        if not isinstance(slug, str) or not slug:
            raise CodexAuthError(
                "catalog_invalid",
                "Codex returned an invalid model catalog.",
                502,
            )
        if not isinstance(display_name, str) or not display_name:
            display_name = slug
        priority = raw_model.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int):
            priority = 0

        models.append(
            CodexModel(
                slug=slug,
                display_name=display_name,
                priority=priority,
                visibility="list",
                default_reasoning_level=_optional_string(raw_model.get("default_reasoning_level")),
                supported_reasoning_levels=_reasoning_levels(
                    raw_model.get("supported_reasoning_levels")
                ),
                supports_reasoning_summary=_summary_support(raw_model),
                supports_parallel_tool_calls=(
                    raw_model.get("supports_parallel_tool_calls") is True
                ),
                use_responses_lite=raw_model.get("use_responses_lite") is True,
                context_window=_optional_positive_int(raw_model.get("context_window")),
                max_context_window=_optional_positive_int(raw_model.get("max_context_window")),
            )
        )

    return tuple(sorted(models, key=lambda model: (model.priority, model.slug)))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _reasoning_levels(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    efforts: list[str] = []
    for item in value:
        effort: object
        if isinstance(item, dict):
            effort = item.get("effort")
        else:
            effort = item
        if isinstance(effort, str) and effort and effort not in efforts:
            efforts.append(effort)
    return tuple(efforts)


def _summary_support(raw_model: Mapping[str, Any]) -> bool:
    current = raw_model.get("supports_reasoning_summary_parameter")
    if isinstance(current, bool):
        return current
    return raw_model.get("supports_reasoning_summaries") is True


class CodexModelCatalog:
    def __init__(
        self,
        store: CodexCredentialStore,
        *,
        http: httpx.AsyncClient,
        version_http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._http = http
        self._version_http = version_http
        self._clock = clock

    async def get(
        self,
        credentials: CodexCredentials,
        force: bool,
    ) -> CatalogSnapshot:
        """Read the account catalog; discover CLI metadata only on explicit refresh."""
        now = int(self._clock())
        account_hash = hashlib.sha256(credentials.account_id.encode("utf-8")).hexdigest()
        account_cache = self._matching_cache(account_hash)
        previous_version = (
            account_cache.client_version if account_cache else None
        ) or CODEX_CLIENT_VERSION
        # A credential rotation preserves only the account's successful version,
        # never its previous generation's model data, freshness or validator.
        cache = (
            account_cache
            if account_cache is not None
            and account_cache.models_valid
            and account_cache.generation == credentials.generation
            else None
        )
        client_version = previous_version
        if force:
            client_version = await latest_client_version(self._version_http) or client_version
        if cache is not None and not force and self._age(cache, now) <= CODEX_FRESH_CACHE_SECONDS:
            return replace(cache, source="fresh-cache")

        try:
            return await self._fetch(credentials, cache, now, account_hash, client_version, force)
        except CodexAuthError as exc:
            # Only explicit version rejection or incompatible catalog structure
            # can justify a single retry. Auth, rate limits and transport/security
            # failures must retain their own meaning.
            if client_version == previous_version or exc.code not in {
                "catalog_version_unsupported",
                "catalog_invalid",
            }:
                raise
            return await self._fetch(credentials, cache, now, account_hash, previous_version, force)

    async def _fetch(
        self,
        credentials: CodexCredentials,
        cache: CatalogSnapshot | None,
        now: int,
        account_hash: str,
        client_version: str,
        force: bool,
    ) -> CatalogSnapshot:
        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "Accept": "application/json",
            "chatgpt-account-id": credentials.account_id,
        }
        if cache is not None and cache.client_version == client_version and cache.etag:
            headers["If-None-Match"] = cache.etag

        try:
            response = await self._http.get(
                CODEX_MODELS_URL,
                params={"client_version": client_version},
                headers=headers,
            )
        except httpx.RequestError as exc:
            cause: BaseException | None = exc
            while cause is not None:
                if isinstance(cause, ssl.SSLError):
                    raise CodexAuthError(
                        "catalog_tls_error",
                        "The secure connection to the Codex model catalog failed.",
                        502,
                    ) from exc
                cause = cause.__cause__ or cause.__context__
            return self._stale_or_raise(None if force else cache, now, exc)

        if response.status_code == 401:
            self._store.invalidate_catalog_models(account_hash, generation=credentials.generation)
            raise CodexAuthError(
                "catalog_unauthorized",
                "Codex authentication is no longer authorized.",
                401,
            )
        if response.status_code == 403:
            self._store.invalidate_catalog_models(account_hash, generation=credentials.generation)
            raise CodexAuthError(
                "catalog_forbidden",
                "This Codex account cannot access the model catalog.",
                403,
            )
        if response.status_code == 304:
            if cache is None or cache.client_version != client_version:
                raise CodexAuthError(
                    "catalog_invalid_response",
                    "Codex returned an invalid model catalog response.",
                    502,
                )
            snapshot = replace(cache, source="revalidated-cache", fetched_at=now)
            self._store.commit_catalog_cache(snapshot)
            return snapshot

        if response.status_code == 429:
            raise CodexAuthError(
                "catalog_rate_limited",
                "Codex model catalog requests are rate limited. Try again later.",
                429,
            )
        if response.status_code in {400, 422}:
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            error = error_payload.get("error") if isinstance(error_payload, dict) else None
            if isinstance(error, dict) and error.get("code") in {
                "unsupported_client_version",
                "client_version_unsupported",
            }:
                raise CodexAuthError(
                    "catalog_version_unsupported",
                    "Codex rejected the model catalog client version.",
                    502,
                )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return self._stale_or_raise(None if force else cache, now, exc)

        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > CODEX_MAX_CATALOG_BYTES
        ) or len(response.content) > CODEX_MAX_CATALOG_BYTES:
            raise CodexAuthError(
                "catalog_too_large",
                "The Codex model catalog exceeded DeepTutor's safety limit.",
                502,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CodexAuthError(
                "catalog_invalid_response",
                "Codex returned an invalid model catalog.",
                502,
            ) from exc
        if not isinstance(payload, dict):
            raise CodexAuthError(
                "catalog_invalid",
                "Codex returned an invalid model catalog.",
                502,
            )

        snapshot = CatalogSnapshot(
            models=parse_models_response(payload),
            source="live",
            fetched_at=now,
            etag=response.headers.get("etag"),
            generation=credentials.generation,
            account_hash=account_hash,
            client_version=client_version,
        )
        self._store.commit_catalog_cache(snapshot)
        return snapshot

    async def invalidate(self) -> None:
        self._store.clear_catalog_cache()

    def _matching_cache(
        self,
        account_hash: str,
    ) -> CatalogSnapshot | None:
        try:
            payload = self._store.load_catalog_cache()
            if payload is None:
                return None
            snapshot = CatalogSnapshot.from_dict(payload)
        except CodexAuthError as exc:
            if exc.code != "catalog_corrupt":
                raise
            self._store.clear_catalog_cache()
            return None
        if snapshot.account_hash != account_hash:
            return None
        return snapshot

    @staticmethod
    def _age(snapshot: CatalogSnapshot, now: int) -> int:
        return max(0, now - snapshot.fetched_at)

    def _stale_or_raise(
        self,
        cache: CatalogSnapshot | None,
        now: int,
        cause: Exception,
    ) -> CatalogSnapshot:
        if cache is not None and self._age(cache, now) <= CODEX_STALE_CACHE_SECONDS:
            return replace(cache, source="stale-cache")
        raise CodexAuthError(
            "catalog_unavailable",
            "The Codex model catalog is temporarily unavailable.",
            503,
        ) from cause
