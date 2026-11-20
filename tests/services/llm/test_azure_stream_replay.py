"""Azure streaming must retain the same replay state as nonstream responses."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import openai
import pytest

from deeptutor.runtime.agentic.client import _ProviderOpenAIAdapter
from deeptutor.services.llm.provider_core.azure_openai_provider import AzureOpenAIProvider
from deeptutor.services.session.provider_response_state import normalize_provider_response_state

ITEMS = [
    {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque-fixture-state"},
    {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "Checking", "annotations": []}],
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


class EventBody(httpx.AsyncByteStream):
    def __init__(self, events):
        self.events = events
        self.closed = False

    async def __aiter__(self):
        for event in self.events:
            yield ("data: " + json.dumps(event) + "\n\n").encode()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_encrypted_reasoning_reaches_the_next_tool_request(streaming):
    requests = []
    bodies = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        output = ITEMS if len(requests) == 1 else []
        response = {
            "id": "resp_fixture",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "fixture",
            "output": output,
            "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
        }
        if body["stream"]:
            events = [{"type": "response.output_item.done", "item": item} for item in output]
            events += [{"type": "response.completed", "response": response}]
            body_stream = EventBody(events)
            bodies.append(body_stream)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=body_stream,
            )
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        sdk = openai.AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/v1",
            http_client=http_client,
            max_retries=0,
        )
        with patch(
            "deeptutor.services.llm.provider_core.azure_openai_provider.AsyncOpenAI",
            return_value=sdk,
        ):
            provider = AzureOpenAIProvider(
                api_key="fixture", api_base="https://fixture.invalid", default_model="o3-fixture"
            )
        client = _ProviderOpenAIAdapter(provider)
        kwargs = dict(
            model="o3-fixture",
            messages=[{"role": "user", "content": "Look up the reference"}],
            reasoning_effort="high",
        )
        result = await client.chat.completions.create(**kwargs, stream=streaming)
        if streaming:
            chunks = [chunk async for chunk in result]
            final = chunks[-1]
            fields = final.choices[0].provider_specific_fields
            tool_id = next(
                chunk.choices[0].delta.tool_calls[0].id
                for chunk in chunks
                if chunk.choices[0].delta.tool_calls
            )
            assert final.usage["total_tokens"] == 10
        else:
            fields = result.choices[0].message.provider_specific_fields
            tool_id = result.choices[0].message.tool_calls[0].id
        assert requests[0]["store"] is False
        assert requests[0]["include"] == ["reasoning.encrypted_content"]
        assert "native_output_items" in fields
        native = fields["native_output_items"]
        assert [(item["type"], item["id"]) for item in native] == [
            (item["type"], item["id"]) for item in ITEMS
        ]
        assert native[0]["encrypted_content"] == "opaque-fixture-state"
        if streaming:
            assert bodies[0].closed
            assert not http_client.is_closed
        state = normalize_provider_response_state({"responses_output_items": native})
        before = deepcopy(state)
        await provider.chat(
            messages=[
                kwargs["messages"][0],
                {
                    "role": "assistant",
                    "content": "Checking",
                    "tool_calls": [],
                    "_provider_response_state": state,
                },
                {"role": "tool", "tool_call_id": tool_id, "content": "reference found"},
            ],
            reasoning_effort="high",
        )
        replay = requests[1]["input"]
        assert replay[1]["encrypted_content"] == "opaque-fixture-state"
        assert [item.get("id") for item in replay[1:4]] == ["rs_1", "msg_1", "fc_1"]
        assert replay[4] == {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "reference found",
        }
        assert state == before


@pytest.mark.asyncio
@pytest.mark.parametrize("search", [False, True])
async def test_ordinary_stream_retains_only_search_metadata_and_citations(search):
    message = {"type": "message", "id": "msg_plain", "role": "assistant", "content": []}
    tool = {
        "type": "function_call",
        "id": "fc_plain",
        "call_id": "call_plain",
        "name": "lookup",
        "arguments": "{}",
    }
    search_item = {"type": "web_search_call", "id": "ws_1", "status": "completed"}
    items = [message, tool] + ([search_item] if search else [])

    async def events():
        for item in items:
            yield SimpleNamespace(type="response.output_item.done", item=SimpleNamespace(**item))
        if search:
            yield SimpleNamespace(
                type="response.output_text.annotation.added",
                annotation={
                    "type": "url_citation",
                    "url": "https://example.test/reference",
                    "title": "Reference",
                },
            )
        yield SimpleNamespace(type="response.completed", response={"status": "completed"})

    async def create(**kwargs):
        return events()

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    with patch(
        "deeptutor.services.llm.provider_core.azure_openai_provider.AsyncOpenAI",
        return_value=client,
    ):
        provider = AzureOpenAIProvider(api_key="fixture", api_base="https://fixture.invalid")
    result = await provider.chat_stream(messages=[])
    assert result.tool_calls[0].name == "lookup"
    assert result.provider_specific_fields == (
        {
            "native_output_items": [search_item],
            "citations": [{"url": "https://example.test/reference", "title": "Reference"}],
        }
        if search
        else {}
    )


@pytest.mark.asyncio
async def test_failed_stream_does_not_publish_partial_replay_state():
    async def events():
        yield SimpleNamespace(type="response.output_item.done", item=SimpleNamespace(**ITEMS[0]))
        yield SimpleNamespace(
            type="response.failed", response={"error": {"message": "fixture failure"}}
        )

    class Stream:
        close = AsyncMock()

        def __aiter__(self):
            return events()

    stream = Stream()

    async def create(**kwargs):
        return stream

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    with patch(
        "deeptutor.services.llm.provider_core.azure_openai_provider.AsyncOpenAI",
        return_value=client,
    ):
        provider = AzureOpenAIProvider(api_key="fixture", api_base="https://fixture.invalid")
    result = await provider.chat_stream(messages=[])
    assert result.finish_reason == "error"
    assert result.provider_specific_fields == {}
    stream.close.assert_awaited_once()
