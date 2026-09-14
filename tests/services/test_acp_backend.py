"""AcpBackend — the Agent Client Protocol (ACP) subagent backend (#1028, stage 1).

The backend drives a spawnable ACP *agent* process over newline-delimited
JSON-RPC 2.0 on stdio, speaking the schema-verified v1 transcript: the client
sends ``initialize`` → ``session/new``/``session/load`` → ``session/prompt``,
and the agent streams ``session/update`` notifications and closes the turn with
the prompt response. These tests exercise that wire contract offline against a
fake agent. Two agents are used:

* an **in-process** fake agent behind :class:`AcpBackend`'s injected
  ``host_factory`` seam (mirrors the transport injection the remote Hermes
  backend uses) — always runnable;
* the real **subprocess** fixture :file:`tests/fixtures/acp_fake_host.py` via
  the default OS-pipe spawn — run wherever asyncio can spawn piped children,
  skipped in sandboxes that forbid it.

Plus the detect/registry wiring and the command-resolution rules. No real
agent CLI is required.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from deeptutor.services.subagent.acp import ACP_COMMAND_ENV, AcpBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_REASONING,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "acp_fake_host.py"
_QUESTION = "Is four the answer?"

# Every test here is async (detect/consult are coroutines); run them all on the
# pytest-asyncio loop like the other backend test modules.
pytestmark = pytest.mark.asyncio


# ---- in-process fake ACP agent ----------------------------------------------------


class _HostWriter:
    """A consult-facing stdin: frames are enqueued for the in-process agent."""

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            return 0
        self._queue.put_nowait(data)
        return len(data)

    async def drain(self) -> None:  # noqa: D102 - queue writes never block
        return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(b"")


class _InMemoryAgent:
    """An ACP v1 agent that consult drives entirely in-process (no OS pipes).

    The ``scenario`` behaviours mirror the subprocess fixture in
    :file:`tests/fixtures/acp_fake_host.py`; both encode the same transcript.
    """

    HOST_SESSION = "acp-test-session-1"

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self._inbound: asyncio.Queue = asyncio.Queue()
        self._stdout = asyncio.StreamReader()
        self._exit_code = 0
        self._done = asyncio.Event()
        self.returncode: int | None = None
        self.stdin = _HostWriter(self._inbound)
        self.stdout = self._stdout
        self._task: asyncio.Task | None = None
        # Requests we answered, for asserting the exact client wire shape.
        self.session_params: dict | None = None
        self.prompt_params: dict | None = None

    # -- asyncio.subprocess.Process duck-type surface ---------------------------
    async def wait(self) -> int:
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def kill(self) -> None:
        self.terminate()

    # -- engine -----------------------------------------------------------------
    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run())
        return self._task

    async def _run(self) -> None:
        try:
            await self._run_scenario()
        finally:
            self.returncode = self._exit_code
            self._stdout.feed_eof()
            self._done.set()

    async def _read_frame(self) -> dict | None:
        while True:
            raw = await self._inbound.get()
            if not raw:
                return None
            try:
                parsed = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            return parsed if isinstance(parsed, dict) else None

    async def _write_frame(self, obj: dict) -> None:
        self._stdout.feed_data((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    async def _respond(self, request: dict, result: dict) -> None:
        await self._write_frame({"jsonrpc": "2.0", "id": request.get("id"), "result": result})

    async def _respond_error(self, request: dict, message: str) -> None:
        await self._write_frame(
            {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": 1, "message": message}}
        )

    async def _notify(self, method: str, params: dict) -> None:
        await self._write_frame({"jsonrpc": "2.0", "method": method, "params": params})

    async def _session_update(self, session_id: str, update: dict) -> None:
        await self._notify("session/update", {"sessionId": session_id, "update": update})

    async def _message_chunk(self, session_id: str, text: str) -> None:
        await self._session_update(
            session_id,
            {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}},
        )

    async def _run_scenario(self) -> None:
        scenario = self.scenario
        session_id: str | None = None

        while True:
            request = await self._read_frame()
            if request is None:
                return
            method = str(request.get("method") or "")
            params = request.get("params") if isinstance(request.get("params"), dict) else {}

            if method == "initialize":
                if scenario == "hang_init":
                    # Stay alive without answering; consult's timeout must fire.
                    while await self._read_frame() is not None:
                        pass
                    return
                await self._respond(
                    request,
                    {
                        "protocolVersion": 1,
                        "agentCapabilities": {"loadSession": True},
                        "agentVersion": "fake-acp-host-1.0",
                    },
                )
                if scenario == "malformed":
                    self._stdout.feed_data(b"NOT-JSON banner\n")
                continue

            if method in ("session/new", "session/load"):
                self.session_params = params
                if scenario == "reject" and method == "session/new":
                    await self._respond_error(request, "session rejected by policy")
                    return
                if method == "session/new":
                    session_id = self.HOST_SESSION
                else:
                    session_id = str(params.get("sessionId") or self.HOST_SESSION)
                await self._respond(request, {"sessionId": session_id})
                continue

            if method == "session/prompt":
                self.prompt_params = params
                question = self._prompt_text(params)
                if scenario == "exit_early":
                    self._exit_code = 3
                    return
                if scenario == "prompt_error":
                    await self._message_chunk(session_id or self.HOST_SESSION, "partial")
                    await self._write_frame(
                        {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "error": {"code": 1, "message": "agent failed"},
                        }
                    )
                    return
                if scenario == "elicitation":
                    await self._message_chunk(session_id or self.HOST_SESSION, "Thinking…")
                    request_id = 2001
                    await self._write_frame(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "elicitation/create",
                            "params": {
                                "mode": "form",
                                "sessionId": session_id or self.HOST_SESSION,
                                "message": "Continue?",
                            },
                        }
                    )
                    reply = await self._read_frame()
                    got = ""
                    if reply is not None and reply.get("id") == request_id and "result" in reply:
                        got = str((reply.get("result") or {}).get("action") or "")
                    if got != "decline":
                        self._exit_code = 7
                        return
                    await self._notify(
                        "elicitation/complete",
                        {"sessionId": session_id or self.HOST_SESSION, "elicitationId": "el-1"},
                    )
                    await self._message_chunk(
                        session_id or self.HOST_SESSION, "Got no input; declining."
                    )
                    await self._respond(request, {"stopReason": "end_turn"})
                    return
                if scenario == "unsolicited_request":
                    await self._message_chunk(session_id or self.HOST_SESSION, "Thinking…")
                    request_id = 2002
                    await self._write_frame(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "session/request_permission",
                            "params": {"sessionId": session_id or self.HOST_SESSION},
                        }
                    )
                    reply = await self._read_frame()
                    code = ""
                    if reply is not None and reply.get("id") == request_id and "error" in reply:
                        code = str((reply.get("error") or {}).get("code") or "")
                    if code != "-32601":
                        self._exit_code = 7
                        return
                    await self._message_chunk(
                        session_id or self.HOST_SESSION, "Permission declined; moving on."
                    )
                    await self._respond(request, {"stopReason": "end_turn"})
                    return
                await self._ok_turn(request, session_id or self.HOST_SESSION, question)
                return

            if "result" in request or "error" in request:
                continue
            self._exit_code = 9
            return

    @staticmethod
    def _prompt_text(params: dict) -> str:
        prompt = params.get("prompt")
        if not isinstance(prompt, list):
            return ""
        pieces: list[str] = []
        for block in prompt:
            if isinstance(block, dict) and block.get("type") == "text":
                pieces.append(str(block.get("text") or ""))
        return "".join(pieces)

    async def _ok_turn(self, request: dict, session_id: str, question: str) -> None:
        prefix = f"resumed:{session_id} " if self.scenario == "ok_resume" else ""
        await self._message_chunk(session_id, f"{prefix}You asked: {question}\n")
        await self._message_chunk(session_id, "The answer is 4.")
        await self._session_update(
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
        await self._session_update(
            session_id,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tc-1",
                "status": "completed",
                "content": [
                    {"type": "content", "content": {"type": "text", "text": "file says hello"}}
                ],
                "rawOutput": {"content": "file says hello"},
            },
        )
        if self.scenario == "ok_with_thought":
            await self._session_update(
                session_id,
                {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"type": "text", "text": "hmm…"},
                },
            )
        await self._message_chunk(session_id, "Done.")
        # The turn ends with the JSON-RPC response to the prompt request.
        await self._respond(request, {"stopReason": "end_turn"})


# ---- helpers ---------------------------------------------------------------------


class _SyncPipeWriter:
    """A consult-facing stdin backed by a real (sync) child stdin pipe."""

    def __init__(self, pipe) -> None:
        self._pipe = pipe
        self._closed = False

    def write(self, data: bytes) -> int:
        if self._closed:
            return 0
        try:
            self._pipe.write(data)
            return len(data)
        except (BrokenPipeError, OSError):
            return 0

    async def drain(self) -> None:
        if not self._closed:
            await asyncio.to_thread(self._pipe.flush)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._pipe.close()
            except Exception:  # noqa: BLE001 - best-effort pipe close
                pass


class _RealProcessAgent:
    """A consult-facing agent that runs the fixture as a real subprocess.

    Some sandboxes forbid asyncio's duplex-pipe spawn (``WinError 5`` on the
    pipe creation) while a synchronous ``subprocess.Popen`` with pipes still
    works. This agent therefore spawns synchronously and bridges the child's
    stdout to an :class:`asyncio.StreamReader` from a reader thread — exercising
    the real process and real byte framing end-to-end while consult stays
    async. Consult only ever sees the same duck-typed surface as the other
    hosts.
    """

    def __init__(self, argv: list[str], loop: asyncio.AbstractEventLoop) -> None:
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._loop = loop
        self.stdout = asyncio.StreamReader()
        self.stdin = _SyncPipeWriter(self._proc.stdin)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    @property
    def returncode(self):
        return self._proc.poll()

    def start(self) -> None:
        """The pump thread is already running; kept for host-interface symmetry."""

    async def wait(self) -> int:
        return await asyncio.to_thread(self._proc.wait)

    def terminate(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()

    def kill(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()

    def _pump(self) -> None:
        try:
            for line in self._proc.stdout:
                self._loop.call_soon_threadsafe(self.stdout.feed_data, line)
        finally:
            self._loop.call_soon_threadsafe(self.stdout.feed_eof)


def _host_argv(scenario: str) -> list[str]:
    return [sys.executable, str(_FIXTURE), scenario]


async def _consult_memory(scenario: str, monkeypatch, **kwargs):
    """Run consult against the in-process fake agent (always available)."""
    agent = _InMemoryAgent(scenario)
    backend = AcpBackend(host_factory=lambda: _ready(agent))
    return await _drive(backend, agent, monkeypatch, **kwargs)


async def _consult_real_process(scenario: str, monkeypatch, **kwargs):
    """Run consult against the real subprocess fixture through sync pipes."""
    loop = asyncio.get_running_loop()
    agent = _RealProcessAgent(_host_argv(scenario), loop)
    backend = AcpBackend(host_factory=lambda: _ready(agent))
    return await _drive(backend, agent, monkeypatch, **kwargs)


async def _consult_default_spawn(scenario: str, monkeypatch, **kwargs):
    """Run consult against the fixture via consult's own asyncio subprocess spawn."""
    monkeypatch.setenv(ACP_COMMAND_ENV, json.dumps(_host_argv(scenario)))
    backend = AcpBackend()
    return await _drive(backend, None, monkeypatch, **kwargs)


