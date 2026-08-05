"""OpenAI Responses background submit/retrieve/cancel contract tests.

Uses the FakeTransport so no real endpoint is contacted.  Verifies the exact
request method/path/body and that retrieve/cancel never re-submit.
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.unified import (
    PROTOCOL_RESPONSES,
    FakeTransport,
    TransportError,
    UnifiedLLMAdapter,
)
from deeptutor.services.llm.provider_core.unified.common import normalize_messages
from deeptutor.services.llm.provider_core.unified.types import (
    UnifiedProtocolError,
    UnifiedRequest,
)

from . import unified_fixtures as fx

RESPONSES_PATH = "/v1/responses"


def _adapter(transport: FakeTransport) -> UnifiedLLMAdapter:
    return UnifiedLLMAdapter(
        protocol=PROTOCOL_RESPONSES,
        transport=transport,
        strict_protocol=True,
        default_model="gpt-5.6",
        provider="openai",
        api_key="test-key",
    )


def _request() -> UnifiedRequest:
    return UnifiedRequest(
        messages=normalize_messages(
            [{"role": "system", "content": "Be brief"}, {"role": "user", "content": "Hi"}]
        ),
        model="gpt-5.6",
        max_tokens=256,
    )


class TestBackgroundLifecycle:
    def test_submit_retrieve_cancel_uses_response_identity(self) -> None:
        transport = FakeTransport()
        transport.add_response("POST", RESPONSES_PATH, fx.RESPONSES_BG_SUBMIT)
        transport.add_response("GET", "/v1/responses/resp_bg_1", fx.RESPONSES_BG_DONE)
        transport.add_response("POST", "/v1/responses/resp_bg_1/cancel", fx.RESPONSES_BG_CANCELLED)
        adapter = _adapter(transport)
        import asyncio

        async def _run() -> None:
            bg = await adapter.submit_background(_request())
            assert bg.id == "resp_bg_1"
            assert bg.status == "in_progress"
            assert bg.metadata["response_id"] == "resp_bg_1"

            done = await adapter.retrieve(bg.metadata["response_id"])
            assert done.status == "completed"
            assert done.content == "Background done"

            cancelled = await adapter.cancel(bg.metadata["response_id"])
            assert cancelled.status == "cancelled"

        asyncio.run(_run())

        # submit body carries background=true; retrieve/cancel never re-submit.
        submits = transport.calls_for("POST", RESPONSES_PATH)
        assert len(submits) == 1
        assert submits[0]["body"]["background"] is True
        assert submits[0]["body"]["model"] == "gpt-5.6"
        assert transport.calls_for("GET", "/v1/responses/resp_bg_1")
        assert transport.calls_for("POST", "/v1/responses/resp_bg_1/cancel")
        # The only POST to /v1/responses is the original submit.
        assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1

    def test_retrieve_never_resubmits_after_network_error(self) -> None:
        transport = FakeTransport()
        transport.add_response("POST", RESPONSES_PATH, fx.RESPONSES_BG_SUBMIT)
        transport.add_error("GET", "/v1/responses/resp_bg_1", TransportError("gone"))
        adapter = _adapter(transport)

        import asyncio

        async def _run() -> None:
            bg = await adapter.submit_background(_request())
            assert bg.id == "resp_bg_1"
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await adapter.retrieve(bg.metadata["response_id"])
            assert excinfo.value.code == "transport_error"
            # One submit, one retrieve attempt, zero extra submits.
            assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1

        asyncio.run(_run())

    def test_background_unsupported_on_other_protocols(self) -> None:
        from deeptutor.services.llm.provider_core.unified import PROTOCOL_CHAT_COMPLETIONS

        adapter = UnifiedLLMAdapter(
            protocol=PROTOCOL_CHAT_COMPLETIONS,
            transport=FakeTransport(),
            strict_protocol=True,
            default_model="gpt-5.6",
        )
        import asyncio

        async def _run() -> None:
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await adapter.submit_background(_request())
            assert excinfo.value.code == "background_unsupported"
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await adapter.retrieve("resp_x")
            assert excinfo.value.code == "background_unsupported"
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await adapter.cancel("resp_x")
            assert excinfo.value.code == "background_unsupported"

        asyncio.run(_run())

    def test_missing_response_id_raises(self) -> None:
        transport = FakeTransport()
        transport.add_response(
            "POST",
            RESPONSES_PATH,
            {"model": "gpt-5.6", "status": "in_progress", "output": []},
        )
        adapter = _adapter(transport)
        import asyncio

        async def _run() -> None:
            with pytest.raises(UnifiedProtocolError) as excinfo:
                await adapter.submit_background(_request())
            assert excinfo.value.code == "missing_response_id"

        asyncio.run(_run())
