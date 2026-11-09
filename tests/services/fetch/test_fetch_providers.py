"""Offline tests for the pluggable fetch-backend registry (issue #2448).

All HTTP is stubbed: the DeepSeek adapter takes an injectable
``client_factory``, and no test ever touches a real network endpoint or
credential.
"""

from __future__ import annotations

import httpx
import pytest

from deeptutor.services.config import (
    DEFAULT_FETCH_PROVIDER,
    FETCH_PROVIDERS,
    fetch_provider_spec,
)
from deeptutor.services.fetch import (
    FETCH_BACKEND_ENV,
    get_fetch_provider,
    list_fetch_providers,
    resolve_fetch_backend,
)
from deeptutor.services.fetch.base import FetchProviderError
from deeptutor.services.fetch.providers.deepseek import (
    DEFAULT_BASE_URL,
    FETCH_PATH,
    DeepSeekFetchProvider,
)
from deeptutor.services.fetch.providers.local import LocalFetchProvider


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Keep deployment/env credential knobs out of every test here."""
    for name in (
        FETCH_BACKEND_ENV,
        "DEEPSEEK_FETCH_API_KEY",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_FETCH_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Spec table + registry
# ---------------------------------------------------------------------------


def test_spec_table_declares_local_default_and_deepseek() -> None:
    assert DEFAULT_FETCH_PROVIDER == "local"
    assert set(FETCH_PROVIDERS) == {"local", "deepseek"}
    assert FETCH_PROVIDERS["local"].requires_api_key is False
    assert FETCH_PROVIDERS["deepseek"].requires_api_key is True
    assert fetch_provider_spec("DeepSeek") is FETCH_PROVIDERS["deepseek"]
    assert fetch_provider_spec("nope") is None


def test_registry_lists_exactly_the_spec_table() -> None:
    assert list_fetch_providers() == sorted(FETCH_PROVIDERS)


def test_adapter_metadata_comes_from_the_spec_table() -> None:
    for provider_id in FETCH_PROVIDERS:
        cls = type(get_fetch_provider(provider_id))
        spec = FETCH_PROVIDERS[provider_id]
        assert cls.name == provider_id
        assert cls.display_name == spec.label
        assert cls.requires_api_key == spec.requires_api_key
        assert cls.requires_base_url == spec.requires_base_url


def test_unknown_backend_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown fetch backend"):
        get_fetch_provider("nope")


def test_default_backend_resolution() -> None:
    assert resolve_fetch_backend() == "local"


def test_env_override_selects_a_registered_backend(monkeypatch) -> None:
    monkeypatch.setenv(FETCH_BACKEND_ENV, "DeepSeek")
    assert resolve_fetch_backend() == "deepseek"


def test_env_override_with_unknown_name_falls_back_to_local(monkeypatch) -> None:
    monkeypatch.setenv(FETCH_BACKEND_ENV, "tarball")
    assert resolve_fetch_backend() == "local"


# ---------------------------------------------------------------------------
# Local adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_adapter_delegates_to_the_local_path() -> None:
    # An unsupported scheme fails inside fetch_url_as_markdown's shared
    # entry checks — proof the adapter routes through the real dispatcher
    # with backend="local" instead of its own HTTP code.
    outcome = await LocalFetchProvider().fetch("ftp://example.com/x")
    assert outcome.ok is False
    assert "scheme" in outcome.error.lower()


# ---------------------------------------------------------------------------
# DeepSeek adapter — stubbed client, fully offline
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, *, status: int = 200, payload: object | Exception | None = None):
        self.status_code = status
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _StubClient:
    def __init__(self, result: _StubResponse | Exception):
        self._result = result
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _factory(result: _StubResponse | Exception):
    created: dict[str, _StubClient] = {}

    def _make(*, timeout: float):
        client = _StubClient(result)
        client.timeout = timeout
        created["client"] = client
        return client

    return _make, created


def _provider(api_key: str = "test-key", **kwargs) -> DeepSeekFetchProvider:
    return DeepSeekFetchProvider(api_key=api_key, **kwargs)


@pytest.mark.asyncio
async def test_deepseek_success_returns_markdown_title_and_requested_url() -> None:
    make, created = _factory(
        _StubResponse(payload={"title": "Docs", "content": "# Docs\n\nBody text."})
    )

    outcome = await _provider().fetch("https://example.com/page", client_factory=make)

    assert outcome.ok is True
    assert outcome.markdown == "# Docs\n\nBody text."
    assert outcome.title == "Docs"
    # Remote backends cannot report the post-redirect URL: citations keep
    # the requested URL (documented trade-off).
    assert outcome.url == "https://example.com/page"
    ((url, kwargs),) = created["client"].calls
    assert url == f"{DEFAULT_BASE_URL}{FETCH_PATH}"
    assert kwargs["json"] == {"url": "https://example.com/page"}
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_deepseek_passes_timeout_to_its_own_client() -> None:
    make, created = _factory(_StubResponse(payload={"title": "", "content": "x"}))

    await _provider().fetch("https://example.com/", timeout_s=7.5, client_factory=make)

    assert created["client"].timeout == 7.5


@pytest.mark.asyncio
async def test_deepseek_missing_key_is_retryable_and_makes_no_request() -> None:
    provider = DeepSeekFetchProvider(api_key="")
    make, created = _factory(_StubResponse(payload={}))

    with pytest.raises(FetchProviderError) as excinfo:
        await provider.fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True
    assert "client" not in created  # no HTTP attempted without credentials


@pytest.mark.parametrize("status", [400, 404, 413])
@pytest.mark.asyncio
async def test_deepseek_hard_failure_statuses_fail_without_retry_signal(status: int) -> None:
    make, _created = _factory(_StubResponse(status=status))

    outcome = await _provider().fetch("https://example.com/", client_factory=make)

    assert outcome.ok is False
    assert f"HTTP {status}" in outcome.error
    assert outcome.url == "https://example.com/"


@pytest.mark.parametrize("status", [401, 402, 403, 408, 429, 500, 503])
@pytest.mark.asyncio
async def test_deepseek_retryable_statuses_raise_retryable_error(status: int) -> None:
    make, _created = _factory(_StubResponse(status=status))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True
    assert str(status) in excinfo.value.message


@pytest.mark.asyncio
async def test_deepseek_network_errors_are_retryable() -> None:
    make, _created = _factory(httpx.ConnectError("connection refused"))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_deepseek_non_json_body_is_retryable() -> None:
    make, _created = _factory(_StubResponse(payload=ValueError("not json")))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_deepseek_non_object_payload_is_retryable() -> None:
    make, _created = _factory(_StubResponse(payload=["not", "a", "dict"]))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_deepseek_empty_content_is_a_hard_failure() -> None:
    make, _created = _factory(_StubResponse(payload={"title": "Empty", "content": "   "}))

    outcome = await _provider().fetch("https://example.com/", client_factory=make)

    assert outcome.ok is False
    assert "no content" in outcome.error


# ---------------------------------------------------------------------------
# Credential / endpoint resolution — order: kwargs > env > chat profile
# ---------------------------------------------------------------------------


def test_explicit_kwargs_beat_env_credentials(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    provider = DeepSeekFetchProvider(api_key="arg-key", base_url="https://gw.example/")
    assert provider.api_key == "arg-key"
    assert provider.base_url == "https://gw.example"


def test_fetch_env_key_beats_chat_env_key(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_FETCH_API_KEY", "fetch-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chat-key")
    assert DeepSeekFetchProvider().api_key == "fetch-key"
    monkeypatch.delenv("DEEPSEEK_FETCH_API_KEY")
    assert DeepSeekFetchProvider().api_key == "chat-key"


def test_base_url_env_override(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_FETCH_BASE_URL", "https://gw.example/v1")
    provider = DeepSeekFetchProvider(api_key="k")
    assert provider.base_url == "https://gw.example/v1"


def test_credentials_fall_back_to_a_deepseek_chat_profile(monkeypatch) -> None:
    class _CatalogService:
        def load(self):
            return {
                "services": {
                    "llm": {
                        "profiles": [
                            {"binding": "openai", "api_key": "openai-key"},
                            {"binding": "deepseek", "api_key": "chat-key"},
                        ]
                    }
                }
            }

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service", lambda: _CatalogService()
    )
    assert DeepSeekFetchProvider().api_key == "chat-key"


def test_masked_or_broken_catalog_keys_are_ignored(monkeypatch) -> None:
    class _MaskedService:
        def load(self):
            return {"services": {"llm": {"profiles": [{"binding": "deepseek", "api_key": "***"}]}}}

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service", lambda: _MaskedService()
    )
    assert DeepSeekFetchProvider().api_key == ""

    class _BrokenService:
        def load(self):
            raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service", lambda: _BrokenService()
    )
    assert DeepSeekFetchProvider().api_key == ""