async def _ready(agent) -> _InMemoryAgent:
    return agent


async def _drive(backend, agent, monkeypatch, *, question: str = _QUESTION, **kwargs):
    if agent is not None:
        agent.start()
    seen: list = []

    async def on_event(event):
        seen.append(event)

    result = await backend.consult(
        question,
        on_event=on_event,
        **kwargs,
    )
    if agent is not None:
        await agent.wait()
    return result, seen


def _asyncio_spawn_available() -> bool:
    """Whether this environment can spawn piped children via asyncio."""
    if _asyncio_spawn_available.result is not None:  # type: ignore[attr-defined]
        return _asyncio_spawn_available.result  # type: ignore[attr-defined]

    async def probe() -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "pass",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await process.wait()
            return process.returncode == 0
        except Exception:  # noqa: BLE001 - any spawn failure means "not available"
            return False

    try:
        _asyncio_spawn_available.result = asyncio.run(probe())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - no event loop available in this thread
        _asyncio_spawn_available.result = False  # type: ignore[attr-defined]
    return _asyncio_spawn_available.result  # type: ignore[attr-defined]


_asyncio_spawn_available.result = None  # type: ignore[attr-defined]

_requires_subprocess = pytest.mark.skipif(
    not _asyncio_spawn_available(),
    reason="asyncio cannot spawn piped children in this sandbox (WinError 5)",
)


