from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from deeptutor.core.agentic.labeled_step import AgenticModelError, LabeledStepResult
from deeptutor.core.agentic.loop import LabelProtocol, LoopRetryPolicy, run_agentic_loop
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.agentic.tool_dispatch import DispatchOutcome
from deeptutor.core.agentic.client import _ProviderOpenAIAdapter
from deeptutor.services.llm.provider_core.unified import (
    LLMTransport, PROTOCOL_RESPONSES, TransportError, UnifiedLLMAdapter,
)


class _Host:
    async def guard_context_window(self, messages): pass
    def build_iteration_trace_meta(self, iteration): return ({}, {})
    async def dispatch_tools(self, **kwargs): return DispatchOutcome(sources=[], tool_messages=[])
    async def resolve_pause(self, dispatch): return False
    async def emit_terminator(self, payload): pass
    async def emit_final(self, text, meta): pass
    def protocol_retry_notice(self): return "retry"
    def protocol_repair_message(self, violation): return violation
    async def force_finalize(self, **kwargs): return ("", False, 0)


_PROTOCOL = LabelProtocol(allowed=("FINISH",), terminal=frozenset({"FINISH"}), intermediate=frozenset(), final=frozenset({"FINISH"}), tool_label=None)


async def _run(monkeypatch, scripted, kwargs):
    calls = []
    bus = StreamBus()
    async def fake_step(**call_kwargs):
        calls.append(dict(call_kwargs["completion_kwargs"]))
        item = scripted.pop(0)
        if isinstance(item, BaseException): raise item
        return item
    monkeypatch.setattr("deeptutor.core.agentic.loop.run_labeled_step", fake_step)
    await run_agentic_loop(initial_messages=[{"role": "user", "content": "x"}], protocol=_PROTOCOL, client=object(), model="x", completion_kwargs=kwargs, binding="openai", tool_schemas=None, stream=bus, source="t", stage="t", max_iterations=1, host=_Host(), retry_policy=LoopRetryPolicy(max_output_tokens=200, delays=(0, 0, 0), sleep=lambda _: _noop()))
    return calls, bus


async def _noop(): pass


@pytest.mark.asyncio
async def test_max_completion_budget_escalates_once(monkeypatch):
    incomplete = AgenticModelError(
        "model_output_incomplete", "x", retryable=True,
        normalized_result={
            "termination": {
                "provider_status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            }
        },
    )
    calls, bus = await _run(monkeypatch, [incomplete, LabeledStepResult(label="FINISH", text="ok")], {"max_completion_tokens": 100})
    assert calls == [{"max_completion_tokens": 100}, {"max_completion_tokens": 200}]
    [retry] = [event for event in bus._history if event.metadata.get("trace_kind") == "automatic_retry"]
    assert {key: retry.metadata[key] for key in (
        "trace_kind", "retry_index", "reason", "original_budget", "retry_budget"
    )} == {
        "trace_kind": "automatic_retry", "retry_index": 1,
        "reason": "max_output_tokens", "original_budget": 100,
        "retry_budget": 200,
    }


@pytest.mark.asyncio
async def test_transient_retries_three_times_then_succeeds(monkeypatch):
    calls, bus = await _run(monkeypatch, [TimeoutError("secret"), TimeoutError("secret"), TimeoutError("secret"), LabeledStepResult(label="FINISH", text="ok")], {"max_tokens": 100})
    assert len(calls) == 4
    retries = [event for event in bus._history if event.metadata.get("trace_kind") == "automatic_retry"]
    assert [event.metadata["retry_index"] for event in retries] == [1, 2, 3]
    assert all(event.metadata["reason"] == "transport_transient" for event in retries)
    assert "secret" not in repr(retries)


@pytest.mark.asyncio
async def test_auth_and_empty_are_not_retried(monkeypatch):
    class AuthError(RuntimeError): status_code = 401
    with pytest.raises(AuthError): await _run(monkeypatch, [AuthError()], {"max_tokens": 100})
    empty = AgenticModelError("model_output_empty", "x", retryable=False, normalized_result={})
    with pytest.raises(AgenticModelError): await _run(monkeypatch, [empty], {"max_tokens": 100})


class _SequencedResponsesTransport(LLMTransport):
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = list(statuses)
        self.calls = 0

    async def request_json(self, method, path, body, headers=None):
        raise AssertionError("stream path expected")

    async def request_json_lines(
        self, method: str, path: str, body: dict[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        if self.statuses:
            raise TransportError("private provider body", status_code=self.statuses.pop(0))
        yield {"type": "response.created", "response": {"id": "resp_ok", "model": "gpt-x"}}
        yield {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "FINISH\nok"}
        yield {
            "type": "response.completed",
            "response": {
                "id": "resp_ok", "model": "gpt-x", "status": "completed",
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        }


def _non_strict_responses_client(transport: LLMTransport) -> _ProviderOpenAIAdapter:
    provider = UnifiedLLMAdapter(
        protocol=PROTOCOL_RESPONSES, transport=transport, strict_protocol=False,
        default_model="gpt-x", provider="openai", api_key="test-key",
    )
    return _ProviderOpenAIAdapter(provider)


@pytest.mark.parametrize("status_code", [429, 500])
@pytest.mark.asyncio
async def test_actual_non_strict_responses_transient_retries_once_then_succeeds(
    status_code: int,
) -> None:
    transport = _SequencedResponsesTransport([status_code])
    bus = StreamBus()

    outcome = await run_agentic_loop(
        initial_messages=[{"role": "user", "content": "x"}], protocol=_PROTOCOL,
        client=_non_strict_responses_client(transport), model="gpt-x",
        completion_kwargs={"max_tokens": 100}, binding="openai", tool_schemas=None,
        stream=bus, source="t", stage="t", max_iterations=1, host=_Host(),
        retry_policy=LoopRetryPolicy(delays=(0,), max_output_tokens=100, sleep=lambda _: _noop()),
    )

    assert outcome.completed is True
    assert transport.calls == 2
    [retry] = [event for event in bus._history if event.metadata.get("trace_kind") == "automatic_retry"]
    assert retry.metadata["reason"] == "transport_transient"
    assert "private provider body" not in repr(retry.to_dict())


@pytest.mark.asyncio
async def test_actual_non_strict_responses_auth_is_not_retried() -> None:
    transport = _SequencedResponsesTransport([401])

    with pytest.raises(AgenticModelError) as excinfo:
        await run_agentic_loop(
            initial_messages=[{"role": "user", "content": "x"}], protocol=_PROTOCOL,
            client=_non_strict_responses_client(transport), model="gpt-x",
            completion_kwargs={"max_tokens": 100}, binding="openai", tool_schemas=None,
            stream=StreamBus(), source="t", stage="t", max_iterations=1, host=_Host(),
            retry_policy=LoopRetryPolicy(delays=(0,), max_output_tokens=100, sleep=lambda _: _noop()),
        )

    assert excinfo.value.code == "model_provider_failed"
    assert excinfo.value.retryable is False
    assert excinfo.value.normalized_result["termination"]["status_code"] == 401
    assert transport.calls == 1
