"""Offline tests for the pluggable fetch-backend registry (issue #2448).

All HTTP is stubbed: the DeepSeek adapter takes an injectable
``client_factory``, and no test ever touches a real network endpoint or
credential. The persisted backend choice is exercised against a temporary
settings directory — never the real user settings dir.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from deeptutor.services.config import (
    DEFAULT_FETCH_PROVIDER,
    FETCH_PROVIDERS,
    fetch_provider_spec,
)
from deeptutor.services.fetch import (
    FETCH_BACKEND_ENV,
    FETCH_BACKEND_SETTINGS_KEY,
    get_fetch_provider,
    list_fetch_providers,
    resolve_fetch_backend,
)
from deeptutor.services.fetch.base import FetchProviderError, redact_fetch_error
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


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the global runtime settings at a throwaway directory."""
    from deeptutor.services.config import runtime_settings

    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True)
    monkeypatch.setattr(runtime_settings, "_global_settings_dir", lambda: settings_dir)
    monkeypatch.setattr(runtime_settings.RuntimeSettingsService, "_instances", {}, raising=False)
    return settings_dir


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


def test_default_backend_resolution(isolated_settings: Path) -> None:
    assert resolve_fetch_backend() == "local"


def test_env_override_selects_a_registered_backend(monkeypatch) -> None:
    monkeypatch.setenv(FETCH_BACKEND_ENV, "DeepSeek")
    assert resolve_fetch_backend() == "deepseek"


def test_env_override_with_unknown_name_falls_back_to_local(
    monkeypatch, isolated_settings: Path
) -> None:
    monkeypatch.setenv(FETCH_BACKEND_ENV, "tarball")
    assert resolve_fetch_backend() == "local"


def test_persisted_backend_is_used_when_no_env_override(isolated_settings: Path) -> None:
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service

    get_runtime_settings_service().save_system({FETCH_BACKEND_SETTINGS_KEY: "deepseek"})

    assert resolve_fetch_backend() == "deepseek"


def test_env_override_beats_the_persisted_backend(monkeypatch, isolated_settings: Path) -> None:
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service

    get_runtime_settings_service().save_system({FETCH_BACKEND_SETTINGS_KEY: "deepseek"})
    monkeypatch.setenv(FETCH_BACKEND_ENV, "local")

    assert resolve_fetch_backend() == "local"


