from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI
import pytest

from deeptutor.services.llm.provider_core import github_copilot_provider as module


@pytest.mark.asyncio
async def test_provider_exchanges_stored_token_before_every_uncached_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchanges = 0
    seen_keys: list[str] = []

    async def exchange(github_token):
        assert github_token == "owner-token"
        nonlocal exchanges
        exchanges += 1
        return SimpleNamespace(
            token="copilot-access",
            expires_at=2_000_000_000,
            api_base="https://tenant.example",
        )

    async def models(_access):
        return [module.CopilotModel("gpt-4.1")]

    async def chat(self, **_kwargs):
        seen_keys.append(self.api_key)
        return SimpleNamespace(content="ok")

    monkeypatch.setattr(module, "exchange_copilot_token", exchange)
    monkeypatch.setattr(module, "fetch_github_copilot_models", models)
    monkeypatch.setattr(
        module,
        "get_github_copilot_storage",
        lambda: SimpleNamespace(load=lambda: SimpleNamespace(access="owner-token")),
    )
    monkeypatch.setattr(module.OpenAICompatProvider, "chat", chat)

    provider = module.GitHubCopilotProvider()
    assert provider._key_pool is None
    await provider.chat(messages=[{"role": "user", "content": "hello"}])
    await provider.chat(messages=[{"role": "user", "content": "again"}])

    assert exchanges == 1
    assert seen_keys == ["copilot-access", "copilot-access"]
    assert provider.api_base == "https://tenant.example"
    assert provider._effective_base == "https://tenant.example"
    assert str(provider._client.base_url) == "https://tenant.example/"
    await provider.aclose()


async def _provider_with_transport(monkeypatch, handler, catalog):
    async def exchange(_token):
        return SimpleNamespace(
            token="copilot-access",
            expires_at=2_000_000_000,
            api_base="https://tenant.example",
        )

    async def models(_access):
        return catalog

    monkeypatch.setattr(module, "exchange_copilot_token", exchange)
    monkeypatch.setattr(module, "fetch_github_copilot_models", models)
    monkeypatch.setattr(
        module,
        "get_github_copilot_storage",
        lambda: SimpleNamespace(load=lambda: SimpleNamespace(access="owner-token")),
    )
    provider = module.GitHubCopilotProvider()
    await provider.aclose()
    provider._client = AsyncOpenAI(
        api_key="no-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return provider


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "model,endpoints,path",
    [
        ("claude-sonnet", ("/responses",), "/responses"),
        ("gpt-5-chat-only", ("/chat/completions",), "/chat/completions"),
        ("gpt-5", ("/responses", "/chat/completions"), "/responses"),
        ("claude-both", ("/responses", "/chat/completions"), "/chat/completions"),
    ],
)
async def test_model_protocol_metadata_routes_actual_sdk_requests(
    monkeypatch, stream, model, endpoints, path
):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "tenant.example"
        assert request.url.path == path
        assert request.headers["authorization"] == "Bearer copilot-access"
        body = json.loads(request.content)
        assert body["model"] == model
        if stream:
            if path == "/responses":
                events = [
                    {"type": "response.output_text.delta", "delta": "OK"},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_1",
                            "status": "completed",
                            "output": [],
                        },
                    },
                ]
            else:
                events = [
                    {
                        "id": "chat_1",
                        "choices": [
                            {"index": 0, "delta": {"content": "OK"}, "finish_reason": "stop"}
                        ],
                    }
                ]
            content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=content + "data: [DONE]\n\n",
            )
        if path == "/responses":
            return httpx.Response(
                200,
                json={
                    "id": "resp_1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "OK"}],
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chat_1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    provider = await _provider_with_transport(
        monkeypatch, handler, [module.CopilotModel(model, endpoints)]
    )
    # A Responses-only model must not be redirected by the heuristic circuit breaker.
    provider._responses_circuit_allows = lambda *args: False if len(endpoints) == 1 else True
    try:
        method = provider.chat_stream if stream else provider.chat
        response = await method(
            messages=[{"role": "user", "content": "hi"}], model=f"github-copilot/{model}"
        )
        assert response.finish_reason != "error", response.content
        assert response.content == "OK"
        assert len(calls) == 1
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_responses_only_error_never_falls_back_to_chat(monkeypatch, stream):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(400, json={"error": {"message": "responses unavailable"}})

    provider = await _provider_with_transport(
        monkeypatch, handler, [module.CopilotModel("claude", ("/responses",))]
    )
    try:
        method = provider.chat_stream if stream else provider.chat
        response = await method(messages=[], model="claude")
        assert response.finish_reason == "error"
        assert calls == ["/responses"]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_unavailable_model_does_not_send_inference(monkeypatch, stream):
    provider = await _provider_with_transport(
        monkeypatch, lambda request: pytest.fail("unavailable model was requested"), []
    )
    try:
        method = provider.chat_stream if stream else provider.chat
        response = await method(messages=[], model="removed-model")
        assert response.finish_reason == "error"
        assert "not currently available" in response.content
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_refresh_changes_endpoint_and_keeps_original_owner(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers["authorization"]))
        assert request.url.path == "/api/chat/completions"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}
        )

    provider = await _provider_with_transport(
        monkeypatch, handler, [module.CopilotModel("gpt-4.1", ("/chat/completions",))]
    )
    count = 0

    async def exchange(token):
        nonlocal count
        assert token == "owner-token"
        count += 1
        return SimpleNamespace(
            token=f"token-{count}",
            expires_at=2_000_000_000,
            api_base=f"https://tenant-{count}.example/api",
        )

    monkeypatch.setattr(module, "exchange_copilot_token", exchange)
    try:
        await provider.chat(messages=[])
        # A later request context must not change the owner attached to the provider.
        monkeypatch.setattr(
            module, "get_github_copilot_storage", lambda: pytest.fail("wrong owner")
        )
        provider._copilot_expires_at = 0
        await provider.chat(messages=[])
        assert seen == [
            ("tenant-1.example", "Bearer token-1"),
            ("tenant-2.example", "Bearer token-2"),
        ]
        assert provider.api_base == provider._effective_base == "https://tenant-2.example/api"
        assert str(provider._client.base_url) == "https://tenant-2.example/api/"
    finally:
        await provider.aclose()
