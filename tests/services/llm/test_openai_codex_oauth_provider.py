from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, AsyncIterator

import httpcore
import httpx
import pytest

from deeptutor.services.codex_auth.constants import CODEX_RESPONSES_URL
from deeptutor.services.codex_auth.contracts import CodexAuthError, CodexToken
from deeptutor.services.llm.exceptions import LLMProviderTransportError
from deeptutor.services.llm.provider_core import openai_codex_provider as module
from deeptutor.services.llm.provider_core.openai_codex_provider import (
    CodexHTTPError,
    OpenAICodexProvider,
)


class FakeCodexService:
    def __init__(self) -> None:
        self.token = CodexToken(
            access_token="test-access-token",
            account_id="account-123",
            expires_at=2_000_000_000,
            generation=7,
        )
        self.token_calls = 0
        self.guard_entries = 0
        self.recovered_generation: int | None = None
        self.marked_reauth: bool = False
        self.runtime_validations: list[tuple[CodexToken, str, str | None]] = []

    async def get_token(self) -> CodexToken:
        self.token_calls += 1
        return self.token

    async def recover_after_unauthorized(self, generation: int) -> None:
        self.recovered_generation = generation

    def validate_runtime_profile(
        self,
        token: CodexToken,
        model_slug: str,
        reasoning_effort: str | None,
    ) -> None:
        self.runtime_validations.append((token, model_slug, reasoning_effort))

    def mark_reauth_required(self) -> None:
        self.marked_reauth = True

    @asynccontextmanager
    async def inference_guard(self) -> AsyncIterator[None]:
        self.guard_entries += 1
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_slug", "reasoning_effort"),
    [("gpt-5.6-sol", "medium"), ("gpt-5.6-luna", "none")],
)
async def test_provider_uses_deeptutor_token_service_and_raw_model_id(
    monkeypatch: pytest.MonkeyPatch,
    model_slug: str,
    reasoning_effort: str,
) -> None:
    service = FakeCodexService()
    requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    async def request(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        requests.append((url, headers, body))
        return "ok", [], "stop"

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", request)

    image_url = "data:image/png;base64,QUJD"
    result = await OpenAICodexProvider().chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        model=f"openai-codex/{model_slug}",
        reasoning_effort=reasoning_effort,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look something up",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    url, headers, body = requests[0]
    assert result.finish_reason == "stop"
    assert service.token_calls == 1
    assert service.guard_entries == 1
    assert service.runtime_validations == [(service.token, model_slug, reasoning_effort)]
    assert url == CODEX_RESPONSES_URL
    assert headers["Authorization"] == "Bearer test-access-token"
    assert headers["chatgpt-account-id"] == "account-123"
    assert body["model"] == model_slug
    assert body["reasoning"] == {"effort": reasoning_effort}
    assert body["tools"][0]["name"] == "lookup"
    assert body["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "describe"},
                {"type": "input_image", "image_url": image_url, "detail": "auto"},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_401_refreshes_for_next_request_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()
    request_count = 0

    async def rejected_request(*_args: Any, **_kwargs: Any) -> tuple[str, list[Any], str]:
        nonlocal request_count
        request_count += 1
        raise CodexHTTPError(401, module._friendly_error(401))

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", rejected_request)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )

    assert request_count == 1
    assert service.recovered_generation == service.token.generation
    assert result.finish_reason == "error"
    assert "retry" in result.content.lower()


@pytest.mark.asyncio
async def test_401_with_dead_refresh_token_does_not_promise_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telling the user "already refreshed, retry" would loop them forever."""
    service = FakeCodexService()

    async def failed_recovery(generation: int) -> None:
        raise CodexAuthError(
            "authentication_required",
            "Sign in to Codex before using this model.",
            401,
        )

    async def rejected_request(*_args: Any, **_kwargs: Any) -> tuple[str, list[Any], str]:
        raise CodexHTTPError(401, module._friendly_error(401))

    service.recover_after_unauthorized = failed_recovery  # type: ignore[method-assign]
    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", rejected_request)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )

    assert result.finish_reason == "error"
    assert "retry" not in result.content.lower()
    assert "sign in again" in result.content.lower()


@pytest.mark.asyncio
async def test_403_does_not_mark_reauth_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 may be model access denial, not a revoked OAuth grant."""
    service = FakeCodexService()

    async def rejected_request(*_args: Any, **_kwargs: Any) -> tuple[str, list[Any], str]:
        raise CodexHTTPError(403, module._friendly_error(403))

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", rejected_request)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )

    assert result.finish_reason == "error"
    assert "account" in result.content.lower()
    assert service.marked_reauth is False


@pytest.mark.asyncio
async def test_429_never_reads_openai_api_key_or_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()
    destinations: list[str] = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")

    async def rate_limited(
        url: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        destinations.append(url)
        raise CodexHTTPError(429, "Codex usage quota exceeded.")

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", rate_limited)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )

    assert "Codex usage quota" in result.content
    assert destinations == [CODEX_RESPONSES_URL]
    assert service.token_calls == 1


@pytest.mark.asyncio
async def test_provider_does_not_expose_network_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()

    async def network_failure(
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        raise RuntimeError("private proxy host and token")

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", network_failure)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
    )

    assert result.finish_reason == "error"
    assert "private proxy" not in result.content
    assert "token" not in result.content.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [
        httpx.RemoteProtocolError("private proxy host and token"),
        httpcore.RemoteProtocolError("private proxy host and token"),
    ],
)
async def test_transport_failure_raises_sanitized_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
    transport_error: Exception,
) -> None:
    service = FakeCodexService()
    sensitive_message = "private proxy host and token"

    async def transport_failure(
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        raise transport_error

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", transport_failure)

    with pytest.raises(LLMProviderTransportError) as exc_info:
        await OpenAICodexProvider().chat(
            [{"role": "user", "content": "hello"}],
        )

    assert str(exc_info.value) == "Codex transport request failed."
    assert sensitive_message not in str(exc_info.value)
    assert exc_info.value.__cause__ is transport_error


def test_provider_source_no_longer_imports_oauth_cli_kit() -> None:
    source = module.__loader__.get_source(module.__name__)  # type: ignore[union-attr]

    assert source is not None
    assert "oauth_cli_kit" not in source
    assert "get_codex_oauth_service" in source
    assert OpenAICodexProvider().get_default_model() == "openai-codex/gpt-5.6-sol"


def _summary_messages(summary: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "Tutor instructions"},
        {"role": "system", "content": summary},
        {"role": "user", "content": "Q"},
    ]


def test_prompt_cache_key_is_stable_across_summary_updates() -> None:
    key_a = module._prompt_cache_key(_summary_messages("Summary A"))
    key_b = module._prompt_cache_key(_summary_messages("Summary B"))

    assert key_a == key_b


def test_prompt_cache_key_differs_for_different_instructions() -> None:
    other = _summary_messages("Summary A")
    other[0]["content"] = "Other instructions"

    assert module._prompt_cache_key(other) != module._prompt_cache_key(
        _summary_messages("Summary A")
    )


@pytest.mark.asyncio
async def test_session_id_header_matches_body_prompt_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()
    requests: list[tuple[dict[str, str], dict[str, Any]]] = []

    async def request(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        requests.append((headers, body))
        return "ok", [], "stop"

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", request)

    provider = OpenAICodexProvider()
    await provider.chat(_summary_messages("Summary A"), model="openai-codex/gpt-5.6-sol")
    await provider.chat(_summary_messages("Summary B"), model="openai-codex/gpt-5.6-sol")

    for headers, body in requests:
        assert headers["session-id"] == body["prompt_cache_key"]
    assert requests[0][0]["session-id"] == requests[1][0]["session-id"]


def test_prompt_cache_key_is_scoped_by_session_id() -> None:
    messages = _summary_messages("Summary A")

    key_a = module._prompt_cache_key(messages, "session-a")
    key_b = module._prompt_cache_key(messages, "session-b")

    assert key_a != key_b
    assert "session-a" not in key_a
    # A summary change inside one conversation must not move the key.
    assert key_a == module._prompt_cache_key(_summary_messages("Summary B"), "session-a")
    assert key_a != module._prompt_cache_key(messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_session_id_kwarg_scopes_header_and_body(
    monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    service = FakeCodexService()
    requests: list[tuple[dict[str, str], dict[str, Any]]] = []

    async def request(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        requests.append((headers, body))
        return "ok", [], "stop"

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", request)

    provider = OpenAICodexProvider()
    call = provider.chat_stream if stream else provider.chat
    for session in ("session-a", "session-b"):
        await call(
            _summary_messages("Summary A"),
            model="openai-codex/gpt-5.6-sol",
            deeptutor_session_id=session,
        )

    for headers, body in requests:
        assert headers["session-id"] == body["prompt_cache_key"]
    assert requests[0][1]["prompt_cache_key"] != requests[1][1]["prompt_cache_key"]


def test_openai_codex_binding_threads_session_id() -> None:
    from deeptutor.services.llm.capabilities import threads_session_id

    assert threads_session_id("openai_codex")


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [None, False, True])
async def test_codex_preserves_optional_tool_parameters(monkeypatch, strict):
    service = FakeCodexService()
    captured = []

    async def request(url, headers, body, **kwargs):
        captured.append(body)
        return "ok", [], "stop"

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", request)
    function = {
        "name": "mastery_quiz",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "resume_question_id": {"type": "string"},
                "visual": {"type": "object", "properties": {"sources": {"type": "array"}}},
            },
            "required": ["question"],
        },
    }
    if strict is not None:
        function["strict"] = strict
    tools = [{"type": "function", "function": function}]
    before = deepcopy(tools)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "Give me a text-only question."}], tools=tools
    )

    assert result.content == "ok"
    outgoing = captured[0]["tools"][0]
    assert outgoing["strict"] is (strict if strict is not None else False)
    assert outgoing["parameters"]["required"] == ["question"]
    assert outgoing["parameters"] == function["parameters"]
    assert tools == before


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_custom_headers_reach_codex_http_without_replacing_oauth_identity(
    monkeypatch: pytest.MonkeyPatch, streaming: bool
) -> None:
    service = FakeCodexService()
    captured: list[httpx.Request] = []
    actual_client = httpx.AsyncClient

    def upstream(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"type":"response.output_text.delta","delta":"ok"}\n\n'
            'data: {"type":"response.completed","response":{"output":[]}}\n\n',
        )

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: actual_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    configured = {
        "User-Agent": "fixture-client",
        "X-Trace": "profile",
        "ORIGINATOR": "fixture-origin",
    }
    provider = OpenAICodexProvider(extra_headers=configured)
    call = provider.chat_stream if streaming else provider.chat
    result = await call(
        [{"role": "user", "content": "hello"}],
        deeptutor_session_id="conversation-one",
        extra_headers={
            "x-trace": "call",
            "x-codex-turn-metadata": "fixture-metadata",
            "authorization": "Bearer wrong",
            "CHATGPT-ACCOUNT-ID": "wrong",
            "Cookie": "wrong",
            "Host": "wrong",
            "Content-Type": "text/plain",
            "session-id": "wrong",
            "Content-Length": "0",
        },
    )
    assert result.content == "ok"
    headers = captured[0].headers
    assert headers["user-agent"] == "fixture-client"
    assert headers["originator"] == "fixture-origin"
    assert headers["x-trace"] == "call"
    assert headers.get_list("x-trace") == ["call"]
    assert headers["x-codex-turn-metadata"] == "fixture-metadata"
    assert headers["authorization"] == "Bearer test-access-token"
    assert headers["chatgpt-account-id"] == "account-123"
    assert "cookie" not in headers
    assert headers["host"] == "chatgpt.com"
    assert headers["content-type"] == "application/json"
    assert headers["session-id"] == module._prompt_cache_key([], "conversation-one")
    assert configured == {
        "User-Agent": "fixture-client",
        "X-Trace": "profile",
        "ORIGINATOR": "fixture-origin",
    }


