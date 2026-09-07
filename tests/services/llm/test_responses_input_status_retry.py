"""Cover the one-shot retry for gateways that reject ``input[N].status``.

Some Responses-wire gateways reject the ``status`` field that our replayed
message items carry, with ``unknown_parameter`` naming the offending index.
The provider strips the field and retries once, then remembers the model so
the next turn does not pay a wasted round trip. These tests pin that
behaviour at the request boundary: nothing here should broaden into a
general retry-on-400.
"""

from __future__ import annotations

from typing import Any

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
    assert "responses-only-model" not in provider._responses_without_message_status_models


async def test_a_second_rejection_is_not_retried_again() -> None:
    provider = _provider()
    create, calls = _recorder(fail_on={1, 2})
    provider._client.responses.create = create

    with pytest.raises(_RejectedParameter):
        await provider._create_responses_with_status_retry(_body())

    assert len(calls) == 2
