from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import sys
from typing import Any

import httpx
import pytest

from deeptutor.services.codex_auth.catalog import CodexModelCatalog, parse_models_response
from deeptutor.services.codex_auth.constants import (
    CODEX_CLIENT_VERSION,
    CODEX_MAX_CATALOG_BYTES,
    CODEX_MAX_MODELS,
)
from deeptutor.services.codex_auth.contracts import (
    CatalogSnapshot,
    CodexAuthError,
    CodexCredentials,
)
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


@pytest.fixture(autouse=True)
def _persist_initial_credentials(tmp_path: Path) -> None:
    """Catalog publication, like production, requires committed credentials."""
    CodexCredentialStore(tmp_path).commit_credentials(_credentials(), expected_generation=0)


class ResponseQueue:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(503)
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
        version_http=http,
        clock=lambda: clock[0],
    )
    return catalog, http


def test_parse_catalog_keeps_only_picker_visible_raw_models() -> None:
    models = parse_models_response(_fixture())

    assert [model.slug for model in models] == ["gpt-5.6-sol"]
    assert models[0].display_name == "GPT-5.6-Sol"
    assert models[0].context_window == 272_000
    assert models[0].max_context_window == 272_000
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
@pytest.mark.parametrize("status_code", [200, 304])
@pytest.mark.parametrize("separate_process", [False, True])
async def test_late_catalog_response_does_not_restore_cache_after_logout(
    tmp_path: Path, status_code: int, separate_process: bool
) -> None:
    store = CodexCredentialStore(tmp_path)
    other_process_store = CodexCredentialStore(tmp_path)
    credentials = store.load_credentials()
    assert credentials is not None
    logout_during_response = False

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(503)
        if logout_during_response:
            assert request.headers["if-none-match"] == '"before-logout"'
            if separate_process:
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import sys; from pathlib import Path; "
                        "from deeptutor.services.codex_auth.storage import CodexCredentialStore; "
                        "CodexCredentialStore(Path(sys.argv[1])).clear_credentials("
                        "expected_generation=int(sys.argv[2]))",
                        str(tmp_path),
                        str(credentials.generation),
                    ],
                    cwd=Path(__file__).resolve().parents[3],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            else:
                other_process_store.clear_credentials(expected_generation=credentials.generation)
            assert other_process_store.load_catalog_cache() is None
            return httpx.Response(status_code, json=_fixture())
        return httpx.Response(200, json=_fixture(), headers={"etag": '"before-logout"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http, clock=lambda: 1_000)
        await catalog.get(credentials, force=True)
        logout_during_response = True
        error = None
        try:
            await catalog.get(credentials, force=True)
        except CodexAuthError as exc:
            error = exc

    assert store.load_credentials() is None
    assert other_process_store.load_catalog_cache() is None
    assert error is not None
    assert error.code == "generation_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 304])
@pytest.mark.parametrize("transition", ["refresh", "relogin", "switch_account"])
async def test_late_catalog_response_preserves_new_generation_cache(
    tmp_path: Path, status_code: int, transition: str
) -> None:
    store = CodexCredentialStore(tmp_path)
    other_process_store = CodexCredentialStore(tmp_path)
    credentials = store.load_credentials()
    assert credentials is not None
    change_during_response = False
    expected_cache = None
    catalog_calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal expected_cache, catalog_calls
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(503)
        catalog_calls += 1
        if change_during_response:
            generation = credentials.generation
            if transition != "refresh":
                generation = other_process_store.clear_credentials(expected_generation=generation)
            account_id = (
                "another-account" if transition == "switch_account" else credentials.account_id
            )
            current = other_process_store.commit_credentials(
                _credentials(account_id=account_id), expected_generation=generation
            )
            newer = replace(
                previous,
                generation=current.generation,
                account_hash=hashlib.sha256(account_id.encode()).hexdigest(),
                client_version="9.9.9",
                etag='"new-generation"',
            )
            other_process_store.commit_catalog_cache(newer)
            expected_cache = newer.to_dict()
            return httpx.Response(status_code, json=_fixture())
        return httpx.Response(200, json=_fixture(), headers={"etag": '"old-generation"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http, clock=lambda: 1_000)
        previous = await catalog.get(credentials, force=True)
        change_during_response = True
        with pytest.raises(CodexAuthError) as error:
            await catalog.get(credentials, force=True)

    assert error.value.code == "generation_changed"
    assert catalog_calls == 2
    assert expected_cache is not None
    assert store.load_catalog_cache() == expected_cache


@pytest.mark.asyncio
async def test_refresh_discovers_and_persists_version_without_sending_credentials(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "registry.npmjs.org":
            assert "authorization" not in request.headers
            assert "chatgpt-account-id" not in request.headers
            assert str(request.url) == "https://registry.npmjs.org/@openai%2Fcodex/latest"
            return httpx.Response(200, json={"name": "@openai/codex", "version": "1.2.3"})
        assert request.url.params["client_version"] == "1.2.3"
        return httpx.Response(200, json=_fixture())

    store = CodexCredentialStore(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http)
        live = await catalog.get(_credentials(), force=True)
        fresh = await catalog.get(_credentials(), force=False)
    assert live.client_version == fresh.client_version == "1.2.3"
    assert store.load_catalog_cache()["client_version"] == "1.2.3"
    assert len(requests) == 2


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
    credentials = CodexCredentialStore(tmp_path).commit_credentials(
        _credentials(account_id="account-a"), expected_generation=1
    )
    try:
        await catalog.get(credentials, force=True)
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
    cached = CodexCredentialStore(tmp_path).load_catalog_cache()
    assert cached["models_valid"] is False
    assert cached["models"] == []
    assert cached["etag"] is None
    assert cached["client_version"] == CODEX_CLIENT_VERSION


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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["schema", "version"])
async def test_new_version_falls_back_once_to_successful_version(
    tmp_path: Path, failure: str
) -> None:
    versions = iter(["1.2.3", "2.0.0"])
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"name": "@openai/codex", "version": next(versions)})
        version = request.url.params["client_version"]
        requested.append(version)
        if version == "2.0.0":
            assert "if-none-match" not in request.headers
            if failure == "schema":
                return httpx.Response(200, json={"unexpected": []})
            return httpx.Response(400, json={"error": {"code": "unsupported_client_version"}})
        return httpx.Response(200, json=_fixture(), headers={"etag": '"old-version"'})

    store = CodexCredentialStore(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http)
        await catalog.get(_credentials(), force=True)
        snapshot = await catalog.get(_credentials(), force=True)
    assert requested == ["1.2.3", "2.0.0", "1.2.3"]
    assert snapshot.source == "live"
    assert store.load_catalog_cache()["client_version"] == "1.2.3"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 429, 500])