def test_invalid_persisted_backend_falls_back_to_local_with_warning(
    isolated_settings: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Written raw to disk so the value reaches the loader un-normalized;
    # _normalize_system warns and coerces it to "local" before resolve sees it.
    settings_file = isolated_settings / "system.json"
    settings_file.write_text(
        json.dumps({"version": 1, FETCH_BACKEND_SETTINGS_KEY: "tarball"}), encoding="utf-8"
    )

    with caplog.at_level("WARNING", logger="deeptutor.services.config.runtime_settings"):
        assert resolve_fetch_backend() == "local"

    assert "tarball" in caplog.text


def test_settings_load_failure_never_breaks_web_fetch(monkeypatch, isolated_settings: Path) -> None:
    from deeptutor.services.config import runtime_settings

    def _boom():
        raise RuntimeError("settings store unavailable")

    monkeypatch.setattr(runtime_settings, "get_runtime_settings_service", _boom)

    assert resolve_fetch_backend() == "local"


def test_setting_spec_row_exposes_and_persists_the_backend(isolated_settings: Path) -> None:
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service
    from deeptutor.services.config.settings_spec import setting_specs

    row = setting_specs()["web_fetch.backend"]

    assert row.scope == "global" and row.effect == "instant"
    assert [choice.value for choice in row.choices()] == ["local", "deepseek"]
    assert row.validate("nope") is not None
    assert row.validate("deepseek") is None

    row.write("deepseek")
    assert row.read() == "deepseek"
    assert get_runtime_settings_service().load_system()[FETCH_BACKEND_SETTINGS_KEY] == "deepseek"
    assert resolve_fetch_backend() == "deepseek"


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
# DeepSeek adapter — stubbed streaming client, fully offline
# ---------------------------------------------------------------------------


class _StubStreamResponse:
    """Streaming response stand-in matching the ``client.stream`` shape."""

    def __init__(
        self,
        *,
        status: int = 200,
        payload: object | Exception | None = None,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload
        self._chunks = chunks
        self.chunks_consumed = 0

    async def aiter_raw(self):
        # The provider reads raw (undecoded) bytes so a compressed body can
        # never inflate past the cap inside httpx's content decoder.
        if self._chunks is not None:
            for chunk in self._chunks:
                self.chunks_consumed += 1
                yield chunk
        elif isinstance(self._payload, Exception):
            raise self._payload
        else:
            self.chunks_consumed += 1
            yield json.dumps(self._payload).encode("utf-8")


class _StubClient:
    def __init__(self, result: _StubStreamResponse | Exception):
        self._result = result
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method: str, url: str, **kwargs):
        self.calls.append((url, kwargs))
        result = self._result
        outer = self

        class _Ctx:
            async def __aenter__(self):
                if isinstance(result, Exception):
                    raise result
                return result

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _factory(result: _StubStreamResponse | Exception):
    created: dict[str, _StubClient] = {}

    def _make(*, timeout: float):
        client = _StubClient(result)
        client.timeout = timeout
        created["client"] = client
        return client

    return _make, created


def _provider(api_key: str = "sk-test-key-1234567890", **kwargs) -> DeepSeekFetchProvider:
    return DeepSeekFetchProvider(api_key=api_key, **kwargs)


def _no_deepseek_profile(monkeypatch) -> None:
    """Pin the credential catalog to "no DeepSeek profile", isolating the test
    from any real key stored on the machine running the suite."""

    class _EmptyCatalogService:
        def load(self):
            return {"services": {"llm": {"profiles": []}}}

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: _EmptyCatalogService(),
    )


