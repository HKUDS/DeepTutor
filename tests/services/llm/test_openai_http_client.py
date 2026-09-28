"""Tests for OpenAI SDK HTTP client options shared across providers."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.llm import openai_http_client
from deeptutor.services.llm.exceptions import LLMConfigError
from deeptutor.services.provider_registry import PROVIDERS, find_by_name


@pytest.fixture(autouse=True)
def _clean_ssl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(openai_http_client, "_warning_logged", False)


def _enable_ssl_override(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    clients: list[Any] = []

    class HTTPClientStub:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            clients.append(self)

    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    monkeypatch.setattr(openai_http_client.httpx, "AsyncClient", HTTPClientStub)
    return clients


def _capture_async_openai(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    class AsyncOpenAIStub:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(module, "AsyncOpenAI", AsyncOpenAIStub)
    return captured


def test_openai_client_kwargs_disable_ssl_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    clients = _enable_ssl_override(monkeypatch)

    kwargs = openai_http_client.openai_client_kwargs(timeout=60)

    assert kwargs["http_client"] is clients[0]
    assert clients[0].kwargs == {"verify": False, "timeout": 60}


def test_openai_client_kwargs_rejects_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(LLMConfigError, match="not allowed in production"):
        openai_http_client.openai_client_kwargs()


def test_provider_core_passes_disable_ssl_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.llm.provider_core import openai_compat_provider as provider_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, provider_mod)

    provider_mod.OpenAICompatProvider(api_key="sk-test", api_base="https://example.com/v1")

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False


def test_azure_provider_passes_disable_ssl_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.llm.provider_core import azure_openai_provider as azure_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, azure_mod)

    azure_mod.AzureOpenAIProvider(
        api_key="sk-test",
        api_base="https://example.openai.azure.com",
        default_model="gpt-test",
    )

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False


def test_agentic_client_passes_disable_ssl_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agentic handle builds its SDK client through the same helper as provider_core."""
    from deeptutor.runtime.agentic import client as agentic_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, agentic_mod)

    agentic_mod._build_openai_client(
        agentic_mod.LLMClientConfig(
            binding="custom",
            model="gpt-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            extra_headers={"X-Test": "1"},
        ),
        disable_ssl_verify=True,
    )

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False
    assert captured[0]["default_headers"]["X-Test"] == "1"
    assert "x-session-affinity" in captured[0]["default_headers"]


def test_embedding_sdk_passes_disable_ssl_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.embedding.adapters import openai_sdk as embedding_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, embedding_mod)

    adapter = embedding_mod.OpenAISDKEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://example.com/v1",
            "model": "text-embedding-3-large",
            "request_timeout": 30,
        }
    )
    adapter._build_client()

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs == {"verify": False, "timeout": 60}


# --- AI/ML API attribution ---------------------------------------------------
# Scoped to the host the SDK client will call, never to the profile's binding.

_AIMLAPI_SPEC = find_by_name("aimlapi")

_PARTNER_ID_PATTERN = re.compile(r"^part_[A-Za-z0-9]{1,64}$")
_SOURCE_PATTERN = re.compile(r"^(web|agent|mcp)/[a-z0-9-]{1,32}$")


def _default_headers(**kwargs: Any) -> dict[str, str]:
    return openai_http_client.openai_sdk_client_kwargs(api_key="sk-test", **kwargs)[
        "default_headers"
    ]


def test_aimlapi_partner_id_and_source_match_the_gateway_contract() -> None:
    headers = openai_http_client.AIMLAPI_ATTRIBUTION_HEADERS

    assert _PARTNER_ID_PATTERN.match(headers["X-AIMLAPI-Partner-ID"])
    assert _SOURCE_PATTERN.match(headers["X-AIMLAPI-Source"])
    assert headers["HTTP-Referer"] == "https://github.com/HKUDS/DeepTutor"
    assert headers["X-Title"] == "DeepTutor"


