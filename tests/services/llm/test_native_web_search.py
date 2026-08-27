"""Tests for native server-side web_search support (#846).

Covers the four seams a native web search crosses:

* ``convert_tools`` — DeepTutor's ``web_search`` function tool declared as the
  provider's native ``{"type": "web_search"}`` tool.
* provider gating — only DeepSeek's supported Responses model takes this path.
* parsing — ``web_search_call`` remains provider metadata and the answer is
  terminal; no fake local tool call is synthesized.
* streaming — the provider's complete action object and citations are retained.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.core.agentic import client as client_module
from deeptutor.core.agentic.client import LLMClientConfig
from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
)
from deeptutor.services.llm.provider_core.openai_responses import (
    consume_sse,
    convert_tools,
)
from deeptutor.services.llm.provider_core.openai_responses.parsing import (
    parse_response_output,
)
from deeptutor.services.provider_registry import find_by_name


class _SSEFixture:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def aiter_lines(self):
        for event in self._events:
            yield f"data: {json.dumps(event)}"
            yield ""


class _SDKStream:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


_TOOLS = [
    {
        "type": "function",
        "function": {"name": "web_search", "parameters": {"type": "object"}},
    }
]


# ---------------------------------------------------------------------------
# convert_tools: native mapping
# ---------------------------------------------------------------------------


class TestConvertToolsNativeWebSearch:
    def test_web_search_maps_to_native_tool_when_enabled(self) -> None:
        tools = [
            {"type": "function", "function": {"name": "web_search", "parameters": {}}},
            {"type": "function", "function": {"name": "rag", "parameters": {}}},
        ]
        converted = convert_tools(tools, native_web_search=True)
        assert {"type": "web_search"} in converted
        # Other tools keep their function schema.
        assert {"type": "function", "name": "rag", "description": "", "parameters": {}} in converted
        assert len(converted) == 2

    def test_web_search_stays_a_function_by_default(self) -> None:
        tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
        converted = convert_tools(tools)
        assert converted == [
            {"type": "function", "name": "web_search", "description": "", "parameters": {}}
        ]


# ---------------------------------------------------------------------------
# provider and adapter gating
# ---------------------------------------------------------------------------


def _provider(model: str) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        api_key="test-key",
        api_base="https://api.deepseek.com",
        default_model=model,
        spec=find_by_name("deepseek"),
        provider_name="deepseek",
    )


def test_only_supported_deepseek_model_uses_responses_for_native_search() -> None:
    assert _provider("deepseek-v4-flash")._should_use_responses_api(
        "deepseek-v4-flash", None, _TOOLS
    )
    assert not _provider("deepseek-v4-pro")._should_use_responses_api(
        "deepseek-v4-pro", None, _TOOLS
    )
    assert not _provider("deepseek-v4-flash")._should_use_responses_api(
        "deepseek-v4-flash", None, None
    )


def test_native_mapping_is_model_scoped() -> None:
    flash_body = _provider("deepseek-v4-flash")._build_responses_body(
        [{"role": "user", "content": "latest news"}],
        _TOOLS,
        "deepseek-v4-flash",
        256,
        0.7,
        None,
        None,
    )
    pro_body = _provider("deepseek-v4-pro")._build_responses_body(
        [{"role": "user", "content": "latest news"}],
        _TOOLS,
        "deepseek-v4-pro",
        256,
        0.7,
        None,
        None,
    )
    assert flash_body["tools"] == [{"type": "web_search"}]
    assert pro_body["tools"][0]["type"] == "function"


def test_agent_client_routes_only_supported_model_through_provider_adapter(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        client_module,
        "_build_direct_openai_adapter",
        lambda *_args, **_kwargs: sentinel,
    )
    spec = find_by_name("deepseek")
    assert spec is not None
    flash = LLMClientConfig(
        binding="deepseek",
        model="deepseek-v4-flash",
        api_key="k",
        base_url="https://api.deepseek.com",
    )
    pro = LLMClientConfig(
        binding="deepseek",
        model="deepseek-v4-pro",
        api_key="k",
        base_url="https://api.deepseek.com",
    )
    assert client_module._build_native_provider_adapter(flash, spec) is sentinel
    assert client_module._build_native_provider_adapter(pro, spec) is None


@pytest.mark.asyncio
async def test_provider_stream_returns_native_search_as_terminal_metadata() -> None:
    provider = _provider("deepseek-v4-flash")
    action = {"type": "open_page", "url": "https://example.com/current"}
    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="web_search_call",
                id="ws_1",
                status="completed",
                action=action,
            ),
        ),
        SimpleNamespace(type="response.output_text.delta", delta="Current answer."),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                status="completed",
                usage={"input_tokens": 4, "output_tokens": 2},
            ),
        ),
    ]
    captured_body: dict = {}

    async def create(**body):
        captured_body.update(body)
        return _SDKStream(events)

    provider._client = SimpleNamespace(
        responses=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace()),
    )

    result = await provider.chat_stream(
        messages=[{"role": "user", "content": "What changed today?"}],
        tools=_TOOLS,
        model="deepseek-v4-flash",
        max_tokens=256,
    )

    assert captured_body["tools"] == [{"type": "web_search"}]
    assert result.content == "Current answer."
    assert result.finish_reason == "stop"
    assert result.tool_calls == []
    assert result.provider_specific_fields["native_output_items"] == [
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": action,
        }
    ]


# ---------------------------------------------------------------------------
# parsing: web_search_call items + url_citation annotations
# ---------------------------------------------------------------------------


class TestParseServerExecutedWebSearch:
    def test_parse_response_output_preserves_action_without_tool_loop(self) -> None:
        response = {
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws_abc",
                    "status": "completed",
                    "action": {
                        "type": "open_page",
                        "url": "https://example.com/paper",
                    },
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "FFT is O(N log N).",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com/paper",
                                    "title": "Cooley-Tukey",
                                }
                            ],
                        }
                    ],
                },
            ],
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        result = parse_response_output(response)
        assert result.content == "FFT is O(N log N)."
        assert result.tool_calls == []
        fields = result.provider_specific_fields
        assert fields["native_output_items"] == [response["output"][0]]
        assert fields["citations"] == [
            {"url": "https://example.com/paper", "title": "Cooley-Tukey"}
        ]

    @pytest.mark.asyncio
    async def test_sse_stream_collects_item_and_annotations(self) -> None:
        events = [
            {
                "type": "response.output_item.added",
                "item": {"type": "web_search_call", "id": "ws_1", "status": "in_progress"},
            },
            {
                "type": "response.output_text.annotation.added",
                "annotation": {"type": "url_citation", "url": "https://a", "title": "A"},
            },
            {
                "type": "response.output_text.annotation.added",
                "annotation": {"type": "url_citation", "url": "https://b", "title": "B"},
            },
            {"type": "response.output_text.delta", "delta": "hello"},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "web_search_call",
                    "id": "ws_1",
                    "status": "completed",
                    "action": {"type": "find_in_page", "pattern": "FFT"},
                },
            },
        ]
        provider_events: list[tuple[str, dict]] = []
        content, tool_calls, _ = await consume_sse(
            _SSEFixture(events),
            on_provider_event=lambda kind, payload: provider_events.append((kind, payload)),
        )
        assert content == "hello"
        assert tool_calls == []
        assert provider_events[-1] == ("output_item", events[-1]["item"])
        assert [payload for kind, payload in provider_events if kind == "citation"] == [
            {"url": "https://a", "title": "A"},
            {"url": "https://b", "title": "B"},
        ]

    @pytest.mark.asyncio
    async def test_sse_deduplicates_repeated_done_items(self) -> None:
        events = [
            {
                "type": "response.output_item.done",
                "item": {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            },
            {
                "type": "response.output_item.done",
                "item": {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            },
        ]
        provider_events: list[tuple[str, dict]] = []
        _, tool_calls, _ = await consume_sse(
            _SSEFixture(events),
            on_provider_event=lambda kind, payload: provider_events.append((kind, payload)),
        )
        assert tool_calls == []
        assert len(provider_events) == 1

    @pytest.mark.asyncio
    async def test_sse_annotations_after_item_done_are_kept(self) -> None:
        # Realistic ordering: the search item completes first, then the answer
        # text streams with its citations. Both remain provider metadata.
        events = [
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "web_search_call",
                    "id": "ws_1",
                    "status": "completed",
                    "action": {"query": "fft"},
                },
            },
            {"type": "response.output_text.delta", "delta": "FFT is O(N log N)."},
            {
                "type": "response.output_text.annotation.added",
                "annotation": {"type": "url_citation", "url": "https://a", "title": "A"},
            },
        ]
        provider_events: list[tuple[str, dict]] = []
        _, tool_calls, _ = await consume_sse(
            _SSEFixture(events),
            on_provider_event=lambda kind, payload: provider_events.append((kind, payload)),
        )
        assert tool_calls == []
        assert provider_events == [
            ("output_item", events[0]["item"]),
            ("citation", {"url": "https://a", "title": "A"}),
        ]
