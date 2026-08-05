"""Account-scoped live model catalog for Codex OAuth."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import hashlib
import time
from typing import Any

import httpx

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
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._http = http
        self._clock = clock

    async def get(
        self,
        credentials: CodexCredentials,
        force: bool,
    ) -> CatalogSnapshot:
        now = int(self._clock())
        account_hash = hashlib.sha256(credentials.account_id.encode("utf-8")).hexdigest()
        cache = self._matching_cache(credentials, account_hash)
        if cache is not None and not force and self._age(cache, now) <= CODEX_FRESH_CACHE_SECONDS:
            return replace(cache, source="fresh-cache")

        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "Accept": "application/json",
            "chatgpt-account-id": credentials.account_id,
        }
        if cache is not None and cache.etag:
            headers["If-None-Match"] = cache.etag

        try:
            response = await self._http.get(
                CODEX_MODELS_URL,
                params={"client_version": CODEX_CLIENT_VERSION},
                headers=headers,
            )
        except httpx.RequestError as exc:
            return self._stale_or_raise(cache, now, exc)

        if response.status_code == 401:
            await self.invalidate()
            raise CodexAuthError(
                "catalog_unauthorized",
                "Codex authentication is no longer authorized.",
                401,
            )
        if response.status_code == 403:
            await self.invalidate()
            raise CodexAuthError(
                "catalog_forbidden",
                "This Codex account cannot access the model catalog.",
                403,
            )
        if response.status_code == 304:
            if cache is None:
                raise CodexAuthError(
                    "catalog_invalid",
                    "Codex returned an invalid model catalog response.",
                    502,
                )
            snapshot = replace(cache, source="revalidated-cache", fetched_at=now)
            self._store.save_catalog_cache(snapshot.to_dict())
            return snapshot

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return self._stale_or_raise(cache, now, exc)

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
                "catalog_invalid",
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
        )
        self._store.save_catalog_cache(snapshot.to_dict())
        return snapshot

    async def invalidate(self) -> None:
        self._store.clear_catalog_cache()

    def _matching_cache(
        self,
        credentials: CodexCredentials,
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
        if snapshot.generation != credentials.generation:
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
