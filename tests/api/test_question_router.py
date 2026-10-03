from __future__ import annotations

from contextlib import contextmanager
import importlib
import logging
from pathlib import Path
import sys
import types

from fastapi import WebSocketDisconnect
import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient


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


class _FakeMimicWebSocket:
    """Direct-call stand-in for the starlette WebSocket used by the mimic endpoint.

    ``error_send_exc`` is raised whenever an ``error`` event is sent, so tests
    can exercise what the endpoint does when the failure notice itself cannot
    reach the client.
    """

    def __init__(self, config: dict, error_send_exc: BaseException | None = None) -> None:
        self._config = config
        self._error_send_exc = error_send_exc
        self.sent: list[dict] = []
        self.closed = False

    async def accept(self) -> None:
        pass

    async def receive_json(self) -> dict:
        return self._config

    async def send_json(self, payload: dict) -> None:
        if payload.get("type") == "error" and self._error_send_exc is not None:
            raise self._error_send_exc
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


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
        config={
            "mode": "parsed",
            "paper_path": str(tmp_path / "paper"),
            "kb_name": "demo-kb",
        },
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
