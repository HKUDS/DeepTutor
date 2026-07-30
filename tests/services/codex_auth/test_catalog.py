from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from deeptutor.services.codex_auth.catalog import CodexModelCatalog, parse_models_response
from deeptutor.services.codex_auth.constants import (
    CODEX_CLIENT_VERSION,
    CODEX_MAX_CATALOG_BYTES,
    CODEX_MAX_MODELS,
)
from deeptutor.services.codex_auth.contracts import CodexAuthError, CodexCredentials
from deeptutor.services.codex_auth.storage import CodexCredentialStore

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "models-response.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _credentials(
    *,
    account_id: str = "account-123",
    generation: int = 1,
) -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token="access-secret",
        refresh_token="refresh-secret",
        id_token="id-secret",
        account_id=account_id,
        expires_at=2_000_000_000,
        generation=generation,
    )


class ResponseQueue:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _catalog(
    tmp_path: Path,
    queue: ResponseQueue,
    clock: list[int],
) -> tuple[CodexModelCatalog, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(queue))
    catalog = CodexModelCatalog(
        CodexCredentialStore(tmp_path),
        http=http,
        clock=lambda: clock[0],
    )
    return catalog, http


def test_parse_catalog_keeps_only_picker_visible_raw_models() -> None:
    models = parse_models_response(_fixture())

    assert [model.slug for model in models] == ["gpt-5.6-sol"]
    assert models[0].display_name == "GPT-5.6-Sol"
    assert models[0].supported_reasoning_levels == ("medium", "high")
    assert models[0].supports_reasoning_summary is True


def test_parse_catalog_supports_legacy_summary_field_and_sorts() -> None:
    payload = {
        "models": [
            {
                "slug": "z-last",
                "display_name": "Z",
                "visibility": "list",
                "priority": 2,
                "supported_reasoning_levels": [],
                "supports_reasoning_summaries": True,
            },
            {
                "slug": "a-first",
                "display_name": "A",
                "visibility": "list",
                "priority": 1,
                "supported_reasoning_levels": [],
            },
        ]
    }

    models = parse_models_response(payload)

    assert [model.slug for model in models] == ["a-first", "z-last"]
    assert models[1].supports_reasoning_summary is True


def test_parse_catalog_rejects_more_than_model_limit() -> None:
    models = [
        {
            "slug": f"model-{index}",
            "display_name": f"Model {index}",
            "visibility": "list",
            "priority": index,
            "supported_reasoning_levels": [],
        }
        for index in range(CODEX_MAX_MODELS + 1)
    ]

    with pytest.raises(CodexAuthError) as exc_info:
        parse_models_response({"models": models})

    assert exc_info.value.code == "catalog_too_large"


@pytest.mark.asyncio
async def test_live_catalog_uses_account_headers_and_client_version(tmp_path: Path) -> None:
    queue = ResponseQueue(httpx.Response(200, json=_fixture(), headers={"ETag": '"catalog-v1"'}))
    clock = [1_000]
    catalog, http = _catalog(tmp_path, queue, clock)
    try:
        snapshot = await catalog.get(_credentials(), force=True)
    finally:
        await http.aclose()

    request = queue.requests[0]
    assert request.url.params["client_version"] == CODEX_CLIENT_VERSION
    assert request.headers["chatgpt-account-id"] == "account-123"
    assert request.headers["authorization"] == "Bearer access-secret"
    assert snapshot.source == "live"
    assert snapshot.etag == '"catalog-v1"'


@pytest.mark.asyncio
async def test_fresh_cache_skips_network_and_etag_304_revalidates(tmp_path: Path) -> None:
    queue = ResponseQueue(
        httpx.Response(200, json=_fixture(), headers={"ETag": '"catalog-v1"'}),
        httpx.Response(304),
    )
    clock = [1_000]
    catalog, http = _catalog(tmp_path, queue, clock)
    try:
        live = await catalog.get(_credentials(), force=True)
        clock[0] = 1_100
        fresh = await catalog.get(_credentials(), force=False)
        assert len(queue.requests) == 1
        clock[0] = 1_301
        revalidated = await catalog.get(_credentials(), force=False)
    finally:
        await http.aclose()

    assert live.source == "live"
    assert fresh.source == "fresh-cache"
    assert revalidated.source == "revalidated-cache"
    assert revalidated.fetched_at == 1_301
    assert queue.requests[1].headers["if-none-match"] == '"catalog-v1"'


@pytest.mark.asyncio
async def test_network_failure_uses_only_matching_stale_cache(tmp_path: Path) -> None:
    queue = ResponseQueue(
        httpx.Response(200, json=_fixture()),
        httpx.ConnectError("offline"),
        httpx.ConnectError("offline"),
    )
    clock = [1_000]
    catalog, http = _catalog(tmp_path, queue, clock)
    try:
        await catalog.get(_credentials(), force=True)
        clock[0] = 1_301
        stale = await catalog.get(_credentials(), force=False)
        with pytest.raises(CodexAuthError) as wrong_generation:
            await catalog.get(_credentials(generation=2), force=True)
    finally:
        await http.aclose()

    assert stale.source == "stale-cache"
    assert wrong_generation.value.code == "catalog_unavailable"


@pytest.mark.asyncio
async def test_cache_is_partitioned_by_account(tmp_path: Path) -> None:
    queue = ResponseQueue(
        httpx.Response(200, json=_fixture()),
        httpx.ConnectError("offline"),
    )
    clock = [1_000]
    catalog, http = _catalog(tmp_path, queue, clock)
    try:
        await catalog.get(_credentials(account_id="account-a"), force=True)
        clock[0] = 1_301
        with pytest.raises(CodexAuthError) as exc_info:
            await catalog.get(
                _credentials(account_id="account-b"),
                force=True,
            )
    finally:
        await http.aclose()

    assert exc_info.value.code == "catalog_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [(401, "catalog_unauthorized"), (403, "catalog_forbidden")],
)
async def test_auth_errors_never_use_stale_cache(
    tmp_path: Path,
    status_code: int,
    error_code: str,
) -> None:
    queue = ResponseQueue(
        httpx.Response(200, json=_fixture()),
        httpx.Response(status_code, text="private error"),
    )
    clock = [1_000]
    catalog, http = _catalog(tmp_path, queue, clock)
    try:
        await catalog.get(_credentials(), force=True)
        clock[0] = 1_301
        with pytest.raises(CodexAuthError) as exc_info:
            await catalog.get(_credentials(), force=True)
    finally:
        await http.aclose()

    assert exc_info.value.code == error_code
    assert "private error" not in str(exc_info.value)
    assert CodexCredentialStore(tmp_path).load_catalog_cache() is None


@pytest.mark.asyncio
async def test_catalog_rejects_response_larger_than_eight_mib(tmp_path: Path) -> None:
    queue = ResponseQueue(httpx.Response(200, content=b" " * (CODEX_MAX_CATALOG_BYTES + 1)))
    clock = [1_000]
    catalog, http = _catalog(tmp_path, queue, clock)
    try:
        with pytest.raises(CodexAuthError) as exc_info:
            await catalog.get(_credentials(), force=True)
    finally:
        await http.aclose()

    assert exc_info.value.code == "catalog_too_large"
