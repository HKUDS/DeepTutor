"""Offline fake ACP host used by the AcpBackend integration tests.

A minimal ACP "host" process that speaks newline-delimited JSON-RPC 2.0 over
stdio from the host side of the transcript the backend drives: it answers the
client's ``initialize`` / ``session/new`` / ``session/load`` / ``prompt``
requests and streams ``agent/message`` notifications (and one optional
``session/input_request``). It holds no real agent state — the point is to pin
the backend's wire behaviour offline, not to emulate an agent.

Usage: ``python acp_fake_host.py <scenario>`` where scenario selects the
behaviour (see ``_SCENARIOS``). Only the Python standard library is used, so
pytest can spawn it with ``sys.executable``.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

HOST_SESSION_ID = "acp-test-session-1"
_VERSION = "fake-acp-host-1.0"

# Our own id space for requests the host sends toward the client, so it never
# collides with the client's request ids.
_HOST_SEQ = 1000


def send(obj: dict[str, Any]) -> None:
    """Write one JSON-RPC frame (newline-delimited) and flush it out."""
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def read_request() -> dict[str, Any] | None:
    """Read the next client frame; ``None`` on EOF."""
    raw = sys.stdin.buffer.readline()
    if not raw:
        return None
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return read_request()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        sys.stderr.write(f"fake host: non-JSON client frame ignored: {text!r}\n")
        sys.stderr.flush()
        return read_request()
    return parsed if isinstance(parsed, dict) else read_request()


def respond(request: dict[str, Any], result: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "id": request.get("id"), "result": result})


def notify(method: str, params: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "method": method, "params": params})


def agent_message(session_id: str, blocks: list[dict[str, Any]], index: int) -> None:
    notify(
        "agent/message",
        {
            "session_id": session_id,
            "message": {
                "id": f"fake-msg-{index}",
                "role": "assistant",
                "content": blocks,
            },
        },
    )


def text_block(text: str, *, delta: bool = False) -> dict[str, Any]:
    return {"type": "text", "textDelta" if delta else "text": text}


def extract_question(request: dict[str, Any]) -> str:
    """Best-effort read of the client's ``prompt`` text (str or content list)."""
    params = request.get("params")
    if not isinstance(params, dict):
        return ""
    prompt = params.get("prompt")
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict):
        content = prompt.get("content")
        if isinstance(content, list):
            pieces = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    pieces.append(str(block.get("text") or ""))
            return "".join(pieces)
    return ""


def stream_ok_turn(session_id: str, question: str, *, resumed: bool = False) -> None:
    """Emit the happy-path turn: streamed text, a tool call, result content."""
    index = 0
    prefix = f"resumed:{session_id} " if resumed else ""
    agent_message(session_id, [text_block(f"{prefix}You asked: {question}\n", delta=True)], index)
    index += 1
    agent_message(session_id, [text_block("The answer is 4.", delta=True)], index)
    index += 1
    agent_message(
        session_id,
        [
            {
                "type": "tool_call",
                "id": "tc-1",
                "name": "read_file",
                "arguments": {"path": "a.txt"},
            }
        ],
        index,
    )
    index += 1
    agent_message(
        session_id,
        [
            {
                "type": "tool_call_result",
                "tool_use_id": "tc-1",
                "content": [{"type": "text", "text": "file says hello"}],
            }
        ],
        index,
    )
    index += 1
    agent_message(session_id, [text_block("Done.", delta=True)], index)
    index += 1
    # The "result" content block closes the turn (no text — streamed already).
    agent_message(session_id, [{"type": "result"}], index)


def run_scenario(scenario: str) -> int:
    session_id: str | None = None
    message_index = 0
    turn_done = False

    while True:
        request = read_request()
        if request is None:
            return 0  # client closed stdin → clean exit
        method = str(request.get("method") or "")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}

        if method == "initialize":
            if scenario == "hang_init":
                # Never answer: pretend to be a non-ACP binary that goes quiet.
                time.sleep(4)
                return 0
            respond(
                request,
                {
                    "protocolVersion": 1,
                    "agentCapabilities": {"load_session": True, "prompt_tools": False},
                    "agentVersion": _VERSION,
                },
            )
            if scenario == "malformed":
                # Interleave a non-JSON line with the protocol stream.
                sys.stdout.buffer.write(b"NOT-JSON banner\n")
                sys.stdout.buffer.flush()
            continue

        if method == "session/new":
            if scenario == "reject":
                respond(request, {})
                notify(
                    "session/update",
                    {
                        "session_id": HOST_SESSION_ID,
                        "status": "rejected",
                        "detail": "session rejected by policy",
                    },
                )
                return 0
            if scenario == "update_accept":
                # Accept via session/update; the request result carries no id.
                respond(request, {})
                notify(
                    "session/update",
                    {"session_id": HOST_SESSION_ID, "status": "accepted"},
                )
            else:
                respond(request, {"sessionId": HOST_SESSION_ID})
            session_id = HOST_SESSION_ID
            continue

        if method == "session/load":
            # Accept any resume id and hand it straight back.
            sid = str(params.get("session_id") or HOST_SESSION_ID)
            session_id = sid
            respond(request, {"sessionId": sid})
            continue

        if method == "prompt":
            if scenario == "exit_early":
                sys.stderr.write("fake host: exiting before answering\n")
                sys.stderr.flush()
                return 3
            if scenario == "error_content":
                agent_message(session_id or HOST_SESSION_ID, [text_block("partial")], 0)
                agent_message(
                    session_id or HOST_SESSION_ID,
                    [{"type": "error", "message": "agent failed"}],
                    1,
                )
                return 0
            if scenario == "input":
                question = extract_question(request)
                agent_message(
                    session_id or HOST_SESSION_ID,
                    [text_block("Thinking…", delta=True)],
                    message_index,
                )
                message_index += 1
                # Ask the client for input and require the auto-empty reply.
                request_id = _HOST_SEQ + 1
                notify_with_id = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "session/input_request",
                    "params": {
                        "session_id": session_id or HOST_SESSION_ID,
                        "message": {"content": [{"type": "text", "text": "Continue?"}]},
                    },
                }
                send(notify_with_id)
                reply = read_request()
                got = ""
                if reply is not None and reply.get("id") == request_id and "result" in reply:
                    got = str((reply.get("result") or {}).get("input") or "")
                if got != "":
                    sys.stderr.write(f"fake host: unexpected input reply: {got!r}\n")
                    sys.stderr.flush()
                    return 7
                agent_message(
                    session_id or HOST_SESSION_ID,
                    [text_block("Got empty input.", delta=True)],
                    message_index,
                )
                message_index += 1
                agent_message(
                    session_id or HOST_SESSION_ID,
                    [{"type": "result"}],
                    message_index,
                )
                return 0
            if scenario in ("ok", "malformed", "update_accept"):
                stream_ok_turn(
                    session_id or HOST_SESSION_ID,
                    extract_question(request),
                )
                return 0
            if scenario == "ok_resume":
                stream_ok_turn(
                    session_id or HOST_SESSION_ID,
                    extract_question(request),
                    resumed=True,
                )
                return 0
            # Unknown scenario: behave like "ok" so the client sees a turn.
            stream_ok_turn(session_id or HOST_SESSION_ID, extract_question(request))
            return 0

        # A response to the host's own request (e.g. session/input_request).
        if "result" in request or "error" in request:
            continue
        sys.stderr.write(f"fake host: unhandled frame {request!r}\n")
        sys.stderr.flush()
        return 9


if __name__ == "__main__":
    scenario = sys.argv[1] if len(sys.argv) > 1 else "ok"
    sys.exit(run_scenario(scenario))
