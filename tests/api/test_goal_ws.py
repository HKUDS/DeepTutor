from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
router_module = importlib.import_module("deeptutor.api.routers.goal")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/goal")
    return app


def test_goal_ws_run_plan_emits_plan_and_complete(monkeypatch) -> None:
    class FakePlan:
        def model_dump(self, mode="json", by_alias=True):
            return {"plan_id": "plan_001", "plan_version": 1}

    class FakeStorage:
        def get_session_dir(self, session_id):
            from pathlib import Path

            return Path("/tmp") / session_id

        def load_plan(self, session_id):
            return FakePlan()

    class FakeOrchestrator:
        storage = FakeStorage()

        async def run_plan(self, session_id):
            return FakePlan()

    monkeypatch.setattr(router_module, "get_orchestrator", lambda: FakeOrchestrator())

    with TestClient(_build_app()) as client:
        with client.websocket_connect("/api/v1/goal/ws/goal_001") as websocket:
            websocket.send_json({"type": "run_plan"})
            first = websocket.receive_json()
            second = websocket.receive_json()

    assert first["type"] == "plan"
    assert first["data"]["plan_id"] == "plan_001"
    assert second["type"] == "complete"


def test_goal_ws_run_plan_emits_stage_events_before_plan(monkeypatch, tmp_path: Path) -> None:
    class FakePlan:
        def model_dump(self, mode="json", by_alias=True):
            return {"plan_id": "plan_001", "plan_version": 1}

    class FakeStorage:
        def get_session_dir(self, session_id):
            session_dir = tmp_path / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            event_file = session_dir / "events.jsonl"
            event_file.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "stage", "stage": "extract", "progress": 0.35}),
                        json.dumps({"type": "stage", "stage": "graph", "progress": 0.7}),
                    ]
                ),
                encoding="utf-8",
            )
            return session_dir

        def load_plan(self, session_id):
            return FakePlan()

    class FakeOrchestrator:
        storage = FakeStorage()

        async def run_plan(self, session_id):
            return FakePlan()

    monkeypatch.setattr(router_module, "get_orchestrator", lambda: FakeOrchestrator())

    with TestClient(_build_app()) as client:
        with client.websocket_connect("/api/v1/goal/ws/goal_001") as websocket:
            websocket.send_json({"type": "run_plan"})
            first = websocket.receive_json()
            second = websocket.receive_json()
            third = websocket.receive_json()
            fourth = websocket.receive_json()

    assert first["type"] == "stage"
    assert first["stage"] == "extract"
    assert second["type"] == "stage"
    assert second["stage"] == "graph"
    assert third["type"] == "plan"
    assert fourth["type"] == "complete"


def test_goal_ws_run_plan_emits_error_when_planner_raises(monkeypatch) -> None:
    class FakeStorage:
        def get_session_dir(self, session_id):
            return Path("/tmp") / session_id

    class FakeOrchestrator:
        storage = FakeStorage()

        async def run_plan(self, session_id):
            raise RuntimeError("planner exploded")

    monkeypatch.setattr(router_module, "get_orchestrator", lambda: FakeOrchestrator())

    with TestClient(_build_app()) as client:
        with client.websocket_connect("/api/v1/goal/ws/goal_001") as websocket:
            websocket.send_json({"type": "run_plan"})
            payload = websocket.receive_json()

    assert payload["type"] == "error"
    assert payload["code"] == "PLAN_FAILED"
    assert "planner exploded" in payload["content"]