def test_services_factory_preserves_codex_headers() -> None:
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.provider_factory import _build_runtime_provider

    config = LLMConfig(
        binding="openai_codex",
        api_key="unused",
        provider_name="openai_codex",
        model="gpt-test",
        extra_headers={"X-Trace": "factory"},
    )
    provider = _build_runtime_provider(config, native_enabled=False)
    assert isinstance(provider, OpenAICodexProvider)
    assert provider.extra_headers == {"X-Trace": "factory"}


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_responses_gateway_preserves_configured_and_call_headers(streaming: bool) -> None:
    import json

    from openai import AsyncOpenAI

    from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider

    captured: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        response = {"id": "resp-fixture", "object": "response", "status": "completed", "output": []}
        if json.loads(request.content).get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="data: "
                + json.dumps({"type": "response.completed", "response": response})
                + "\n\n",
            )
        return httpx.Response(200, json=response)

    configured = {
        "User-Agent": "fixture-client",
        "originator": "fixture-origin",
        "X-Trace": "profile",
    }
    provider = OpenAICompatProvider(
        api_key="gateway-test-key",
        api_base="https://gateway.test/v1",
        wire_api="responses",
        extra_headers=configured,
    )
    await provider._client.close()
    provider._client = AsyncOpenAI(
        api_key="gateway-test-key",
        base_url="https://gateway.test/v1",
        default_headers=configured,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    try:
        await (provider.chat_stream if streaming else provider.chat)(
            [{"role": "user", "content": "hello"}],
            extra_headers={"X-Trace": "call", "x-codex-turn-metadata": "fixture-metadata"},
        )
        assert len(captured) == 1
        assert captured[0].url.path == "/v1/responses"
        assert captured[0].headers["user-agent"] == "fixture-client"
        assert captured[0].headers["originator"] == "fixture-origin"
        assert captured[0].headers["x-trace"] == "call"
        assert captured[0].headers["x-codex-turn-metadata"] == "fixture-metadata"
        assert captured[0].headers["authorization"] == "Bearer gateway-test-key"
        assert "extra_headers" not in json.loads(captured[0].content)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["chat", "chat_stream"])