def _texts(seen) -> list[str]:
    return [e.text for e in seen]


# ---- command resolution / detect -------------------------------------------------


async def test_env_command_unset_means_unavailable(monkeypatch) -> None:
    monkeypatch.delenv(ACP_COMMAND_ENV, raising=False)
    detected = await AcpBackend().detect()

    assert detected.kind == "acp"
    assert detected.available is False
    assert "configure" in detected.detail.lower() or ACP_COMMAND_ENV in detected.detail


async def test_env_command_resolves_makes_available(monkeypatch) -> None:
    monkeypatch.setenv(ACP_COMMAND_ENV, json.dumps(_host_argv("ok")))
    detected = await AcpBackend().detect()
    assert detected.available is True
    assert detected.version == ""


async def test_env_command_missing_binary_stays_unavailable(monkeypatch) -> None:
    monkeypatch.setenv(ACP_COMMAND_ENV, json.dumps(["definitely-not-an-acp-host-xyz", "ok"]))
    detected = await AcpBackend().detect()
    assert detected.available is False
    assert "definitely-not-an-acp-host-xyz" in detected.detail


async def test_settings_extra_args_are_a_valid_command_source(monkeypatch) -> None:
    """Persisted per-backend ``extra_args`` are the command when the env is unset."""
    monkeypatch.delenv(ACP_COMMAND_ENV, raising=False)

    class _Settings:
        def backend(self, kind: str) -> BackendConfig:  # noqa: ARG002
            return BackendConfig(extra_args=_host_argv("ok"))

    import deeptutor.services.subagent.acp as acp_mod

    monkeypatch.setattr(acp_mod, "load_subagent_settings", lambda: _Settings())
    detected = await AcpBackend().detect()
    assert detected.available is True


