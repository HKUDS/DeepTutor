"""Cover optional replay status removal and the bounded gateway fallback.

Custom Responses gateways can reject optional status fields on messages,
reasoning and function calls inside an HTTP-200 stream. Requests omit those
fields while preserving replay content and status required by other item
kinds. The HTTP-error fallback remains bounded to one retry.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import httpx
from openai import AsyncOpenAI
import pytest

from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name

pytestmark = pytest.mark.asyncio


class _RejectedParameter(Exception):
    """Stand in for the SDK error, which exposes ``body`` and a status code."""

    def __init__(self, param: str, *, status_code: int = 400, code: str = "unknown_parameter"):
        super().__init__(param)
        self.status_code = status_code
        self.body = {"error": {"code": code, "param": param, "type": "invalid_request_error"}}


def _provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        api_key="test-key",
        api_base="https://gateway.example/v1",
        default_model="responses-only-model",
        spec=find_by_name("custom"),
        provider_name="custom",
        wire_api="responses",
    )


def _body(*, statuses: bool = True) -> dict[str, Any]:
    def message(role: str, text: str) -> dict[str, Any]:
        item: dict[str, Any] = {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text", "text": text}],
        }
        if statuses:
            item["status"] = "completed"
        return item

    return {
        "model": "responses-only-model",
        "input": [
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
            message("user", "first"),
            message("assistant", "second"),
        ],
    }


def _recorder(fail_on: set[int], error: Exception | None = None):
    """Return (create, calls): fail the listed attempts, else answer OK."""
    calls: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> str:
        calls.append(kwargs)
        if len(calls) in fail_on:
            raise error or _RejectedParameter("input[2].status")
        return "ok"

    return create, calls


async def test_a_rejected_status_is_stripped_and_the_call_retried_once() -> None:
    provider = _provider()
    create, calls = _recorder(fail_on={1})
    provider._client.responses.create = create

    assert await provider._create_responses_with_status_retry(_body()) == "ok"

    assert len(calls) == 2
    # Every message item loses ``status``, not only the one the gateway named:
    # a second round trip per item would be the same bug, N times over.
    assert all("status" not in item for item in calls[1]["input"] if item["type"] == "message")
    # Items of other kinds are passed through untouched.
    assert calls[1]["input"][0] == {"type": "function_call_output", "call_id": "c1", "output": "ok"}
    # The caller's body is not mutated.
    assert all("status" in item for item in calls[0]["input"] if item["type"] == "message")


async def test_the_model_is_remembered_so_the_next_turn_costs_one_call() -> None:
    provider = _provider()
    create, calls = _recorder(fail_on={1})
    provider._client.responses.create = create

    await provider._create_responses_with_status_retry(_body())
    assert await provider._create_responses_with_status_retry(_body()) == "ok"

    assert len(calls) == 3
    assert all("status" not in item for item in calls[2]["input"] if item["type"] == "message")


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(_RejectedParameter("input[1].status", status_code=500), id="server-error"),
        pytest.param(_RejectedParameter("temperature"), id="another-parameter"),
        pytest.param(
            _RejectedParameter("input[1].status", code="invalid_value"), id="another-code"
        ),
        pytest.param(RuntimeError("transport died"), id="not-an-api-error"),
    ],
)
async def test_an_unrelated_failure_is_raised_rather_than_retried(error: Exception) -> None:
    provider = _provider()
    create, calls = _recorder(fail_on={1}, error=error)
    provider._client.responses.create = create

    with pytest.raises(type(error)):
        await provider._create_responses_with_status_retry(_body())

    assert len(calls) == 1


async def test_a_body_with_nothing_to_strip_reports_the_original_failure() -> None:
    provider = _provider()
    create, calls = _recorder(fail_on={1})
    provider._client.responses.create = create

    with pytest.raises(_RejectedParameter):
        await provider._create_responses_with_status_retry(_body(statuses=False))

    assert len(calls) == 1
    assert "responses-only-model" not in provider._responses_without_optional_status_models


async def test_a_second_rejection_is_not_retried_again() -> None:
    provider = _provider()
    create, calls = _recorder(fail_on={1, 2})
    provider._client.responses.create = create

    with pytest.raises(_RejectedParameter):
        await provider._create_responses_with_status_retry(_body())

    assert len(calls) == 2


async def test_status_is_preserved_for_items_where_it_is_required() -> None:
    provider = _provider()
    item = {"type": "web_search_call", "id": "ws_1", "status": "completed"}
    body = {"input": [item, *_body()["input"]]}

    sanitized = provider._responses_body_without_optional_input_status(body)

    assert sanitized["input"][0] == item
    assert provider._responses_body_without_optional_input_status(body, 0) is None
    await provider._client.close()


@pytest.mark.parametrize("method", ["chat", "chat_stream"])
@pytest.mark.parametrize("replay_native_items", [False, True])
async def test_requests_omit_optional_status_before_a_gateway_can_reject_it(
    method: str, replay_native_items: bool
) -> None:
    provider = _provider()
    native_items = [
        {
            "type": "reasoning",
            "id": "rs_1",
            "status": "completed",
            "summary": [],
            "encrypted_content": "opaque-reasoning-state",
        },
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "previous answer"}],
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": "{}",
            "status": "completed",
        },
    ]
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "retry"},
    ]
    if replay_native_items:
        messages[1]["_provider_response_state"] = {"responses_output_items": native_items}
    original = deepcopy(messages)
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        for index, item in enumerate(body["input"]):
            if item.get("type") in {"message", "reasoning", "function_call"} and "status" in item:
                error = {
                    "code": "unknown_parameter",
                    "message": f"Unknown parameter: 'input[{index}].status'.",
                    "param": f"input[{index}].status",
                    "type": "invalid_request_error",
                }
                if body["stream"]:
                    return httpx.Response(
                        200,
                        headers={"content-type": "text/event-stream"},
                        text="event: error\ndata: " + json.dumps({"error": error}) + "\n\n",
                    )
                return httpx.Response(400, json={"error": error})
        response = {
            "id": "resp_1",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                }
            ],
        }
        if not body["stream"]:
            return httpx.Response(200, json=response)
        events = [
            {"type": "response.output_text.delta", "delta": "ok"},
            {"type": "response.completed", "response": response},
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + json.dumps(event) + "\n\n" for event in events),
        )

    await provider._client.close()
    provider._client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        result = await getattr(provider, method)(messages)
    finally:
        await provider._client.close()

    assert result.content == "ok"
    assert result.finish_reason == "stop"
    assert len(requests) == 1
    assert all("status" not in item for item in requests[0]["input"])
    assert messages == original
    if replay_native_items:
        assert requests[0]["input"][1] == {
            key: value for key, value in native_items[0].items() if key != "status"
        }
        assert requests[0]["input"][2] == {
            key: value for key, value in native_items[1].items() if key != "status"
        }
        assert requests[0]["input"][3] == {
            key: value for key, value in native_items[2].items() if key != "status"
        }
