"""Legacy ``LLMResponse`` compatibility through the unified adapter.

The adapter must be a drop-in ``LLMProvider``: ``chat`` / ``chat_stream``
return the classic :class:`~deeptutor.services.llm.provider_core.base.LLMResponse`,
and no raw SDK object ever crosses the boundary.
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.base import LLMResponse, ToolCallRequest
from deeptutor.services.llm.provider_core.unified import (
    PROTOCOL_ANTHROPIC,
    PROTOCOL_CHAT_COMPLETIONS,
    PROTOCOL_RESPONSES,
    FakeTransport,
    TransportError,
    UnifiedLLMAdapter,
)
from deeptutor.services.llm.provider_core.unified.common import to_legacy_llm_response
from deeptutor.services.llm.provider_core.unified.types import UnifiedProtocolError, UnifiedResponse
from deeptutor.core.agentic.loop import _is_transient_loop_error
from deeptutor.agents.research.pipeline import _is_transient_model_error

from . import unified_fixtures as fx

MESSAGES = [{"role": "user", "content": "Hi"}]


def _adapter(protocol: str, transport: FakeTransport) -> UnifiedLLMAdapter:
    return UnifiedLLMAdapter(
        protocol=protocol,
        transport=transport,
        strict_protocol=True,
        default_model="gpt-5.6",
        provider="openai",
        api_key="test-key",
    )


class TestLegacyChat:
    @pytest.mark.parametrize("status_code,retryable", [(429, True), (500, True), (401, False)])
    def test_non_strict_responses_transport_error_preserves_lifecycle(
        self, status_code: int, retryable: bool
    ) -> None:
        transport = FakeTransport()
        transport.add_error(
            "POST", "/v1/responses", TransportError("private", status_code=status_code)
        )
        adapter = UnifiedLLMAdapter(
            protocol=PROTOCOL_RESPONSES, transport=transport, strict_protocol=False,
            default_model="gpt-5.6", provider="openai", api_key="test-key",
        )
        import asyncio

        response = asyncio.run(adapter.chat(MESSAGES))

        assert response.termination == {
            "provider_status": "failed", "finish_reason": "error",
            "error_code": "transport_error", "status_code": status_code,
            "protocol": "openai_responses", "provider": "openai",
            "retryable": retryable,
        }

    @pytest.mark.parametrize(
        "status_code,expected_retryable",
        [(408, True), (429, True), (500, True), (503, True), (401, False), (403, False)],
    )
    def test_responses_transport_status_survives_adapter_and_retry_classifiers(
        self, status_code: int, expected_retryable: bool
    ) -> None:
        transport = FakeTransport()
        transport.add_error(
            "POST", "/v1/responses",
            TransportError("provider body is private", status_code=status_code),
        )
        adapter = _adapter(PROTOCOL_RESPONSES, transport)
        import asyncio

        with pytest.raises(UnifiedProtocolError) as excinfo:
            asyncio.run(adapter.chat(MESSAGES))

        error = excinfo.value
        assert error.code == "transport_error"
        assert error.status_code == status_code
        assert error.retryable is expected_retryable
        assert _is_transient_loop_error(error) is expected_retryable
        assert _is_transient_model_error(error) is expected_retryable

    def test_chat_completions_returns_legacy_llm_response(self) -> None:
        transport = FakeTransport()
        transport.add_response("POST", "/v1/chat/completions", fx.CHAT_COMPLETIONS_TEXT)
        adapter = _adapter(PROTOCOL_CHAT_COMPLETIONS, transport)
        import asyncio

        response = asyncio.run(adapter.chat(MESSAGES))
        assert isinstance(response, LLMResponse)
        assert response.content == "Hello there!"
        assert response.finish_reason == "stop"
        assert response.usage["prompt_tokens"] == 10

    def test_responses_returns_legacy_llm_response_with_tool_calls(self) -> None:
        transport = FakeTransport()
        transport.add_response("POST", "/v1/responses", fx.RESPONSES_TOOL)
        adapter = _adapter(PROTOCOL_RESPONSES, transport)
        import asyncio

        response = asyncio.run(adapter.chat(MESSAGES))
        assert isinstance(response, LLMResponse)
        assert response.finish_reason == "tool_calls"
        assert len(response.tool_calls) == 2
        assert all(isinstance(tc, ToolCallRequest) for tc in response.tool_calls)
        assert response.tool_calls[0].id == "call_1|fc_1"
        assert response.tool_calls[0].name == "get_weather"
        assert response.termination["provider_status"] == "completed"
        assert response.continuation_items

    def test_anthropic_returns_legacy_llm_response(self) -> None:
        transport = FakeTransport()
        transport.add_response("POST", "/v1/messages", fx.ANTHROPIC_TEXT)
        adapter = _adapter(PROTOCOL_ANTHROPIC, transport)
        import asyncio

        response = asyncio.run(adapter.chat(MESSAGES))
        assert isinstance(response, LLMResponse)
        assert response.content == "Hello there!"
        assert response.reasoning_content is None


class TestLegacyChatStream:
    def test_stream_fires_deltas_and_returns_final_response(self) -> None:
        transport = FakeTransport()
        transport.add_stream("POST", "/v1/chat/completions", fx.CHAT_COMPLETIONS_STREAM_TEXT)
        adapter = _adapter(PROTOCOL_CHAT_COMPLETIONS, transport)
        import asyncio

        deltas: list[str] = []

        async def _run() -> None:
            response = await adapter.chat_stream(
                MESSAGES, on_content_delta=lambda text: deltas.append(text) or asyncio.sleep(0)
            )
            return response

        response = asyncio.run(_run())
        assert deltas == ["Hel", "lo"]
        assert isinstance(response, LLMResponse)
        assert response.content == "Hello"
        assert response.finish_reason == "stop"

    def test_stream_reasoning_deltas_fire_callback(self) -> None:
        transport = FakeTransport()
        transport.add_stream("POST", "/v1/messages", fx.ANTHROPIC_STREAM_THINKING)
        adapter = _adapter(PROTOCOL_ANTHROPIC, transport)
        import asyncio

        reasoning: list[str] = []

        async def _run() -> None:
            return await adapter.chat_stream(
                MESSAGES, on_reasoning_delta=lambda text: reasoning.append(text) or asyncio.sleep(0)
            )

        response = asyncio.run(_run())
        assert reasoning == ["Let me reason"]
        assert response.reasoning_content == "Let me reason"
        assert response.content == "Answer"


class TestNoRawSdkObjects:
    def test_returns_only_legacy_dataclasses(self) -> None:
        transport = FakeTransport()
        transport.add_response("POST", "/v1/chat/completions", fx.CHAT_COMPLETIONS_TOOL)
        adapter = _adapter(PROTOCOL_CHAT_COMPLETIONS, transport)
        import asyncio

        response = asyncio.run(adapter.chat(MESSAGES))
        assert isinstance(response, LLMResponse)
        assert not hasattr(response, "choices")  # not an SDK object
        assert not hasattr(response, "model_dump")  # not an SDK response


class _CloseRecordingTransport(FakeTransport):
    """Fake transport that records every ``aclose`` awaited by the adapter."""

    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        await super().aclose()


class TestLifecycle:
    def test_aclose_closes_adapter_owned_transport(self) -> None:
        import asyncio

        transport = _CloseRecordingTransport()
        adapter = _adapter(PROTOCOL_RESPONSES, transport)
        asyncio.run(adapter.aclose())
        assert transport.close_calls == 1

    def test_aclose_delegates_exactly_once_per_call(self) -> None:
        import asyncio

        transport = _CloseRecordingTransport()
        adapter = _adapter(PROTOCOL_CHAT_COMPLETIONS, transport)

        async def _run() -> None:
            await adapter.aclose()
            await adapter.aclose()

        asyncio.run(_run())
        assert transport.close_calls == 2


class TestToLegacyMapping:
    def test_maps_reasoning_and_thinking_blocks(self) -> None:
        unified = UnifiedResponse(
            content="Answer",
            reasoning={"text": "Think", "signature": "sig1"},
            finish_status="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )
        legacy = to_legacy_llm_response(unified)
        assert legacy.content == "Answer"
        assert legacy.reasoning_content == "Think"
        assert legacy.thinking_blocks == [
            {"type": "thinking", "thinking": "Think", "signature": "sig1"}
        ]
        assert legacy.usage == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