async def test_extra_args_append_to_env_command(monkeypatch) -> None:
    monkeypatch.setenv(ACP_COMMAND_ENV, json.dumps(["claude", "--acp"]))
    import deeptutor.services.subagent.acp as acp_mod

    command = acp_mod.acp_host_command(BackendConfig(extra_args=["--model", "x"]))
    assert command == ["claude", "--acp", "--model", "x"]


async def test_space_separated_env_command_is_parsed(monkeypatch) -> None:
    monkeypatch.setenv(ACP_COMMAND_ENV, '"claude" --acp')
    import deeptutor.services.subagent.acp as acp_mod

    command = acp_mod.acp_host_command(BackendConfig())
    assert command == ["claude", "--acp"]


# ---- registry ---------------------------------------------------------------------


async def test_registry_knows_acp_backend() -> None:
    from deeptutor.services.subagent.registry import get_backend, list_backend_kinds

    assert "acp" in list_backend_kinds()
    assert isinstance(get_backend("acp"), AcpBackend)


async def test_detect_all_reports_acp(monkeypatch) -> None:
    monkeypatch.delenv(ACP_COMMAND_ENV, raising=False)
    from deeptutor.services.subagent.registry import detect_all

    kinds = {d.kind for d in await detect_all()}
    assert "acp" in kinds


# ---- consult integration (in-process agent, always runs) ---------------------------


