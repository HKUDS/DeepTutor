"""Strict explicit-``api_protocol`` no-fallback contract tests.

With ``strict_protocol=true`` a failed or unsupported Responses/Anthropic path
must raise the stable :class:`UnifiedProtocolError` and never silently call
Chat Completions (or any other protocol).
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.unified import (
    PROTOCOL_ANTHROPIC,
    PROTOCOL_CHAT_COMPLETIONS,
    PROTOCOL_RESPONSES,
    FakeTransport,
    UnifiedLLMAdapter,
)
from deeptutor.services.llm.provider_core.unified.types import UnifiedProtocolError

MESSAGES = [{"role": "user", "content": "Hi"}]


def _adapter(protocol: str, *, strict: bool = True) -> UnifiedLLMAdapter:
    return UnifiedLLMAdapter(
        protocol=protocol,
        transport=FakeTransport(),
        strict_protocol=strict,
        default_model="gpt-5.6",
        provider="openai",
        api_key="test-key",
    )


class TestStrictNoFallback:
    def test_responses_failure_does_not_fallback_to_chat_completions(self) -> None:
        adapter = _adapter(PROTOCOL_RESPONSES, strict=True)
        import asyncio

        async def _run() -> None:
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await adapter.chat(MESSAGES)
            assert excinfo.value.code in {"transport_error", "protocol_error"}

            # Only the Responses request was attempted; no chat completions.
            calls = adapter.transport.requests
            assert len(calls) == 1
            assert calls[0]["path"] == "/v1/responses"
            assert calls[0]["method"] == "POST"

        asyncio.run(_run())

    def test_anthropic_failure_does_not_fallback(self) -> None:
        adapter = _adapter(PROTOCOL_ANTHROPIC, strict=True)
        import asyncio

        async def _run() -> None:
            with pytest.raises(UnifiedProtocolError):
                await adapter.chat(MESSAGES)
            calls = adapter.transport.requests
            assert len(calls) == 1
            assert calls[0]["path"] == "/v1/messages"

        asyncio.run(_run())

    def test_non_strict_returns_error_response_without_fallback(self) -> None:
        adapter = _adapter(PROTOCOL_RESPONSES, strict=False)
        import asyncio

        async def _run() -> None:
            response = await adapter.chat(MESSAGES)
            assert response.finish_reason == "error"
            assert response.content is not None and "Error calling LLM" in response.content
            calls = adapter.transport.requests
            assert len(calls) == 1
            assert calls[0]["path"] == "/v1/responses"

        asyncio.run(_run())

    def test_stream_failure_raises_stable_error_when_strict(self) -> None:
        adapter = _adapter(PROTOCOL_RESPONSES, strict=True)
        import asyncio

        async def _run() -> None:
            with pytest.raises(UnifiedProtocolError):
                await adapter.chat_stream(MESSAGES)
            calls = adapter.transport.requests
            assert len(calls) == 1
            assert calls[0]["path"] == "/v1/responses"

        asyncio.run(_run())


class TestExistingProvidersHonorExplicitProtocol:
    def test_openai_compat_rejects_anthropic_protocol(self) -> None:
        from deeptutor.services.llm.provider_core.openai_compat_provider import (
            OpenAICompatProvider,
        )

        provider = OpenAICompatProvider(
            api_key="test-key",
            api_base="https://example.invalid/v1",
            api_protocol="anthropic_messages",
            strict_protocol=True,
        )
        import asyncio

        async def _run() -> None:
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await provider.chat(MESSAGES)
            assert excinfo.value.code == "protocol_unsupported"

        asyncio.run(_run())

    def test_anthropic_provider_rejects_openai_responses(self) -> None:
        pytest.importorskip("anthropic")
        from deeptutor.services.llm.provider_core.anthropic_provider import (
            AnthropicProvider,
        )

        provider = AnthropicProvider(
            api_key="test-key",
            api_base="https://api.anthropic.com",
            api_protocol="openai_responses",
            strict_protocol=True,
        )
        import asyncio

        async def _run() -> None:
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await provider.chat(MESSAGES)
            assert excinfo.value.code == "protocol_unsupported"

        asyncio.run(_run())


class TestMapErrorPassthrough:
    def test_unified_protocol_error_passes_through_map_error(self) -> None:
        from deeptutor.services.llm.error_mapping import map_error

        error = UnifiedProtocolError("boom", code="transport_error", protocol="openai_responses")
        mapped = map_error(error, provider="openai")
        assert mapped is error
