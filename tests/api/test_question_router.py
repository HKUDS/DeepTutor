from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib
import logging
from pathlib import Path
import sys
import types

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
WebSocketDisconnect = pytest.importorskip("fastapi").WebSocketDisconnect


@pytest.fixture(autouse=True)
def _cleanup_question_router_module():
    yield
    sys.modules.pop("deeptutor.api.routers.question", None)


class _DummyProcessLogEvent:
    def __init__(self, **kwargs) -> None:
        self.data = {"type": "process_log", **kwargs}

    def to_dict(self):
        return self.data


@contextmanager
def _noop_context(*_args, **_kwargs):
    yield


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    return module


def _fake_config_module() -> types.ModuleType:
    """Stand in for ``deeptutor.services.config``, deferring the rest to the real one.

    Only the two names the question router reads at import time are overridden.
    Everything else resolves to the real attribute, because the websocket
    handler lazily imports ``deeptutor.api.routers.auth``, which pulls
    *unrelated* loaders (auth settings, integrations, …) out of this same
    package. Stubbing those one at a time was whack-a-mole, and skipping them
    left the test passing only when an earlier test had already put
    ``deeptutor.api.routers.auth`` in ``sys.modules`` — so the lazy import was
    a cache hit that never reached this stand-in. Green in a full run, red on
    its own.
    """
    real = importlib.import_module("deeptutor.services.config")
    module = types.ModuleType("deeptutor.services.config")
    module.__getattr__ = lambda name: getattr(real, name)  # PEP 562
    module.PROJECT_ROOT = Path.cwd()
    module.load_config_with_main = lambda *_args, **_kwargs: {}
    return module


def _load_question_router_module(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("deeptutor.api.routers.question", None)

    fake_agents = _package("deeptutor.agents")
    fake_agents_question = types.ModuleType("deeptutor.agents.question")
    fake_agents_question.AgentCoordinator = object
    fake_agents.question = fake_agents_question
    monkeypatch.setitem(sys.modules, "deeptutor.agents", fake_agents)
    monkeypatch.setitem(sys.modules, "deeptutor.agents.question", fake_agents_question)

    fake_logging = _package("deeptutor.logging")
    fake_logging.ProcessLogEvent = _DummyProcessLogEvent
    fake_logging.bind_log_context = _noop_context
    fake_logging.capture_process_logs = _noop_context
    fake_logging.current_log_context = lambda: {}
    monkeypatch.setitem(sys.modules, "deeptutor.logging", fake_logging)

    monkeypatch.setitem(sys.modules, "deeptutor.services.config", _fake_config_module())

    fake_llm_package = _package("deeptutor.services.llm")
    fake_llm_config = types.ModuleType("deeptutor.services.llm.config")
    fake_llm_config.get_llm_config = lambda: None
    fake_llm_package.config = fake_llm_config
    monkeypatch.setitem(sys.modules, "deeptutor.services.llm", fake_llm_package)
    monkeypatch.setitem(sys.modules, "deeptutor.services.llm.config", fake_llm_config)

    fake_settings_package = _package("deeptutor.services.settings")
    fake_interface_settings = types.ModuleType("deeptutor.services.settings.interface_settings")
    fake_interface_settings.get_ui_language = lambda default="en": default
    # The router asks for the *response* language now that reader-facing output
    # no longer follows the interface locale; the stand-in module has to offer
    # both readers the real one does.
    fake_interface_settings.get_response_language = lambda default="en": default
    fake_settings_package.interface_settings = fake_interface_settings
    monkeypatch.setitem(sys.modules, "deeptutor.services.settings", fake_settings_package)
    monkeypatch.setitem(
        sys.modules,
        "deeptutor.services.settings.interface_settings",
        fake_interface_settings,
    )

    fake_tools = _package("deeptutor.tools")
    fake_tools_question = types.ModuleType("deeptutor.tools.question")

    async def _default_mimic_exam_questions(*_args, **_kwargs):
        return {"success": True}

    fake_tools_question.mimic_exam_questions = _default_mimic_exam_questions
    fake_tools.question = fake_tools_question
    monkeypatch.setitem(sys.modules, "deeptutor.tools", fake_tools)
    monkeypatch.setitem(sys.modules, "deeptutor.tools.question", fake_tools_question)

    return importlib.import_module("deeptutor.api.routers.question")


def _build_app(router_module) -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/question")
    app.include_router(router_module.ws_router, prefix="/ws/questions")
    return app


def test_mimic_websocket_accepts_config_and_returns_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    async def _fake_mimic_exam_questions(*_args, **_kwargs):
        return {"success": False, "error": "stub mimic failure"}

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _fake_mimic_exam_questions)
    # ``MIMIC_OUTPUT_DIR`` was a module-level constant resolved at import time
    # (which froze it to the admin path). It's now a per-call helper so the
    # path follows whichever user is running. Patch the helper instead.
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    with TestClient(_build_app(question_router_module)) as client:
        with client.websocket_connect("/ws/questions/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "parsed",
                    "paper_path": str(tmp_path / "paper"),
                    "kb_name": "demo-kb",
                    "max_questions": 3,
                }
            )
            messages = [websocket.receive_json() for _ in range(3)]

    assert [message["type"] for message in messages] == ["status", "status", "error"]
    assert messages[0]["stage"] == "init"
    assert messages[1]["stage"] == "processing"
    assert messages[2]["content"] == "stub mimic failure"


