"""Provider-only probes must be truthful, read-only, and keep credentials private."""

from copy import deepcopy
from types import SimpleNamespace

import aiohttp
import pytest

from deeptutor.services.settings import provider_probe


class Response:
    def __init__(self, status=200, payload=None):
        self.status, self.payload = status, payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, response):
        self.response, self.requests = response, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def install(monkeypatch, response):
    session = Session(response)
    monkeypatch.setattr(provider_probe.aiohttp, "ClientSession", lambda **kw: session)
    monkeypatch.setattr(provider_probe, "_get_aiohttp_connector", lambda: None)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "auth_error"),
        (403, "auth_error"),
        (404, "unavailable"),
        (405, "unavailable"),
        (429, "rate_limited"),
        (500, "http_error"),
        (302, "http_error"),
    ],
)
async def test_http_errors_are_not_successful_connections(monkeypatch, status, expected):
    session = install(monkeypatch, Response(status, {"error": "secret-sk-do-not-return"}))
    result = await provider_probe.probe_provider("openai", "https://example.test/v1", "secret")
    assert result == {"status": expected, "models": [], "http_status": status}
    assert len(session.requests) == 1
    assert session.requests[0][1]["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"data": []}, "connected"),
        ({"data": [{"id": "one"}, {"id": "one"}]}, "connected"),
        ({"error": "no models"}, "unavailable"),
        ({"data": [{"unexpected": 123}]}, "unavailable"),
        (ValueError("HTML response"), "unavailable"),
    ],
)
async def test_only_recognized_listing_responses_verify_connection(monkeypatch, payload, expected):
    install(monkeypatch, Response(payload=payload))
    result = await provider_probe.probe_provider("openai", "https://example.test/v1", "secret")
    assert result["status"] == expected
    if isinstance(payload, dict) and payload.get("data") and expected == "connected":
        assert result["models"] == [{"id": "one"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "binding,base,fmt,url,header",
    [
        (
            "custom",
            "https://example.test/v1",
            "anthropic",
            "https://example.test/v1/models",
            "x-api-key",
        ),
        (
            "ollama",
            "http://localhost:11434/v1/",
            "auto",
            "http://localhost:11434/api/tags",
            "Authorization",
        ),
        (
            "azure",
            "https://example.test/openai",
            "auto",
            "https://example.test/openai/models",
            "api-key",
        ),
    ],
)
async def test_native_headers_and_local_discovery(monkeypatch, binding, base, fmt, url, header):
    session = install(monkeypatch, Response(payload={"models": [{"name": "local:latest"}]}))
    result = await provider_probe.probe_provider(
        binding, base, "key", fmt, {"X-Gateway": "value"}, "preview"
    )
    assert result == {"status": "connected", "models": [{"id": "local:latest"}]}
    assert session.requests[0][0] == url
    assert header in session.requests[0][1]["headers"]
    assert session.requests[0][1]["headers"]["X-Gateway"] == "value"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status",
    [(TimeoutError("secret"), "timeout"), (aiohttp.ClientError("secret"), "unreachable")],
)
async def test_network_errors_do_not_leak_credentials(monkeypatch, error, status):
    install(monkeypatch, error)
    assert await provider_probe.probe_provider("openai", "https://example.test", "secret") == {
        "status": status,
        "models": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("connection", [False, True])
async def test_route_resolves_draft_secrets_by_id_without_writes(monkeypatch, connection):
    from deeptutor.api.routers import settings as router

    entry = {"id": "saved", "api_key": "live-key", "extra_headers": {"X-Key": "live-header"}}
    live = {"connections": [entry], "services": {"llm": {"profiles": [entry]}}}
    draft = deepcopy(live)
    for item in [draft["connections"][0], draft["services"]["llm"]["profiles"][0]]:
        item["api_key"] = "draft-key"
        item["extra_headers"]["X-Key"] = "draft-header"
    original = deepcopy((live, draft))
    monkeypatch.setattr(router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(
        router, "get_model_catalog_service", lambda: SimpleNamespace(load=lambda: live)
    )
    monkeypatch.setattr(
        router,
        "get_settings_draft_service",
        lambda: SimpleNamespace(load=lambda: {"catalog": draft}),
    )
    calls = []

    async def probe(*args):
        calls.append(args)
        return {"status": "connected", "models": []}

    monkeypatch.setattr(provider_probe, "probe_provider", probe)
    payload = router.ProviderProbePayload(
        base_url="https://example.test/v1",
        api_key="***",
        extra_headers={"X-Key": "***"},
        connection_id="saved" if connection else None,
        profile_id=None if connection else "saved",
    )
    assert await router.test_provider_connection(payload) == {"status": "connected", "models": []}
    assert calls[0][2] == "draft-key"
    assert calls[0][4] == {"X-Key": "draft-header"}
    payload.api_key = "just-typed-key"
    await router.test_provider_connection(payload)
    assert calls[1][2] == "just-typed-key"
    assert (live, draft) == original


@pytest.mark.asyncio
async def test_probe_keeps_admin_boundary(monkeypatch):
    from fastapi import HTTPException

    from deeptutor.api.routers import settings as router

    def denied():
        raise HTTPException(status_code=403)

    monkeypatch.setattr(router, "_require_settings_admin", denied)
    with pytest.raises(HTTPException) as exc:
        await router.test_provider_connection(router.ProviderProbePayload())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["/embeddings", "/audio/speech", "/images/generations"])
async def test_full_service_endpoint_discovers_sibling_models(monkeypatch, suffix):
    session = install(monkeypatch, Response(payload={"data": []}))
    await provider_probe.probe_provider("openai", "https://example.test/v1" + suffix, "key")
    assert session.requests[0][0] == "https://example.test/v1/models"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["http://[", "https://example.test:wrong", "ftp://example.test", "http://key@example.test"],
)
async def test_invalid_addresses_are_actionable_without_network_requests(monkeypatch, url):
    session = install(monkeypatch, Response(payload={"data": []}))
    assert await provider_probe.probe_provider("openai", url) == {
        "status": "invalid_url",
        "models": [],
    }
    assert session.requests == []


@pytest.mark.parametrize(
    "inputs,outputs,expected",
    [
        (["image", "video"], ["text"], {"llm"}),
        (["text"], ["audio"], {"voice"}),
        (["audio"], ["text"], {"llm", "voice"}),
        (["text"], ["image"], {"generation"}),
        (["image"], ["video", "audio"], {"generation", "voice"}),
        (["IMAGE"], ["TEXT"], {"llm"}),
    ],
)
def test_voice_and_visual_generation_detection_are_independent(inputs, outputs, expected):
    result = provider_probe.detect_capabilities(
        [{"architecture": {"input_modalities": inputs, "output_modalities": outputs}}]
    )
    assert {item["category"] for item in result} == expected
