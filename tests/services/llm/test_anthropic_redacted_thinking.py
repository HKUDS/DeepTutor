"""Encrypted thinking survives tool continuation without becoming public text."""

from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider
from deeptutor.services.session.provider_response_state import (
    MAX_THINKING_BLOCK_BYTES,
    MAX_THINKING_BLOCKS,
    normalize_provider_response_state,
)


def _blocks() -> list[dict[str, str]]:
    return [
        {"type": "thinking", "thinking": "Check the source", "signature": "signature-fixture"},
        {"type": "redacted_thinking", "data": "opaque-fixture+/=="},
        {"type": "thinking", "thinking": "Use lookup", "signature": "second-signature"},
    ]


def test_parse_keeps_encrypted_blocks_in_order_and_out_of_reasoning_text() -> None:
    response = AnthropicProvider._parse_response(
        SimpleNamespace(
            content=[SimpleNamespace(**block) for block in _blocks()]
            + [SimpleNamespace(type="tool_use", id="tool-1", name="lookup", input={})],
            stop_reason="tool_use",
            usage=None,
        )
    )
    assert response.thinking_blocks == _blocks()
    assert response.reasoning_content == "Check the source\nUse lookup"
    assert response.tool_calls[0].id == "tool-1"


def test_encrypted_only_response_has_no_readable_reasoning() -> None:
    response = AnthropicProvider._parse_response(
        SimpleNamespace(
            content=[SimpleNamespace(type="redacted_thinking", data="opaque-fixture+/==")],
            stop_reason="max_tokens",
            usage=None,
        )
    )
    assert response.thinking_blocks == [{"type": "redacted_thinking", "data": "opaque-fixture+/=="}]
    assert response.reasoning_content is None
    assert response.content is None


@pytest.mark.parametrize("private_state", [False, True])
def test_tool_continuation_preserves_direct_and_private_encrypted_blocks(
    private_state: bool,
) -> None:
    provider = object.__new__(AnthropicProvider)
    message = {
        "role": "assistant",
        "content": "Looking up the source",
        "tool_calls": [{"id": "tool-1", "function": {"name": "lookup", "arguments": "{}"}}],
    }
    if private_state:
        message["_provider_response_state"] = {"thinking_blocks": _blocks()}
    else:
        message["thinking_blocks"] = _blocks()
    original = deepcopy(message)
    _, converted = provider._convert_messages(
        [message, {"role": "tool", "tool_call_id": "tool-1", "content": "source"}]
    )
    assert converted[0]["content"][:3] == _blocks()
    assert converted[0]["content"][-1]["id"] == "tool-1"
    assert converted[1]["content"][0]["tool_use_id"] == "tool-1"
    assert message == original


def test_private_normalization_retains_mixed_blocks_and_copies_only_protocol_fields() -> None:
    blocks = _blocks()
    blocks[1]["unexpected"] = "discard"
    state = normalize_provider_response_state({"thinking_blocks": blocks})
    assert state == {"thinking_blocks": _blocks()}
    blocks[1]["data"] = "changed"
    assert state["thinking_blocks"][1]["data"] == "opaque-fixture+/=="


@pytest.mark.parametrize("data", [None, "", 1, True, [], {}])
def test_invalid_encrypted_data_rejects_the_whole_thinking_sequence(data: object) -> None:
    assert (
        normalize_provider_response_state(
            {"thinking_blocks": [_blocks()[0], {"type": "redacted_thinking", "data": data}]}
        )
        is None
    )


def test_encrypted_blocks_share_the_existing_count_and_utf8_byte_limits() -> None:
    block = {"type": "redacted_thinking", "data": "opaque"}
    assert (
        normalize_provider_response_state({"thinking_blocks": [block] * (MAX_THINKING_BLOCKS + 1)})
        is None
    )
    assert (
        normalize_provider_response_state(
            {"thinking_blocks": [{**block, "data": "中" * (MAX_THINKING_BLOCK_BYTES // 3)}]}
        )
        is None
    )


@pytest.mark.asyncio
async def test_encrypted_private_state_survives_sqlite_but_is_removed_from_public_history(
    tmp_path: Path,
) -> None:
    from deeptutor.services.session.model_history import replay_history
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    state = normalize_provider_response_state({"thinking_blocks": _blocks()})
    store = SQLiteSessionStore(tmp_path / "session.db")
    session = await store.create_session()
    await store.add_message(session["id"], "user", "Question")
    await store.add_message(
        session["id"], "assistant", "Answer", metadata={"provider_response_state": state}
    )
    internal = await store.get_messages_for_context(session["id"])
    assert internal[-1]["metadata"]["provider_response_state"] == {"thinking_blocks": _blocks()}
    public = await store.get_session_with_messages(session["id"])
    assert "opaque-fixture" not in json.dumps(public)
    # Completed turns already drop prefix-bound thinking during history replay.
    assert "opaque-fixture" not in json.dumps(replay_history(internal))


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_real_sdk_tool_followup_keeps_encrypted_data(streaming: bool) -> None:
    pytest.importorskip("anthropic")

    from deeptutor.runtime.agentic.messages import assistant_message_with_tool_calls

    requests = []
    blocks = _blocks() + [{"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {}}]

    def respond(payload):
        requests.append(payload)
        content = blocks if len(requests) == 1 else [{"type": "text", "text": "Complete"}]
        message = {
            "id": "msg-fixture",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": content,
            "stop_reason": "tool_use" if len(requests) == 1 else "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }
        if not payload.get("stream"):
            return "application/json", json.dumps(message).encode()
        frames = [
            {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}}
        ]
        for index, block in enumerate(content):
            frames.extend(
                [
                    {"type": "content_block_start", "index": index, "content_block": block},
                    {"type": "content_block_stop", "index": index},
                ]
            )
        frames.extend(
            [
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
                    "usage": {"output_tokens": 3},
                },
                {"type": "message_stop"},
            ]
        )
        return "text/event-stream", "".join(
            f"event: {frame['type']}\ndata: {json.dumps(frame)}\n\n" for frame in frames
        ).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            content_type, body = respond(payload)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    provider = AnthropicProvider(
        api_key="fixture",
        api_base=f"http://127.0.0.1:{server.server_port}",
        supports_prompt_caching=False,
    )
    tools = [
        {
            "type": "function",
            "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}},
        }
    ]
    messages = [{"role": "user", "content": "Question"}]
    method = provider.chat_stream if streaming else provider.chat
    try:
        first = await method(messages, tools=tools)
        assert first.finish_reason == "tool_calls"
        messages.extend(
            [
                assistant_message_with_tool_calls(
                    first.content or "",
                    [
                        {"id": call.id, "name": call.name, "arguments": json.dumps(call.arguments)}
                        for call in first.tool_calls
                    ],
                    thinking_blocks=first.thinking_blocks,
                ),
                {"role": "tool", "tool_call_id": "tool-1", "content": "source"},
            ]
        )
        final = await method(messages, tools=tools)
        assert final.content == "Complete"
        assert requests[1]["messages"][1]["content"][:3] == _blocks()
        assert requests[1]["messages"][2]["content"][0]["tool_use_id"] == "tool-1"
        assert len(requests) == 2
    finally:
        await provider._client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