# ---------------------------------------------------------------------------
# DT-22 HIGH-chain regression pins (evidence: agent/dt22-todo-scan report §7).
#
# Two HIGH findings on this router, both `except Exception: pass` around
# failure-prone I/O inside ``websocket_mimic_generate``:
#
#   1. the outer error broadcast — ``send_json({"type": "error", ...})``
#      (report line 323; drifted to the outer handler's broadcast);
#   2. the stdout redirect write — ``StdoutInterceptor.write`` (renamed from
#      ``TeeWrite`` since the scan) swallowing failures of the real terminal
#      write (report line 131).
#
# These are failure-injection characterization tests: they pin the contract
# that a send/write failure stays isolated and that cleanup still runs (no
# process-wide stdout hijack, websocket always closed, run never crashes the
# handler). 现状豁免 (current-behavior exemption): the swallowed failures are
# themselves *silent* — no log record — and surfacing them would require a
# code change, which is out of scope for this test-only card; the exemption
# is recorded here instead of "fixing" the swallow.
# ---------------------------------------------------------------------------


class _FakeMimicWebSocket:
    """Server-side websocket stand-in with targeted send/receive failures."""

    def __init__(
        self,
        incoming: list[dict] | None = None,
        fail_send_when=None,
        disconnect_immediately: bool = False,
        error_send_exc: BaseException | None = None,
    ) -> None:
        self._incoming = list(incoming or [])
        self._fail_send_when = fail_send_when
        self._disconnect_immediately = disconnect_immediately
        self._error_send_exc = error_send_exc
        self.accepted = False
        self.sent: list[dict] = []
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> dict:
        if self._disconnect_immediately:
            raise WebSocketDisconnect(code=1000)
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect(code=1000)

    async def send_json(self, payload: dict) -> None:
        if payload.get("type") == "error" and self._error_send_exc is not None:
            raise self._error_send_exc
        if self._fail_send_when is not None and self._fail_send_when(payload):
            raise RuntimeError("connection is closed")
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


class _BrokenTerminal:
    """Stdout stand-in whose write/flush always fail (detached terminal)."""

    def __init__(self) -> None:
        self.write_attempts = 0
        self.flush_attempts = 0

    def write(self, message: str) -> int:
        self.write_attempts += 1
        raise OSError("terminal detached")

    def flush(self) -> None:
        self.flush_attempts += 1
        raise OSError("terminal detached")


def _parsed_mode_config(tmp_path: Path) -> dict:
    return {
        "mode": "parsed",
        "paper_path": str(tmp_path / "paper"),
        "kb_name": "demo-kb",
        "max_questions": 1,
    }