@pytest.mark.asyncio
async def test_deepseek_success_returns_markdown_title_and_requested_url() -> None:
    make, created = _factory(
        _StubStreamResponse(payload={"title": "Docs", "content": "# Docs\n\nBody text."})
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
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test-key-1234567890"


@pytest.mark.asyncio
async def test_deepseek_passes_timeout_to_its_own_client() -> None:
    make, created = _factory(_StubStreamResponse(payload={"title": "", "content": "x"}))

    await _provider().fetch("https://example.com/", timeout_s=7.5, client_factory=make)

    assert created["client"].timeout == 7.5


@pytest.mark.asyncio
async def test_deepseek_missing_key_is_retryable_and_makes_no_request(monkeypatch) -> None:
    # The catalog is pinned empty AND the env vars are cleared (autouse
    # fixture) so this never depends on credentials present on the machine.
    _no_deepseek_profile(monkeypatch)
    provider = DeepSeekFetchProvider(api_key="")
    make, created = _factory(_StubStreamResponse(payload={}))

    with pytest.raises(FetchProviderError) as excinfo:
        await provider.fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True
    assert "client" not in created  # no HTTP attempted without credentials


@pytest.mark.asyncio
async def test_deepseek_ignores_catalog_credentials_when_env_is_gone(monkeypatch) -> None:
    _no_deepseek_profile(monkeypatch)
    assert DeepSeekFetchProvider(api_key="").api_key == ""


@pytest.mark.parametrize("status", [400, 404, 413])
@pytest.mark.asyncio
async def test_deepseek_hard_failure_statuses_fail_without_retry_signal(status: int) -> None:
    make, _created = _factory(_StubStreamResponse(status=status))

    outcome = await _provider().fetch("https://example.com/", client_factory=make)

    assert outcome.ok is False
    assert f"HTTP {status}" in outcome.error
    assert outcome.url == "https://example.com/"


@pytest.mark.parametrize("status", [401, 402, 403, 408, 429, 500, 503])
@pytest.mark.asyncio
async def test_deepseek_retryable_statuses_raise_retryable_error(status: int) -> None:
    make, _created = _factory(_StubStreamResponse(status=status))

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
    make, _created = _factory(_StubStreamResponse(chunks=[b"<html>not json</html>"]))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_deepseek_non_object_payload_is_retryable() -> None:
    make, _created = _factory(_StubStreamResponse(payload=["not", "a", "dict"]))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True


@pytest.mark.parametrize("content", [{"blocks": []}, ["a", "b"], 42, True, None])
@pytest.mark.asyncio
async def test_deepseek_non_string_content_is_retryable(content: object) -> None:
    make, _created = _factory(_StubStreamResponse(payload={"title": "T", "content": content}))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/", client_factory=make)

    assert excinfo.value.retryable is True
    assert "non-string content" in excinfo.value.message


@pytest.mark.asyncio
async def test_deepseek_non_string_title_is_ignored_not_stringified() -> None:
    make, _created = _factory(
        _StubStreamResponse(payload={"title": {"nested": "object"}, "content": "body"})
    )

    outcome = await _provider().fetch("https://example.com/", client_factory=make)

    assert outcome.ok is True
    assert outcome.title == ""
    assert outcome.markdown == "body"


@pytest.mark.asyncio
async def test_deepseek_empty_content_is_a_hard_failure() -> None:
    make, _created = _factory(_StubStreamResponse(payload={"title": "Empty", "content": "   "}))

    outcome = await _provider().fetch("https://example.com/", client_factory=make)

    assert outcome.ok is False
    assert "no content" in outcome.error


# ---------------------------------------------------------------------------
# Remote response bounding — same 4 MB cap as the local download path
# ---------------------------------------------------------------------------


def _oversized_chunks(chunk_bytes: int, count: int) -> list[bytes]:
    return [b"x" * chunk_bytes for _ in range(count)]


@pytest.mark.asyncio
async def test_deepseek_response_over_cap_is_retryable_and_not_fully_consumed() -> None:
    from deeptutor.tools.web_fetch import MAX_RESPONSE_BYTES

    # 6 chunks of half the cap: the cap blows on chunk 3, so chunks 4-6 must
    # never be pulled from the response.
    chunk = MAX_RESPONSE_BYTES // 2
    response = _StubStreamResponse(chunks=_oversized_chunks(chunk, 6))
    make, _created = _factory(response)

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/huge", client_factory=make)

    assert excinfo.value.retryable is True
    assert "exceeds" in excinfo.value.message
    assert response.chunks_consumed == 3  # stopped reading at the cap


@pytest.mark.asyncio
async def test_deepseek_content_length_over_cap_rejects_before_reading() -> None:
    from deeptutor.tools.web_fetch import MAX_RESPONSE_BYTES

    response = _StubStreamResponse(
        chunks=_oversized_chunks(1024, 8),
        headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
    )
    make, _created = _factory(response)

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/huge", client_factory=make)

    assert excinfo.value.retryable is True
    assert response.chunks_consumed == 0  # Content-Length gate fired first


@pytest.mark.asyncio
async def test_deepseek_response_at_cap_boundary_is_accepted() -> None:
    from deeptutor.tools.web_fetch import MAX_RESPONSE_BYTES

    payload = {"title": "T", "content": "fine"}
    body = json.dumps(payload).encode("utf-8")
    response = _StubStreamResponse(
        chunks=[body], headers={"content-length": str(MAX_RESPONSE_BYTES)}
    )
    make, _created = _factory(response)

    outcome = await _provider().fetch("https://example.com/", client_factory=make)

    assert outcome.ok is True
    assert outcome.markdown == "fine"


@pytest.mark.asyncio
async def test_deepseek_stream_never_buffers_past_the_cap(monkeypatch) -> None:
    """Many chunks under a patched-down cap: remaining capacity is checked
    BEFORE extending, so the buffer never holds more than the cap (an
    extend-then-check loop would blow it inside extend), and the request
    asks for an identity body so compression cannot inflate chunks unseen."""
    import deeptutor.services.fetch.providers.deepseek as deepseek_module
    from deeptutor.tools import web_fetch as web_fetch_module

    cap = 2048
    monkeypatch.setattr(web_fetch_module, "MAX_RESPONSE_BYTES", cap)

    class _CapCheckedBuffer(bytearray):
        def extend(self, chunk: bytes) -> None:
            assert len(self) + len(chunk) <= cap, "buffer exceeded the cap at extend time"
            super().extend(chunk)

    # ``bytearray`` resolves through builtins at call time; shadowing it in
    # the module namespace swaps the buffer the provider allocates.
    monkeypatch.setattr(deepseek_module, "bytearray", _CapCheckedBuffer, raising=False)

    response = _StubStreamResponse(chunks=[b"x" * 1000 for _ in range(10)])
    make, created = _factory(response)

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/huge", client_factory=make)

    assert excinfo.value.retryable is True
    assert "exceeds" in excinfo.value.message
    # 1000-byte chunks under a 2048 cap: chunk 3 would push past the cap, so
    # reading stops there — chunks 4-10 are never pulled from the response.
    assert response.chunks_consumed == 3
    ((url, kwargs),) = created["client"].calls
    assert kwargs["headers"]["Accept-Encoding"] == "identity"


@pytest.mark.asyncio
async def test_deepseek_gzip_response_is_rejected_without_decompression(monkeypatch) -> None:
    """A compressed body that would decompress past the cap is refused before
    any byte is read, so nothing inflates it in memory."""
    import gzip

    from deeptutor.tools import web_fetch as web_fetch_module

    cap = 2048
    monkeypatch.setattr(web_fetch_module, "MAX_RESPONSE_BYTES", cap)

    # Repetitive data compresses far below the cap but expands to 50x it.
    compressed = gzip.compress(b"x" * (cap * 50))
    assert len(compressed) < cap
    response = _StubStreamResponse(
        chunks=[compressed],
        headers={"content-encoding": "gzip"},
    )
    make, _created = _factory(response)

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider().fetch("https://example.com/zipped", client_factory=make)

    assert excinfo.value.retryable is True
    assert "compressed" in excinfo.value.message
    assert response.chunks_consumed == 0  # rejected before reading the body


# ---------------------------------------------------------------------------
# Log redaction — exception text must never carry credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepseek_network_error_message_is_redacted() -> None:
    api_key = "sk-deepseek-real-key-42"
    poisoned = (
        f"401 from gateway; Authorization: Bearer sk-secret-bearer-token-99 rejected key {api_key}"
    )
    make, _created = _factory(httpx.ConnectError(poisoned))

    with pytest.raises(FetchProviderError) as excinfo:
        await _provider(api_key=api_key).fetch("https://example.com/", client_factory=make)

    message = excinfo.value.message
    assert "sk-secret-bearer-token-99" not in message
    assert api_key not in message
    assert "Bearer ***" in message


def test_redact_fetch_error_masks_bearer_and_sk_tokens_and_caps_length() -> None:
    text = (
        "Authorization: Bearer sk-abcdefghijklmnop entry sk-tiny-key-1 "
        "plus a very long tail " + "z" * 500
    )
    redacted = redact_fetch_error(text)

    assert "sk-abcdefghijklmnop" not in redacted
    assert "sk-tiny-key-1" not in redacted
    assert "Bearer ***" in redacted
    assert len(redacted) <= 200


def test_redact_fetch_error_includes_exception_type() -> None:
    redacted = redact_fetch_error(httpx.ReadTimeout("timed out"))
    assert redacted.startswith("ReadTimeout:")


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