async def test_consult_streams_events_and_returns_session(monkeypatch) -> None:
    result, seen = await _consult_memory("ok", monkeypatch)

    assert result.success is True
    assert result.error == ""
    assert result.session_id == "acp-test-session-1"
    assert result.event_count == len(seen)

    # Session start is announced, then text chunks stream, a tool runs, closes.
    assert seen[0].kind == EVENT_LOG
    assert "session" in seen[0].text
    kinds = [e.kind for e in seen[1:]]
    assert kinds[0] == EVENT_TEXT and kinds[1] == EVENT_TEXT
    assert EVENT_TOOL in kinds
    assert EVENT_TOOL_RESULT in kinds
    assert kinds[-1] == EVENT_TEXT

    tool = next(e for e in seen if e.kind == EVENT_TOOL)
    tool_result = next(e for e in seen if e.kind == EVENT_TOOL_RESULT)
    assert "Reading" in tool.text or "a.txt" in tool.text
    assert "file says hello" in tool_result.text
    # Tool start and finish collapse to one row via the shared toolCallId.
    assert tool.meta.get("merge_id") == "tc-1"
    assert tool_result.meta.get("merge_id") == "tc-1"

    # The question travelled through the prompt content array and back.
    assert any(_QUESTION in t for t in _texts(seen))
    assert result.final_text.startswith("You asked:")
    assert "The answer is 4." in result.final_text
    assert result.final_text.endswith("Done.")


async def test_consult_sends_schema_conformant_session_and_prompt(monkeypatch) -> None:
    """session/new carries cwd+mcpServers and session/prompt an array of blocks."""
    agent = _InMemoryAgent("ok")
    backend = AcpBackend(host_factory=lambda: _ready(agent))
    result, _ = await _drive(backend, agent, monkeypatch)

    assert result.success is True
    assert agent.session_params is not None
    assert agent.session_params["cwd"]  # absolute working directory
    assert agent.session_params["mcpServers"] == []
    assert agent.prompt_params is not None
    assert agent.prompt_params["sessionId"] == "acp-test-session-1"
    assert agent.prompt_params["prompt"] == [{"type": "text", "text": _QUESTION}]


async def test_consult_resume_sends_session_load_with_session_id(monkeypatch) -> None:
    agent = _InMemoryAgent("ok_resume")
    backend = AcpBackend(host_factory=lambda: _ready(agent))
    result, _ = await _drive(backend, agent, monkeypatch, session_id="acp-sess-9", question="again")

    assert result.success is True
    assert agent.session_params is not None
    assert agent.session_params["sessionId"] == "acp-sess-9"
    assert agent.session_params["mcpServers"] == []
    assert result.session_id == "acp-sess-9"
    # The fake agent prefixes its answer with the id it was asked to load.
    assert result.final_text.startswith("resumed:acp-sess-9 ")


async def test_consult_system_prompt_is_prepended_on_fresh_run(monkeypatch) -> None:
    config = BackendConfig(system_prompt="be brief")
    result, _ = await _consult_memory("ok", monkeypatch, config=config)
    assert result.final_text.startswith("You asked: be brief\n\nIs four the answer?")


async def test_consult_system_prompt_skipped_on_resume(monkeypatch) -> None:
    config = BackendConfig(system_prompt="be brief")
    result, _ = await _consult_memory("ok_resume", monkeypatch, config=config, session_id="s-1")
    assert "be brief" not in result.final_text


async def test_consult_forwards_images_as_paths(monkeypatch) -> None:
    result, _ = await _consult_memory("ok", monkeypatch, images=["C:/tmp/a.png", "C:/tmp/b.png"])
    assert "a.png" in result.final_text
    assert "b.png" in result.final_text


async def test_consult_answers_elicitation_with_decline(monkeypatch) -> None:
    """A v1 elicitation/create request is surfaced and auto-declined so a run
    never stalls; the agent then finishes the turn."""
    result, seen = await _consult_memory("elicitation", monkeypatch)
    assert result.success is True
    assert result.final_text.endswith("Got no input; declining.")
    log = next(
        e for e in seen if e.kind == EVENT_LOG and ("elicitation" in e.text or "input" in e.text)
    )
    assert "decline" in log.text


async def test_consult_rejects_unsolicited_requests_with_method_not_found(monkeypatch) -> None:
    """Unsupported agent requests (e.g. permission) are refused, not approved."""
    result, seen = await _consult_memory("unsolicited_request", monkeypatch)
    assert result.success is True
    assert result.final_text.endswith("Permission declined; moving on.")
    assert any("unsupported method" in e.text for e in seen)