async def _run_mimic_endpoint(
    monkeypatch: pytest.MonkeyPatch, question_router_module, websocket: _FakeMimicWebSocket
) -> None:
    """Invoke the endpoint directly with auth bypassed, under a timeout."""

    async def _allow(_websocket) -> str:
        return "test-user-token"

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", _allow)

    await asyncio.wait_for(question_router_module.websocket_mimic_generate(websocket), timeout=10)


@pytest.mark.asyncio
async def test_mimic_error_broadcast_failure_is_isolated_and_cleanup_still_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DT-22 HIGH pin #1: outer error broadcast swallow stays isolated.

    When the workflow itself raises and the client can no longer receive the
    error frame, the send failure must not escape the handler, stdout must be
    restored, and the websocket must still be closed. Removing the swallow
    naively would leak the send ``RuntimeError`` out of the endpoint and this
    test would go red — that is the regression being pinned.
    """
    question_router_module = _load_question_router_module(monkeypatch)

    async def _exploding_mimic(*_args, **_kwargs):
        raise RuntimeError("mimic exploded")

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _exploding_mimic)
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    websocket = _FakeMimicWebSocket(
        incoming=[_parsed_mode_config(tmp_path)],
        fail_send_when=lambda payload: payload.get("type") == "error",
    )
    terminal = object()
    monkeypatch.setattr(sys, "stdout", terminal)

    await _run_mimic_endpoint(monkeypatch, question_router_module, websocket)

    assert websocket.accepted
    assert websocket.closed
    assert [message["type"] for message in websocket.sent] == ["status", "status"]
    assert sys.stdout is terminal


@pytest.mark.asyncio
async def test_mimic_client_disconnect_before_config_ends_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DT-22 HIGH chain #1, disconnect flavor: a client vanishing right after
    accept must end the run without raising, without any frames sent, and with
    stdout restored and the socket close attempted (swallowed when already
    gone)."""
    question_router_module = _load_question_router_module(monkeypatch)

    websocket = _FakeMimicWebSocket(disconnect_immediately=True)
    terminal = object()
    monkeypatch.setattr(sys, "stdout", terminal)

    await _run_mimic_endpoint(monkeypatch, question_router_module, websocket)

    assert websocket.accepted
    assert websocket.closed
    assert websocket.sent == []
    assert sys.stdout is terminal


@pytest.mark.asyncio
async def test_mimic_failed_result_broadcast_to_dead_client_still_restores_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DT-22 HIGH chain #1, result-failure flavor: when the workflow reports
    ``success: False`` and the error broadcast itself fails because the client
    is gone, the run still cleans up (stdout restored, socket closed) instead
    of crashing."""
    question_router_module = _load_question_router_module(monkeypatch)

    async def _failing_mimic(*_args, **_kwargs):
        return {"success": False, "error": "generation failed"}

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _failing_mimic)
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    websocket = _FakeMimicWebSocket(
        incoming=[_parsed_mode_config(tmp_path)],
        fail_send_when=lambda payload: payload.get("type") == "error",
    )
    terminal = object()
    monkeypatch.setattr(sys, "stdout", terminal)

    await _run_mimic_endpoint(monkeypatch, question_router_module, websocket)

    assert websocket.closed
    assert [message["type"] for message in websocket.sent] == ["status", "status"]
    assert sys.stdout is terminal


@pytest.mark.asyncio
async def test_mimic_print_survives_detached_terminal_and_still_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DT-22 HIGH pin #2: the stdout redirect swallow keeps generation alive.

    With the real terminal's write/flush raising, a ``print`` from inside the
    workflow must not propagate, its cleaned (ANSI-stripped) text must still
    reach the client as a process_log frame, and process stdout must be
    restored afterwards. 现状豁免: the terminal failure itself is swallowed
    silently — surfacing it (e.g. a debug log) would be a code change outside
    this test-only card.
    """
    question_router_module = _load_question_router_module(monkeypatch)

    async def _printing_mimic(*_args, **_kwargs):
        print("Generating \x1b[31mquestions\x1b[0m...")
        sys.stdout.flush()
        await asyncio.sleep(0)
        return {"success": True, "generated_questions": ["q1"], "failed_questions": []}

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _printing_mimic)
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    websocket = _FakeMimicWebSocket(incoming=[_parsed_mode_config(tmp_path)])
    terminal = _BrokenTerminal()
    monkeypatch.setattr(sys, "stdout", terminal)

    await _run_mimic_endpoint(monkeypatch, question_router_module, websocket)

    assert [message["type"] for message in websocket.sent] == [
        "status",
        "status",
        "process_log",
        "complete",
    ]
    log_frame = websocket.sent[2]
    assert log_frame["message"] == "Generating questions..."
    assert terminal.write_attempts >= 1
    assert terminal.flush_attempts >= 1
    assert sys.stdout is terminal


