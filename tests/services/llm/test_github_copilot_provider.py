from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI
import pytest

from deeptutor.services.llm.provider_core import github_copilot_provider as module
from deeptutor.services.session.context_builder import ContextBuilder
from deeptutor.services.session.provider_response_state import normalize_provider_response_state
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


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
@pytest.mark.parametrize("replay", [False, True])
async def test_multiturn_responses_omits_output_message_metadata(monkeypatch, stream, replay):
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "Continue"},
    ]
    if replay:
        messages[1]["_provider_response_state"] = {
            "responses_output_items": [
                {
                    "type": "message",
                    "role": "assistant",
                    "id": "msg_previous",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Hi"}],
                },
                {
                    "type": "function_call",
                    "id": "fc_previous",
                    "call_id": "call_previous",
                    "name": "lookup",
                    "arguments": "{}",
                },
            ]
        }
        messages.insert(2, {"role": "tool", "tool_call_id": "call_previous", "content": "result"})
    original = deepcopy(messages)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/responses"
        assistant = body["input"][1]
        assert assistant["role"] == "assistant"
        assert assistant["content"][0]["text"] == "Hi"
        assert "status" not in assistant
        assert "id" not in assistant
        if replay:
            assert body["input"][2]["id"] == "fc_previous"
            assert body["input"][2]["call_id"] == body["input"][3]["call_id"]
        if stream:
            events = [
                {"type": "response.output_text.delta", "delta": "OK"},
                {
                    "type": "response.completed",
                    "response": {"id": "resp_2", "status": "completed", "output": []},
                },
            ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_2",
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

    provider = await _provider_with_transport(
        monkeypatch, handler, [module.CopilotModel("gpt-5", ("/responses",))]
    )
    try:
        method = provider.chat_stream if stream else provider.chat
        response = await method(messages=messages, model="gpt-5")
        assert response.finish_reason != "error", response.content
        assert response.content == "OK"
        assert len(calls) == 1
        assert messages == original
    finally:
        await provider.aclose()


def _reasoning_output(index):
    # Shape observed on Copilot's wire: no status. SDK model_dump adds status=None.
    return {
        "type": "reasoning",
        "id": f"rs_{index}",
        "summary": [],
        "content": [],
        "encrypted_content": f"opaque-test-reasoning-{index}",
    }


def _message_output(index):
    return {
        "type": "message",
        "id": f"msg_{index}",
        "role": "assistant",
        "status": "completed",
        "phase": "final_answer",
        "content": [{"type": "output_text", "text": "OK", "annotations": []}],
    }


def _responses_reply(output, stream):
    response = {"id": "resp_test", "status": "completed", "output": output}
    if not stream:
        return httpx.Response(200, json=response)
    events = []
    for index, item in enumerate(output):
        events.append({"type": "response.output_item.added", "output_index": index, "item": item})
        if item["type"] == "message":
            events.append({"type": "response.output_text.delta", "delta": "OK"})
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": response})
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_four_turn_sqlite_history_replays_sdk_reasoning_without_status(
    monkeypatch, tmp_path, stream
):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        for index, item in enumerate(body["input"]):
            if "status" in item:
                return httpx.Response(
                    400,
                    json={"error": {"message": f"Unknown parameter: 'input[{index}].status'."}},
                )
        turn = len(bodies)
        output = ([] if turn == 1 else [_reasoning_output(turn)]) + [_message_output(turn)]
        return _responses_reply(output, stream)

    store = SQLiteSessionStore(db_path=tmp_path / "copilot-replay.db")
    session = await store.create_session()
    provider = await _provider_with_transport(
        monkeypatch, handler, [module.CopilotModel("gpt-5.6-sol-fast", ("/responses",))]
    )
    try:
        method = provider.chat_stream if stream else provider.chat
        for turn in range(1, 5):
            await store.add_message(session["id"], "user", f"Synthetic turn {turn}")
            stored = await store.get_messages(session["id"])
            history = ContextBuilder(store)._build_history("", stored)
            original = deepcopy(history)
            result = await method(messages=history, model="gpt-5.6-sol-fast")
            assert result.finish_reason == "stop", result.content
            assert history == original
            items = result.provider_specific_fields.get("native_output_items", [])
            if turn >= 2:
                assert items[0]["type"] == "reasoning"
                assert "status" in items[0] and items[0]["status"] is None
                assert items[0]["encrypted_content"] == f"opaque-test-reasoning-{turn}"
            state = normalize_provider_response_state({"responses_output_items": items})
            await store.add_message(
                session["id"],
                "assistant",
                result.content,
                metadata={"provider_response_state": state},
            )
            if turn >= 3:
                reasoning = bodies[-1]["input"][3]
                assert reasoning["type"] == "reasoning"
                assert reasoning["id"] == "rs_2"
                assert reasoning["encrypted_content"] == "opaque-test-reasoning-2"
                assert reasoning["summary"] == []
                assert "status" not in reasoning
                assistant = bodies[-1]["input"][4]
                assert assistant["phase"] == "final_answer"
                assert "id" not in assistant
            persisted = await store.get_messages(session["id"])
            assert persisted[:-1] == stored
            assert persisted[-1]["metadata"]["provider_response_state"] == state
        assert len(bodies) == 4
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_replayed_reasoning_and_tool_rounds_preserve_call_pairing(monkeypatch, stream):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert all(
            "status" not in item
            for item in body["input"]
            if item.get("type") in {"message", "reasoning"}
        )
        for item in body["input"]:
            if item.get("type") == "function_call":
                assert item["status"] == "completed"
                assert item["id"] == f"fc_{item['call_id'].split('_')[-1]}"
                assert item["arguments"] == '{"status":"keep nested argument"}'
                assert any(
                    output.get("type") == "function_call_output"
                    and output["call_id"] == item["call_id"]
                    for output in body["input"]
                )
        turn = len(bodies)
        output = [
            _reasoning_output(turn),
            {
                "type": "function_call",
                "id": f"fc_{turn}",
                "call_id": f"call_{turn}",
                "name": "lookup",
                "arguments": '{"status":"keep nested argument"}',
                "status": "completed",
            },
        ]
        return _responses_reply(output, stream)

    provider = await _provider_with_transport(
        monkeypatch, handler, [module.CopilotModel("gpt-5", ("/responses",))]
    )
    try:
        history = [{"role": "user", "content": "Use lookup"}]
        method = provider.chat_stream if stream else provider.chat
        for turn in range(1, 5):
            original = deepcopy(history)
            result = await method(messages=history, model="gpt-5")
            assert result.finish_reason != "error", result.content
            assert history == original
            items = result.provider_specific_fields["native_output_items"]
            assert items[1]["status"] == "completed"
            call = result.tool_calls[0]
            assert call.id == f"call_{turn}|fc_{turn}"
            history.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "_provider_response_state": {"responses_output_items": items},
                    },
                    {"role": "tool", "tool_call_id": call.id, "content": "Synthetic result"},
                ]
            )
            history = json.loads(json.dumps(history))
        assert len(bodies) == 4
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("override", ["input", "extra_body"])
@pytest.mark.parametrize("reasoning_status", [None, "completed"])
async def test_responses_input_overrides_are_normalized_after_kwargs_merge(
    monkeypatch, stream, override, reasoning_status
):
    items = [
        {"role": "assistant", "id": "msg_raw", "status": "completed", "content": "OK"},
        {**_reasoning_output(1), "status": reasoning_status},
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": "{}",
            "status": "completed",
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "OK", "status": None},
        {"type": "web_search_call", "id": "ws_1", "status": "completed"},
    ]
    kwargs = {"input": items} if override == "input" else {"extra_body": {"input": items}}
    original = deepcopy(kwargs)

    def handler(request):
        body = json.loads(request.content)
        expected = deepcopy(items)
        for item in expected[:2]:
            item.pop("status")
        expected[0].pop("id")
        assert body["input"] == expected
        return _responses_reply([_message_output(1)], stream)

    provider = await _provider_with_transport(
        monkeypatch, handler, [module.CopilotModel("gpt-5", ("/responses",))]
    )
    try:
        method = provider.chat_stream if stream else provider.chat
        result = await method(
            messages=[{"role": "user", "content": "Ignored"}], model="gpt-5", **kwargs
        )
        assert result.finish_reason == "stop", result.content
        assert kwargs == original
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_copilot_normalization_does_not_change_openai_requests(stream):
    items = [{**_reasoning_output(1), "status": None}, _message_output(1)]
    history = [
        {
            "role": "assistant",
            "content": "OK",
            "_provider_response_state": {"responses_output_items": items},
        },
        {"role": "user", "content": "Continue"},
    ]
    original = deepcopy(history)
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert body["input"][:2] == items
        return _responses_reply([_message_output(2)], stream)

    provider = module.OpenAICompatProvider(
        api_key="test-key", wire_api="responses", configure_env=False
    )
    await provider.aclose()
    provider._client = AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        method = provider.chat_stream if stream else provider.chat
        result = await method(messages=history, model="gpt-5")
        assert result.finish_reason == "stop", result.content
        assert len(bodies) == 1
        assert history == original
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