async def test_manual_refresh_failure_is_not_stale_success(tmp_path: Path, status: int) -> None:
    queue = ResponseQueue(httpx.Response(200, json=_fixture()), httpx.Response(status))
    catalog, http = _catalog(tmp_path, queue, [1_000])
    try:
        original = await catalog.get(_credentials(), force=True)
        with pytest.raises(CodexAuthError):
            await catalog.get(_credentials(), force=True)
        assert CodexCredentialStore(tmp_path).load_catalog_cache() == original.to_dict()
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_version_discovery_failure_reuses_persisted_success_after_restart(
    tmp_path: Path,
) -> None:
    npm_responses = iter(
        [
            httpx.Response(200, json={"name": "@openai/codex", "version": "1.2.3"}),
            httpx.Response(503),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return next(npm_responses)
        assert request.url.params["client_version"] == "1.2.3"
        return httpx.Response(200, json=_fixture())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await CodexModelCatalog(CodexCredentialStore(tmp_path), http=http, version_http=http).get(
            _credentials(), force=True
        )
        restarted = CodexModelCatalog(CodexCredentialStore(tmp_path), http=http, version_http=http)
        assert (await restarted.get(_credentials(), force=True)).client_version == "1.2.3"


@pytest.mark.asyncio
@pytest.mark.parametrize("second_status", [200, 304])
async def test_version_change_never_reuses_old_etag_or_promotes_304(
    tmp_path: Path, second_status: int
) -> None:
    versions = iter(["1.2.3", "2.0.0"])
    catalog_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"name": "@openai/codex", "version": next(versions)})
        catalog_requests.append(request)
        if len(catalog_requests) == 2:
            assert "if-none-match" not in request.headers
            return httpx.Response(second_status, json=_fixture())
        if len(catalog_requests) == 3:
            assert request.url.params["client_version"] == "1.2.3"
            assert request.headers["if-none-match"] == '"v1"'
            return httpx.Response(304)
        return httpx.Response(200, json=_fixture(), headers={"etag": '"v1"'})

    store = CodexCredentialStore(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http)
        original = await catalog.get(_credentials(), force=True)
        if second_status == 304:
            with pytest.raises(CodexAuthError) as error:
                await catalog.get(_credentials(), force=True)
            assert error.value.code == "catalog_invalid_response"
            assert len(catalog_requests) == 2
            assert store.load_catalog_cache() == original.to_dict()
            return
        result = await catalog.get(_credentials(), force=True)
    assert result.client_version == "2.0.0"
    assert store.load_catalog_cache()["client_version"] == result.client_version