def test_aimlapi_attribution_sent_for_the_registry_endpoint() -> None:
    headers = _default_headers(base_url=_AIMLAPI_SPEC.default_api_base, spec=_AIMLAPI_SPEC)

    assert headers["X-AIMLAPI-Partner-ID"] == "part_ItAs0L5uSTvV2dFDOZZaS1BL"
    assert headers["X-AIMLAPI-Source"] == "agent/deeptutor"
    assert headers["X-Title"] == "DeepTutor"


def test_aimlapi_attribution_withheld_when_sdk_falls_back_to_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``base_url=None`` makes AsyncOpenAI call api.openai.com, whatever the binding says."""
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    headers = _default_headers(base_url=None, spec=_AIMLAPI_SPEC)

    assert not [key for key in headers if key.lower().startswith("x-aimlapi-")]


def test_aimlapi_attribution_follows_openai_base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no explicit base_url the SDK honours OPENAI_BASE_URL, so the gate must too."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.aimlapi.com/v1")
    assert "X-AIMLAPI-Partner-ID" in _default_headers(base_url=None, spec=None)

    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example.com/v1")
    assert "X-AIMLAPI-Partner-ID" not in _default_headers(base_url=None, spec=_AIMLAPI_SPEC)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.aimlapi.com/v1",
        "https://API.AIMLAPI.COM/v1",
        "api.aimlapi.com/v1",
    ],
)
def test_aimlapi_attribution_sent_for_equivalent_spellings(base_url: str) -> None:
    headers = _default_headers(base_url=base_url, spec=None)

    assert headers["X-AIMLAPI-Partner-ID"] == "part_ItAs0L5uSTvV2dFDOZZaS1BL"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.aimlapi.com.evil.io/v1",
        "https://notaimlapi.com/v1",
        "https://aimlapi.com.attacker.example/v1",
        "https://gateway.internal.example/aimlapi/v1",
        "https://openrouter.ai/api/v1",
        "https://api.openai.com/v1",
    ],
)
def test_aimlapi_attribution_withheld_from_other_hosts(base_url: str) -> None:
    headers = _default_headers(base_url=base_url, spec=None)

    assert not [key for key in headers if key.lower().startswith("x-aimlapi-")]


def test_aimlapi_attribution_withheld_when_binding_points_at_a_proxy() -> None:
    headers = _default_headers(base_url="https://proxy.example.com/v1", spec=_AIMLAPI_SPEC)

    assert not [key for key in headers if key.lower().startswith("x-aimlapi-")]


def test_aimlapi_attribution_does_not_override_caller_headers() -> None:
    headers = _default_headers(
        base_url="https://api.aimlapi.com/v1",
        spec=_AIMLAPI_SPEC,
        extra_headers={"X-Title": "Caller Wins", "X-Custom": "1"},
    )

    assert headers["X-Title"] == "Caller Wins"
    assert headers["X-Custom"] == "1"
    assert headers["X-AIMLAPI-Partner-ID"] == "part_ItAs0L5uSTvV2dFDOZZaS1BL"


def test_aimlapi_attribution_constant_is_never_mutated() -> None:
    before = dict(openai_http_client.AIMLAPI_ATTRIBUTION_HEADERS)

    _default_headers(
        base_url="https://api.aimlapi.com/v1",
        spec=_AIMLAPI_SPEC,
        extra_headers={"X-Title": "Caller Wins"},
    )

    assert openai_http_client.AIMLAPI_ATTRIBUTION_HEADERS == before


def test_no_other_provider_spec_carries_aimlapi_headers() -> None:
    for spec in PROVIDERS:
        if spec.name == "aimlapi":
            continue
        headers = _default_headers(base_url=spec.default_api_base or None, spec=spec)
        leaked = [key for key in headers if key.lower().startswith("x-aimlapi-")]
        assert not leaked, f"{spec.name} leaks {leaked}"
