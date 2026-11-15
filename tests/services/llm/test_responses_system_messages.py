"""Keep system instructions when projecting a conversation to Responses."""

from copy import deepcopy
import json
from unittest.mock import patch

import httpx
import openai
import pytest

from deeptutor.services.llm.provider_core.azure_openai_provider import AzureOpenAIProvider
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.llm.provider_core.openai_responses import convert_messages
from deeptutor.services.session.context_builder import ContextBuilder


def test_summary_history_keeps_the_base_system_policy():
    history = ContextBuilder.__new__(ContextBuilder)._build_history(
        "Previous conversation summary", []
    )
    messages = [
        {"role": "system", "content": "Tutor policy"},
        *history,
        {"role": "user", "content": "Continue"},
    ]
    original = deepcopy(messages)
    instructions, inputs = convert_messages(messages)
    assert instructions == "Tutor policy\n\nPrevious conversation summary"
    assert inputs == [{"role": "user", "content": [{"type": "input_text", "text": "Continue"}]}]
    assert messages == original


@pytest.mark.parametrize("content", [None, "", [], [{"type": "text", "text": ""}]])
def test_empty_later_system_message_does_not_erase_prior_instructions(content):
    instructions, _ = convert_messages(
        [
            {"role": "system", "content": "Keep source citations"},
            {"role": "system", "content": content},
        ]
    )
    assert instructions == "Keep source citations"


def test_text_parts_keep_order_and_do_not_mutate_the_source():
    messages = [
        {"role": "system", "content": "  Base policy\n"},
        {
            "role": "system",
            "content": [{"type": "text", "text": "Locale"}, {"type": "text", "text": "Citations"}],
        },
    ]
    original = deepcopy(messages)
    assert convert_messages(messages) == ("  Base policy\n\n\nLocale\nCitations", [])
    assert messages == original


@pytest.mark.parametrize(
    "messages,expected",
    [
        ([], ""),
        ([{"role": "system", "content": "  Keep exact whitespace\n"}], "  Keep exact whitespace\n"),
    ],
)
def test_existing_empty_and_single_system_behavior(messages, expected):
    assert convert_messages(messages) == (expected, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "azure"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_real_sdk_request_contains_policy_and_summary(kind, streaming):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        response = {
            "id": "resp_fixture",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "fixture",
            "output": [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                }
            ],
        }
        if streaming:
            events = [
                {"type": "response.output_text.delta", "delta": "ok"},
                {"type": "response.completed", "response": response},
            ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content="".join("data: " + json.dumps(event) + "\n\n" for event in events),
            )
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = openai.AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/v1",
            http_client=http_client,
            max_retries=0,
        )
        module = "azure_openai_provider" if kind == "azure" else "openai_compat_provider"
        with patch(
            f"deeptutor.services.llm.provider_core.{module}.AsyncOpenAI", return_value=client
        ):
            if kind == "azure":
                provider = AzureOpenAIProvider(
                    api_key="fixture", api_base="https://fixture.invalid", default_model="fixture"
                )
            else:
                provider = OpenAICompatProvider(
                    api_key="fixture",
                    api_base="https://fixture.invalid/v1",
                    default_model="fixture",
                    wire_api="responses",
                )
        method = provider.chat_stream if streaming else provider.chat
        response = await method(
            messages=[
                {"role": "system", "content": "Tutor policy"},
                {"role": "system", "content": "History summary"},
                {"role": "user", "content": "Continue"},
            ]
        )
        assert response.content == "ok"
        assert requests[0]["instructions"] == "Tutor policy\n\nHistory summary"
        assert [item["role"] for item in requests[0]["input"]] == ["user"]