@pytest.mark.asyncio
async def test_legacy_cache_is_readable_but_never_revalidated_as_known_version(
    tmp_path: Path,
) -> None:
    queue = ResponseQueue(
        httpx.Response(200, json=_fixture(), headers={"etag": '"v1"'}),
        httpx.Response(200, json=_fixture()),
    )
    catalog, http = _catalog(tmp_path, queue, [1_000])
    store = CodexCredentialStore(tmp_path)
    try:
        await catalog.get(_credentials(), force=True)
        legacy = store.load_catalog_cache()
        del legacy["client_version"]
        store.save_catalog_cache(legacy)
        assert CatalogSnapshot.from_dict(legacy).client_version is None
        result = await catalog.get(_credentials(), force=True)
        assert result.client_version == CODEX_CLIENT_VERSION
        assert "if-none-match" not in queue.requests[1].headers
    finally:
        await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (httpx.Response(401), "catalog_unauthorized"),
        (httpx.Response(403), "catalog_forbidden"),
        (httpx.Response(429), "catalog_rate_limited"),
        (httpx.Response(500), "catalog_unavailable"),
        (httpx.Response(400, json={"error": {"code": "other"}}), "catalog_unavailable"),
        (httpx.ConnectError("offline"), "catalog_unavailable"),
        ("tls", "catalog_tls_error"),
    ],
)
async def test_new_version_does_not_retry_or_hide_unrelated_failures(
    tmp_path: Path, failure: httpx.Response | Exception | str, code: str
) -> None:
    catalog_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal catalog_requests
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"name": "@openai/codex", "version": "2.0.0"})
        catalog_requests += 1
        if failure == "tls":
            raise httpx.ConnectError("private tls detail") from ssl.SSLCertVerificationError()
        if isinstance(failure, Exception):
            raise failure
        assert isinstance(failure, httpx.Response)
        return failure

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(CodexCredentialStore(tmp_path), http=http, version_http=http)
        with pytest.raises(CodexAuthError) as error:
            await catalog.get(_credentials(), force=True)
    assert error.value.code == code
    assert catalog_requests == 1
    assert CodexCredentialStore(tmp_path).load_catalog_cache() is None


@pytest.mark.asyncio
async def test_failed_fallback_does_not_loop_or_overwrite_success(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"name": "@openai/codex", "version": "2.0.0"})
        calls += 1
        return httpx.Response(200, json={"invalid": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(CodexCredentialStore(tmp_path), http=http, version_http=http)
        with pytest.raises(CodexAuthError, match="invalid model catalog"):
            await catalog.get(_credentials(), force=True)
    assert calls == 2
    assert CodexCredentialStore(tmp_path).load_catalog_cache() is None


@pytest.mark.asyncio
async def test_credential_rotation_keeps_version_but_not_catalog_or_etag(tmp_path: Path) -> None:
    npm_calls = 0
    catalog_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal npm_calls, catalog_calls
        if request.url.host == "registry.npmjs.org":
            npm_calls += 1
            if npm_calls == 1:
                return httpx.Response(200, json={"name": "@openai/codex", "version": "1.2.3"})
            return httpx.Response(503)
        catalog_calls += 1
        assert request.url.params["client_version"] == "1.2.3"
        assert "if-none-match" not in request.headers
        if catalog_calls == 1:
            return httpx.Response(200, json=_fixture(), headers={"etag": '"old-generation"'})
        raise httpx.ConnectError("offline")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(CodexCredentialStore(tmp_path), http=http, version_http=http)
        await catalog.get(_credentials(), force=True)
        with pytest.raises(CodexAuthError):
            await catalog.get(_credentials(generation=2), force=False)
    assert catalog_calls == 2
    assert npm_calls == 1


@pytest.mark.asyncio
async def test_invalid_json_does_not_retry_a_different_version(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"name": "@openai/codex", "version": "2.0.0"})
        calls += 1
        return httpx.Response(200, content=b"<html>gateway error</html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(CodexCredentialStore(tmp_path), http=http, version_http=http)
        with pytest.raises(CodexAuthError) as error:
            await catalog.get(_credentials(), force=True)
    assert error.value.code == "catalog_invalid_response"
    assert calls == 1


@pytest.mark.asyncio
async def test_auth_invalidation_preserves_version_history_but_no_usable_models(
    tmp_path: Path,
) -> None:
    npm_calls = 0
    catalog_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal npm_calls, catalog_calls
        if request.url.host == "registry.npmjs.org":
            npm_calls += 1
            if npm_calls == 1:
                return httpx.Response(200, json={"name": "@openai/codex", "version": "1.2.3"})
            return httpx.Response(503)
        catalog_calls += 1
        assert request.url.params["client_version"] == "1.2.3"
        if catalog_calls == 1:
            return httpx.Response(200, json=_fixture(), headers={"etag": '"old"'})
        if catalog_calls == 2:
            return httpx.Response(401)
        assert "if-none-match" not in request.headers
        if catalog_calls == 3:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json=_fixture())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(CodexCredentialStore(tmp_path), http=http, version_http=http)
        await catalog.get(_credentials(), force=True)
        with pytest.raises(CodexAuthError):
            await catalog.get(_credentials(), force=True)
        # The same generation must not get a fresh or stale invalidated catalog.
        with pytest.raises(CodexAuthError):
            await catalog.get(_credentials(), force=False)
        refreshed = CodexCredentialStore(tmp_path).commit_credentials(
            _credentials(), expected_generation=1
        )
        result = await catalog.get(refreshed, force=True)
    assert result.client_version == "1.2.3"
    assert result.models_valid is True
    assert result.source == "live"
