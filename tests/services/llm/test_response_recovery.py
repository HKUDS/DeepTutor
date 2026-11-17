"""Synthetic provider operations; no network or model calls."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from deeptutor.services.llm.exceptions import LLMOperationPaused
from deeptutor.services.llm.provider_core import response_recovery as recovery
from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
    _SemanticProgress,
)
from deeptutor.services.llm.provider_core.openai_responses import consume_sdk_stream
from deeptutor.services.llm.request_compat import is_transient_transport_error


@pytest.fixture(autouse=True)
def deadlines(monkeypatch):
    monkeypatch.setattr(recovery, "PROGRESS_DEADLINE_S", 0.025)
    monkeypatch.setattr(recovery, "RECOVERY_ALLOWANCE_S", 0.035)
    monkeypatch.setattr(recovery, "LOOKUP_TIMEOUT_S", 0.01)


async def stream(events):
    for event in events:
        yield NS(**event)
    while True:
        await asyncio.sleep(0.002)
        yield NS(type="response.in_progress", response=NS(id="resp_known", status="in_progress"))


def result(status="completed", text="Hello world"):
    return {
        "id": "resp_known",
        "status": status,
        "output": [
            {"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": text}]},
            {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_saved",
                "name": "save_note",
                "arguments": '{"text":"one"}',
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def initial():
    return [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": NS(id="resp_known", status="in_progress"),
        }
    ]


@pytest.mark.asyncio
async def test_retrieves_same_operation_once_and_preserves_content_usage_and_tool_identity():
    retrieve = AsyncMock(return_value=result())
    events = (
        initial() + [dict(type="response.output_text.delta", sequence_number=1, delta="Hello ")] * 2
    )
    seen = []

    async def emit(text):
        seen.append(text)

    parsed = await consume_sdk_stream(
        recovery.guarded_responses(stream(events), progress=_SemanticProgress(), retrieve=retrieve),
        emit,
    )
    assert "".join(seen) == parsed[0] == "Hello world"
    assert [call.id for call in parsed[1]] == ["call_saved|fc_1"]
    assert parsed[3]["completion_tokens"] == 5
    retrieve.assert_awaited_once_with("resp_known")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["in_progress", "failed", "cancelled", "expired"])
async def test_pending_and_terminal_failures_pause_without_submitting_any_replacement(status):
    retrieve = AsyncMock(return_value=result(status))
    with pytest.raises(LLMOperationPaused) as raised:
        await consume_sdk_stream(
            recovery.guarded_responses(
                stream(initial()), progress=_SemanticProgress(), retrieve=retrieve
            )
        )
    assert not is_transient_transport_error(raised.value)
    assert raised.value.retryable is False
    assert retrieve.await_count <= 2


@pytest.mark.asyncio
async def test_unsupported_and_changed_owner_do_not_query():
    retrieve = AsyncMock(return_value=result())
    with pytest.raises(LLMOperationPaused, match="unavailable"):
        await consume_sdk_stream(
            recovery.guarded_responses(stream(initial()), progress=_SemanticProgress())
        )
    calls = 0

    def owner():
        nonlocal calls
        calls += 1
        return "alice" if calls == 1 else "bob"

    with pytest.raises(LLMOperationPaused, match="ownership"):
        await consume_sdk_stream(
            recovery.guarded_responses(
                stream(initial()), progress=_SemanticProgress(), retrieve=retrieve, owner=owner
            )
        )
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_and_query_timeouts_are_bounded_and_cancellation_is_not_recovery():
    async def hung(*args):
        await asyncio.Event().wait()

    with pytest.raises(LLMOperationPaused, match="could not be retrieved"):
        await asyncio.wait_for(
            consume_sdk_stream(
                recovery.guarded_responses(
                    stream(initial()), progress=_SemanticProgress(), retrieve=hung
                )
            ),
            0.2,
        )
    retrieve = AsyncMock(return_value=result())
    task = asyncio.create_task(
        consume_sdk_stream(
            recovery.guarded_responses(
                stream(initial()), progress=_SemanticProgress(), retrieve=retrieve
            )
        )
    )
    await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_mismatched_result_and_output_prefix_are_not_delivered():
    for recovered in [{**result(), "id": "other"}, result(text="Different answer")]:
        events = initial() + [dict(type="response.output_text.delta", delta="Hello ")]
        with pytest.raises(LLMOperationPaused):
            await consume_sdk_stream(
                recovery.guarded_responses(
                    stream(events),
                    progress=_SemanticProgress(),
                    retrieve=AsyncMock(return_value=recovered),
                )
            )


@pytest.mark.asyncio
async def test_official_stored_response_recovery_uses_one_create_and_one_retrieve():
    provider = OpenAICompatProvider(
        api_key="synthetic",
        api_base="https://api.openai.com/v1",
        wire_api="responses",
        default_model="test",
    )
    original = provider._client
    create = AsyncMock(return_value=stream(initial()))
    retrieve = AsyncMock(return_value=result())
    provider._client = NS(
        base_url="https://api.openai.com/v1",
        api_key="synthetic",
        responses=NS(create=create, retrieve=retrieve),
    )
    try:
        response = await provider.chat_stream_with_retry(
            messages=[{"role": "user", "content": "test"}], store=True
        )
        assert response.content == "Hello world"
        assert response.tool_calls[0].id == "call_saved|fc_1"
        assert create.await_count == retrieve.await_count == 1
    finally:
        await original.close()


@pytest.mark.asyncio
async def test_unknown_create_outcome_and_default_private_response_never_retry():
    provider = OpenAICompatProvider(
        api_key="synthetic",
        api_base="https://api.openai.com/v1",
        wire_api="responses",
        default_model="test",
    )
    original = provider._client
    create = AsyncMock(side_effect=TimeoutError())
    retrieve = AsyncMock()
    provider._client = NS(
        base_url="https://api.openai.com/v1",
        api_key="synthetic",
        responses=NS(create=create, retrieve=retrieve),
    )
    try:
        with pytest.raises(LLMOperationPaused, match="unknown"):
            await provider.chat_stream_with_retry(messages=[])
        create.assert_awaited_once()
        create.reset_mock(side_effect=True)
        create.return_value = stream(initial())
        with pytest.raises(LLMOperationPaused, match="unavailable"):
            await provider.chat_stream_with_retry(messages=[])
        assert create.call_args.kwargs["store"] is False
        create.assert_awaited_once()
        retrieve.assert_not_awaited()
    finally:
        await original.close()


@pytest.mark.asyncio
async def test_already_observed_tool_completion_is_not_duplicated_by_lookup():
    events = initial() + [
        dict(
            type="response.output_item.done",
            sequence_number=1,
            item=NS(
                id="fc_1",
                type="function_call",
                call_id="call_saved",
                name="save_note",
                arguments='{"text":"one"}',
            ),
        )
    ]
    parsed = await consume_sdk_stream(
        recovery.guarded_responses(
            stream(events), progress=_SemanticProgress(), retrieve=AsyncMock(return_value=result())
        )
    )
    writes = []
    for call in parsed[1]:
        writes.append((call.id, call.arguments))
    assert writes == [("call_saved|fc_1", {"text": "one"})]


@pytest.mark.asyncio
async def test_config_changed_during_lookup_and_noncooperative_close_are_fenced(monkeypatch):
    from deeptutor.services.llm.provider_core import openai_stream

    identity = ["original"]

    async def retrieve(_):
        identity[0] = "changed"
        return result()

    with pytest.raises(LLMOperationPaused, match="identity"):
        await consume_sdk_stream(
            recovery.guarded_responses(
                stream(initial()),
                progress=_SemanticProgress(),
                retrieve=retrieve,
                owner=lambda: identity[0],
            )
        )
    finished = asyncio.Event()

    async def close():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.03)
        finished.set()

    monkeypatch.setattr(openai_stream, "CLOSE_TIMEOUT_S", 0.005)
    async with openai_stream.managed_openai_stream(NS(close=close)):
        pass
    assert not finished.is_set()
    await asyncio.wait_for(finished.wait(), 0.15)
