"""Offline fake ACP agent used by the AcpBackend integration tests.

A minimal ACP v1 *agent* that speaks newline-delimited JSON-RPC 2.0 over
stdio from the agent side of the transcript the backend drives: it answers the
client's ``initialize`` / ``session/new`` / ``session/load`` / ``session/prompt``
requests, streams ``session/update`` notifications (``agent_message_chunk``,
``tool_call``, ``tool_call_update``, …), answers ``elicitation/create``
requests from the client, and closes each turn with the ``session/prompt``
response. It holds no real agent state — the point is to pin the backend's wire
behaviour offline, not to emulate an agent.

Usage: ``python acp_fake_host.py <scenario>`` where scenario selects the
behaviour (see ``run_scenario``). Only the Python standard library is used, so
pytest can spawn it with ``sys.executable``.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

HOST_SESSION_ID = "acp-test-session-1"
_VERSION = "fake-acp-host-1.0"


def send(obj: dict[str, Any]) -> None:
    """Write one JSON-RPC frame (newline-delimited) and flush it out."""
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def read_request() -> dict[str, Any] | None:
    """Read the next client frame; ``None`` on EOF."""
    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            return None
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            sys.stderr.write(f"fake host: non-JSON client frame ignored: {text!r}\n")
            sys.stderr.flush()
            continue
        return parsed if isinstance(parsed, dict) else read_request()


def respond(request: dict[str, Any], result: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "id": request.get("id"), "result": result})


def respond_error(request: dict[str, Any], message: str) -> None:
    send({"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": 1, "message": message}})


def notify(method: str, params: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "method": method, "params": params})


def session_update(session_id: str, update: dict[str, Any]) -> None:
    notify("session/update", {"sessionId": session_id, "update": update})


def message_chunk(session_id: str, text: str) -> None:
    session_update(
        session_id,
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}},
    )


def extract_question(request: dict[str, Any]) -> str:
    """Read the client's ``prompt`` — an array of content blocks in v1."""
    params = request.get("params")
    if not isinstance(params, dict):
        return ""
    prompt = params.get("prompt")
    if not isinstance(prompt, list):
        return ""
    pieces: list[str] = []
    for block in prompt:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)


def end_prompt(request: dict[str, Any]) -> None:
    """Close the prompt turn by replying to the client's prompt request."""
    send({"jsonrpc": "2.0", "id": request.get("id"), "result": {"stopReason": "end_turn"}})


def stream_ok_turn(
    request: dict[str, Any], session_id: str, question: str, *, resumed: bool = False
) -> None:
    """Emit the happy-path turn: text chunks, a tool call + result, closing text."""
    prefix = f"resumed:{session_id} " if resumed else ""
    message_chunk(session_id, f"{prefix}You asked: {question}\n")
    message_chunk(session_id, "The answer is 4.")
    session_update(
        session_id,
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "tc-1",
            "title": "Reading project files",
            "kind": "read",
            "status": "pending",
            "rawInput": {"path": "a.txt"},
        },
    )
    session_update(
        session_id,
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tc-1",
            "status": "completed",
            "content": [
                {
                    "type": "content",
                    "content": {"type": "text", "text": "file says hello"},
                }
            ],
            "rawOutput": {"content": "file says hello"},
        },
    )
    message_chunk(session_id, "Done.")
    end_prompt(request)


def run_scenario(scenario: str) -> int:
    session_id: str | None = None

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
                    "agentCapabilities": {"loadSession": True},
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
                respond_error(request, "session rejected by policy")
                return 0
            session_id = HOST_SESSION_ID
            respond(request, {"sessionId": session_id})
            continue

        if method == "session/load":
            # Accept any resume id and hand it straight back.
            session_id = str(params.get("sessionId") or HOST_SESSION_ID)
            respond(request, {"sessionId": session_id})
            continue

        if method == "session/prompt":
            question = extract_question(request)
            if scenario == "exit_early":
                sys.stderr.write("fake host: exiting before answering\n")
                sys.stderr.flush()
                return 3
            if scenario == "prompt_error":
                message_chunk(session_id or HOST_SESSION_ID, "partial")
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {"code": 1, "message": "agent failed"},
                    }
                )
                return 0
            if scenario == "elicitation":
                # Ask the client for input (v1 elicitation) and require the
                # auto-decline answer before finishing the turn.
                request_id = 2001
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "elicitation/create",
                        "params": {
                            "mode": "form",
                            "sessionId": session_id or HOST_SESSION_ID,
                            "message": "Continue?",
                        },
                    }
                )
                reply = read_request()
                got = ""
                if reply is not None and reply.get("id") == request_id and "result" in reply:
                    got = str((reply.get("result") or {}).get("action") or "")
                if got != "decline":
                    sys.stderr.write(f"fake host: unexpected elicitation reply: {got!r}\n")
                    sys.stderr.flush()
                    return 7
                notify(
                    "elicitation/complete",
                    {"sessionId": session_id or HOST_SESSION_ID, "elicitationId": "el-1"},
                )
                message_chunk(session_id or HOST_SESSION_ID, "Got no input; declining.")
                end_prompt(request)
                return 0
            if scenario in ("ok", "malformed"):
                stream_ok_turn(request, session_id or HOST_SESSION_ID, question)
                return 0
            if scenario == "ok_resume":
                stream_ok_turn(request, session_id or HOST_SESSION_ID, question, resumed=True)
                return 0
            # Unknown scenario: behave like "ok" so the client sees a turn.
            stream_ok_turn(request, session_id or HOST_SESSION_ID, question)
            return 0

        if "result" in request or "error" in request:
            continue
        sys.stderr.write(f"fake host: unhandled frame {request!r}\n")
        sys.stderr.flush()
        return 9


if __name__ == "__main__":
    scenario = sys.argv[1] if len(sys.argv) > 1 else "ok"
    sys.exit(run_scenario(scenario))