@pytest.mark.parametrize(
    ("requested", "supported", "expected"),
    [
        ("none", ["low", "medium", "high"], "low"),
        ("none", ["high", "medium", "low"], "low"),
        ("none", ["minimal", "low"], "minimal"),
        ("none", ["medium", "high"], "medium"),
        ("minimal", ["low", "medium"], "low"),
        ("none", ["none", "low"], "none"),
        ("minimal", ["minimal", "low"], "minimal"),
        ("high", ["low", "high"], "high"),
        ("future-effort", ["low"], "future-effort"),
        (None, ["low"], None),
        ("none", None, "none"),
        ("none", [], "none"),
        ("none", "low", "none"),
        ("none", ["future-effort"], "none"),
    ],
)
async def test_provider_respects_model_reasoning_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    requested: str | None,
    supported: object,
    expected: str | None,
) -> None:
    """Book callers can request no reasoning on a model whose minimum is low."""
    from deeptutor.multi_user import personal_models

    service = FakeCodexService()
    catalog = {
        "services": {
            "llm": {
                "profiles": [
                    {
                        "models": [
                            {
                                "model": "requested-model",
                                "codex_supported_reasoning_levels": ["none"],
                            }
                        ],
                    },
                    {
                        "managed_by": "openai_codex_oauth",
                        "models": [
                            {"model": "other-model", "codex_supported_reasoning_levels": ["none"]},
                            {
                                "model": "requested-model",
                                "codex_supported_reasoning_levels": supported,
                            },
                        ],
                    },
                ],
            },
        },
    }
    requests: list[dict[str, Any]] = []

    def load_catalog() -> dict[str, Any]:
        assert service.runtime_validations == [(service.token, "requested-model", requested)]
        return catalog

    async def request(
        _url: str,
        _headers: dict[str, str],
        body: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        requests.append(body)
        return "visible content", [], "stop"

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    # Patch the shared owner lookup so this test also runs against the old
    # provider: it must fail on the outgoing effort, not a missing helper.
    monkeypatch.setattr(
        personal_models, "owner_catalog_service", lambda: SimpleNamespace(load=load_catalog)
    )
    monkeypatch.setattr(module, "_request_codex", request)
    result = await getattr(OpenAICodexProvider(), method)(
        [{"role": "user", "content": "Write a short Python example."}],
        model="openai-codex/requested-model",
        reasoning_effort=requested,
    )

    assert result.content == "visible content"
    assert len(requests) == 1
    assert requests[0]["model"] == "requested-model"
    if expected is None:
        assert "reasoning" not in requests[0]
    else:
        assert requests[0]["reasoning"] == {"effort": expected}


@pytest.mark.asyncio
async def test_unsupported_reasoning_does_not_bypass_account_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.multi_user import personal_models

    service = FakeCodexService()

    def reject_profile(*_args: Any) -> None:
        raise CodexAuthError("codex_catalog_unavailable", "Refresh Codex models.", 409)

    def forbidden_lookup() -> None:
        pytest.fail("Rejected account/model must not reach capability lookup")

    async def forbidden_request(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("Rejected account/model must not reach the network")

    monkeypatch.setattr(service, "validate_runtime_profile", reject_profile)
    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(personal_models, "owner_catalog_service", forbidden_lookup)
    monkeypatch.setattr(module, "_request_codex", forbidden_request)
    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="requested-model",
        reasoning_effort="none",
    )

    assert result.finish_reason == "error"
    assert "Refresh Codex models" in result.content
