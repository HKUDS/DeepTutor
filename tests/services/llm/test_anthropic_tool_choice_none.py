"""Explicit tool suppression must survive native Anthropic request conversion."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest

from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider


@pytest.mark.parametrize("thinking", [False, True])
def test_explicit_none_is_preserved_with_and_without_thinking(thinking: bool) -> None:
    assert AnthropicProvider._convert_tool_choice("none", thinking) == {"type": "none"}


@pytest.mark.parametrize(
    "effort,model",
    [(None, "claude-sonnet-4-6"), ("high", "claude-sonnet-4-6"), ("high", "claude-opus-4-8")],
)
def test_request_keeps_tools_but_prohibits_calling_them(effort: str | None, model: str) -> None:
    provider = object.__new__(AnthropicProvider)
    provider.default_model = model
    provider.extra_headers = {}
    provider._supports_prompt_caching = True
    kwargs = provider._build_kwargs(
        [{"role": "user", "content": "Answer without using tools"}],
        [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        model,
        2048,
        0.7,
        effort,
        "none",
    )
    assert kwargs["tool_choice"] == {"type": "none"}
    assert kwargs["tools"][0]["name"] == "lookup"


@pytest.mark.parametrize("thinking", [False, True])
def test_auto_and_default_keep_their_existing_choice(thinking: bool) -> None:
    for choice in [None, "auto"]:
        assert AnthropicProvider._convert_tool_choice(choice, thinking) == {"type": "auto"}


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("effort", [None, "high"])
async def test_default_sdk_sends_explicit_none_on_the_wire(
    streaming: bool, effort: str | None
) -> None:
    pytest.importorskip("anthropic")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            message = {
                "id": "msg-fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "answer"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 3, "output_tokens": 1},
            }
            if payload.get("stream"):
                frames = [
                    {
                        "type": "message_start",
                        "message": {**message, "content": [], "stop_reason": None},
                    },
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": message["content"][0],
                    },
                    {"type": "content_block_stop", "index": 0},
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": {"output_tokens": 1},
                    },
                    {"type": "message_stop"},
                ]
                body = "".join(
                    f"event: {f['type']}\ndata: {json.dumps(f)}\n\n" for f in frames
                ).encode()
                content_type = "text/event-stream"
            else:
                body = json.dumps(message).encode()
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = AnthropicProvider(
        api_key="fixture", api_base=f"http://127.0.0.1:{server.server_port}"
    )
    try:
        method = provider.chat_stream if streaming else provider.chat
        response = await method(
            [{"role": "user", "content": "Answer without tools"}],
            tools=[
                {
                    "type": "function",
                    "function": {"name": "lookup", "parameters": {"type": "object"}},
                }
            ],
            model="claude-sonnet-4-6",
            reasoning_effort=effort,
            tool_choice="none",
        )
        assert response.content == "answer"
        assert requests[0]["tool_choice"] == {"type": "none"}
        assert requests[0]["tools"][0]["name"] == "lookup"
        assert len(requests) == 1
    finally:
        await provider._client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