@pytest.mark.asyncio
async def test_mimic_log_pusher_send_failure_stops_stream_without_breaking_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DT-22 HIGH chain #1, mid-stream flavor: the log pusher treats a failed
    send as end-of-stream (break) instead of crashing the run — the workflow
    still completes, the final ``complete`` frame still goes out where
    possible, and cleanup runs."""
    question_router_module = _load_question_router_module(monkeypatch)

    async def _printing_mimic(*_args, **_kwargs):
        print("stream me")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return {"success": True, "generated_questions": [], "failed_questions": []}

    monkeypatch.setattr(question_router_module, "mimic_exam_questions", _printing_mimic)
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    websocket = _FakeMimicWebSocket(
        incoming=[_parsed_mode_config(tmp_path)],
        fail_send_when=lambda payload: payload.get("type") == "process_log",
    )
    terminal = object()
    monkeypatch.setattr(sys, "stdout", terminal)

    await _run_mimic_endpoint(monkeypatch, question_router_module, websocket)

    assert [message["type"] for message in websocket.sent] == ["status", "status", "complete"]
    assert websocket.closed
    assert sys.stdout is terminal


async def _run_mimic_endpoint_until_error_send(
    question_router_module, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error_send_exc
) -> _FakeMimicWebSocket:
    async def _raising_mimic_exam_questions(*_args, **_kwargs):
        raise RuntimeError("mimic workflow exploded")

    monkeypatch.setattr(
        question_router_module, "mimic_exam_questions", _raising_mimic_exam_questions
    )
    monkeypatch.setattr(
        question_router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers"
    )

    async def _anonymous_ws_auth(_websocket):
        return None

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", _anonymous_ws_auth)

    websocket = _FakeMimicWebSocket(
        incoming=[_parsed_mode_config(tmp_path)],
        error_send_exc=error_send_exc,
    )
    await question_router_module.websocket_mimic_generate(websocket)
    return websocket


@pytest.mark.asyncio
async def test_mimic_error_event_send_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="deeptutor.api.routers.question"):
        websocket = await _run_mimic_endpoint_until_error_send(
            question_router_module, monkeypatch, tmp_path, ConnectionError("peer reset")
        )

    assert websocket.closed
    # The original workflow failure is still logged server-side.
    assert any(
        record.levelno == logging.ERROR and "Mimic generation error" in record.getMessage()
        for record in caplog.records
    )
    # The secondary failure to deliver the error event must not be swallowed.
    assert any(
        record.levelno >= logging.WARNING and "Failed to send error event" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "send_exc",
    [
        WebSocketDisconnect(code=1001),
        RuntimeError('Cannot call "send" once a close message has been sent.'),
    ],
)
async def test_mimic_error_event_send_failure_on_closed_socket_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    send_exc: BaseException,
) -> None:
    question_router_module = _load_question_router_module(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="deeptutor.api.routers.question"):
        await _run_mimic_endpoint_until_error_send(
            question_router_module, monkeypatch, tmp_path, send_exc
        )

    # A closed/disconnected client is expected during teardown, not a warning.
    assert not any(
        record.levelno >= logging.WARNING and "Failed to send error event" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        record.levelno == logging.DEBUG and "WebSocket closed" in record.getMessage()
        for record in caplog.records
    )