async def test_consult_session_rejected_is_a_failure(monkeypatch) -> None:
    result, seen = await _consult_memory("reject", monkeypatch)
    assert result.success is False
    assert "reject" in result.error
    assert any(e.kind == EVENT_ERROR for e in seen)


async def test_consult_prompt_error_fails_run(monkeypatch) -> None:
    result, seen = await _consult_memory("prompt_error", monkeypatch)
    assert result.success is False
    assert "agent failed" in result.error
    assert any(e.kind == EVENT_ERROR and "agent failed" in e.text for e in seen)


async def test_consult_agent_exit_before_answer_is_a_failure(monkeypatch) -> None:
    result, seen = await _consult_memory("exit_early", monkeypatch)
    assert result.success is False
    assert "3" in result.error and "prompt" in result.error
    assert any(e.kind == EVENT_ERROR for e in seen)


async def test_consult_handshake_timeout_is_a_clean_failure(monkeypatch) -> None:
    """An agent that never answers initialize fails fast instead of hanging."""
    import deeptutor.services.subagent.acp as acp_mod

    monkeypatch.setattr(acp_mod, "_HANDSHAKE_TIMEOUT_SECONDS", 1.0)
    result, seen = await _consult_memory("hang_init", monkeypatch)
    assert result.success is False
    assert "initialize" in result.error
    assert any(e.kind == EVENT_ERROR for e in seen)


async def test_consult_tolerates_non_json_stdout_lines(monkeypatch) -> None:
    result, seen = await _consult_memory("malformed", monkeypatch)
    assert result.success is True
    assert "The answer is 4." in result.final_text
    assert any("NOT-JSON banner" in e.text for e in seen)


async def test_consult_thought_chunks_map_to_reasoning(monkeypatch) -> None:
    """agent_thought_chunk text maps to reasoning and never joins the answer."""
    result, seen = await _consult_memory("ok_with_thought", monkeypatch)
    assert result.success is True
    assert any(e.kind == EVENT_REASONING and e.text == "hmm…" for e in seen)
    assert "hmm…" not in result.final_text


async def test_consult_without_configured_command_fails_cleanly(monkeypatch) -> None:
    monkeypatch.delenv(ACP_COMMAND_ENV, raising=False)
    backend = AcpBackend()
    seen: list = []

    async def on_event(event):
        seen.append(event)

    result = await backend.consult("q", on_event=on_event)
    assert result.success is False
    assert ACP_COMMAND_ENV in result.error or "configure" in result.error
    assert any(e.kind == EVENT_ERROR for e in seen)


# ---- consult integration (real subprocess fixture, always runs) -------------------


async def test_subprocess_consult_streams_and_returns_session(monkeypatch) -> None:
    result, seen = await _consult_real_process("ok", monkeypatch)
    assert result.success is True
    assert result.session_id == "acp-test-session-1"
    assert "The answer is 4." in result.final_text
    assert any(e.kind == EVENT_TOOL for e in seen)


async def test_subprocess_consult_resumes_session(monkeypatch) -> None:
    result, _ = await _consult_real_process("ok_resume", monkeypatch, session_id="acp-sess-9")
    assert result.success is True
    assert result.session_id == "acp-sess-9"
    assert result.final_text.startswith("resumed:acp-sess-9 ")


async def test_subprocess_consult_rejected_session_fails(monkeypatch) -> None:
    result, seen = await _consult_real_process("reject", monkeypatch)
    assert result.success is False
    assert "reject" in result.error
    assert any(e.kind == EVENT_ERROR for e in seen)


@_requires_subprocess
async def test_default_spawn_consult_streams_and_returns_session(monkeypatch) -> None:
    """Pin consult's own asyncio spawn against the fixture (needs OS pipes)."""
    result, seen = await _consult_default_spawn("ok", monkeypatch)
    assert result.success is True
    assert result.session_id == "acp-test-session-1"
    assert "The answer is 4." in result.final_text
    assert any(e.kind == EVENT_TOOL for e in seen)
