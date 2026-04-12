from __future__ import annotations

import importlib

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
router_module = importlib.import_module("deeptutor.api.routers.goal")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/goal")
    return app


def test_create_session_route(monkeypatch) -> None:
    class FakeOrchestrator:
        async def create_session(self, kb_name, goal_config):
            return type("Session", (), {"session_id": "goal_20260409_001", "status": "created"})()

    fake_orchestrator = FakeOrchestrator()
    monkeypatch.setattr(router_module, "get_orchestrator", lambda: fake_orchestrator)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/goal/create_session",
            json={
                "kb_name": "placeholder_kb",
                "goal_config": {"goal_level": "foundation", "daily_minutes": 90},
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["session_id"] == "goal_20260409_001"


def test_replan_route_returns_diff(monkeypatch) -> None:
    class FakeDiff:
        def model_dump(self, mode="json"):
            return {"added_tasks": ["task_2"], "moved_tasks": [], "dropped_tasks": []}

    class FakePlan:
        plan_version = 2
        diff = FakeDiff()

    class FakeOrchestrator:
        async def replan(self, session_id, reason):
            return FakePlan()

    fake_orchestrator = FakeOrchestrator()
    monkeypatch.setattr(router_module, "get_orchestrator", lambda: fake_orchestrator)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/goal/session/goal_001/replan",
            json={"reason": "low_accuracy", "strategy": "rule_based"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["plan_version"] == 2
    assert response.json()["data"]["diff"]["added_tasks"] == ["task_2"]


def test_submit_feedback_route_accepts_payload(monkeypatch) -> None:
    captured = {}

    class FakeOrchestrator:
        async def submit_feedback(self, session_id, feedback):
            captured["session_id"] = session_id
            captured["task_id"] = feedback.task_id
            return {"accepted": True, "next_action": "none"}

    fake_orchestrator = FakeOrchestrator()
    monkeypatch.setattr(router_module, "get_orchestrator", lambda: fake_orchestrator)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/goal/session/goal_001/feedback",
            json={
                "feedback_id": "fb_001",
                "task_id": "task_day1_001",
                "completion": "done",
                "actual_minutes": 35,
                "quiz": {"score": 4, "total": 5},
                "reflection": "掌握不错",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["accepted"] is True
    assert captured == {"session_id": "goal_001", "task_id": "task_day1_001"}


def test_get_plan_returns_plan_not_ready_error_when_missing(monkeypatch) -> None:
    class FakeStorage:
        def load_plan(self, session_id):
            raise FileNotFoundError(session_id)

    class FakeOrchestrator:
        storage = FakeStorage()

    fake_orchestrator = FakeOrchestrator()
    monkeypatch.setattr(router_module, "get_orchestrator", lambda: fake_orchestrator)

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/goal/session/goal_404/plan")

    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PLAN_NOT_READY"


def test_run_plan_returns_plan_failed_error(monkeypatch) -> None:
    class FakeOrchestrator:
        async def run_plan(self, session_id):
            raise ValueError("planner returned empty task list")

    monkeypatch.setattr(router_module, "get_orchestrator", lambda: FakeOrchestrator())

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/goal/session/goal_001/run_plan")

    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PLAN_FAILED"


def test_generate_practice_returns_task_not_found_error(monkeypatch) -> None:
    class FakeOrchestrator:
        async def generate_practice(self, session_id, task_id, count=3):
            raise ValueError("Task not found")

    monkeypatch.setattr(router_module, "get_orchestrator", lambda: FakeOrchestrator())

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/goal/session/goal_001/task/task_missing/generate_practice",
            json={"count": 3, "difficulty": "medium", "question_type": "choice"},
        )

    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "TASK_NOT_FOUND"


def test_get_day_plan_detail_route_success(monkeypatch) -> None:
    class FakeStorage:
        def load_session(self, session_id):
            return type("Session", (), {"session_id": session_id})()

    class FakeDayDetail:
        def model_dump(self, mode="json"):
            return {
                "session_id": "goal_001",
                "day_index": 1,
                "date": "2026-04-10",
                "objective_summary": "完成当日核心任务",
                "time_blocks": [],
                "key_points": [],
                "pitfalls": [],
                "acceptance_criteria": [],
                "review_actions": [],
                "linked_task_ids": [],
            }

    class FakeOrchestrator:
        storage = FakeStorage()

        def get_day_plan_detail(self, session_id, day_index):
            return FakeDayDetail()

    monkeypatch.setattr(router_module, "get_orchestrator", lambda: FakeOrchestrator())

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/goal/session/goal_001/day/1")

    assert response.status_code == 200
    assert response.json()["data"]["day_index"] == 1
    assert response.json()["data"]["objective_summary"] == "完成当日核心任务"


def test_get_day_plan_detail_route_returns_day_not_found(monkeypatch) -> None:
    class FakeStorage:
        def load_session(self, session_id):
            return type("Session", (), {"session_id": session_id})()

    class FakeOrchestrator:
        storage = FakeStorage()

        def get_day_plan_detail(self, session_id, day_index):
            raise ValueError(f"Day not found: {day_index}")

    monkeypatch.setattr(router_module, "get_orchestrator", lambda: FakeOrchestrator())

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/goal/session/goal_001/day/99")

    assert response.status_code == 400
    payload = response.json()["detail"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DAY_NOT_FOUND"


def test_goal_router_end_to_end_flow(monkeypatch) -> None:
    class FakeDiff:
        def model_dump(self, mode="json"):
            return {"added_tasks": ["task_day2_review_001"], "moved_tasks": [], "dropped_tasks": []}

    class FakePlan:
        def __init__(self, version: int):
            self.plan_id = "plan_001"
            self.plan_version = version
            self.status = "ready"
            self.diff = FakeDiff() if version > 1 else None

        def model_dump(self, mode="json", by_alias=True):
            return {
                "plan_id": self.plan_id,
                "plan_version": self.plan_version,
                "status": self.status,
                "days": [{"day_index": 1, "budget_minutes": 90, "task_ids": ["task_day1_001"], "notes": ""}],
                "tasks": [
                    {
                        "task_id": "task_day1_001",
                        "day_index": 1,
                        "node_id": "node_limit",
                        "title": "Learn limit basics",
                        "kind": "learn",
                        "estimate_minutes": 45,
                        "objective": "Understand limits",
                    }
                ],
            }

    class FakeSession:
        def __init__(self):
            self.session_id = "goal_20260409_001"
            self.status = "created"
            self.plan_version = 0

    class FakeStorage:
        def __init__(self, session: FakeSession, plan: FakePlan):
            self._session = session
            self._plan = plan

        def load_session(self, session_id):
            return self._session

        def load_plan(self, session_id):
            return self._plan

    class FakeOrchestrator:
        def __init__(self):
            self._session = FakeSession()
            self._plan = FakePlan(version=1)
            self.storage = FakeStorage(self._session, self._plan)

        async def create_session(self, kb_name, goal_config):
            self._session.status = "created"
            self._session.plan_version = 0
            return self._session

        async def run_plan(self, session_id):
            self._session.status = "ready"
            self._session.plan_version = 1
            self._plan = FakePlan(version=1)
            self.storage._plan = self._plan
            return self._plan

        async def submit_feedback(self, session_id, feedback):
            return {"accepted": True, "next_action": "none"}

        async def replan(self, session_id, reason):
            self._session.plan_version = 2
            self._plan = FakePlan(version=2)
            self.storage._plan = self._plan
            return self._plan

        async def generate_practice(self, session_id, task_id, count=3):
            return {
                "practice_set_path": f"data/user/goal/{session_id}/practice/{task_id}.json",
                "practice_set": {
                    "questions": [{"question": "What is a limit?", "reference_answer": "A value approached"}]
                },
            }

    fake_orchestrator = FakeOrchestrator()
    monkeypatch.setattr(router_module, "get_orchestrator", lambda: fake_orchestrator)

    with TestClient(_build_app()) as client:
        created = client.post(
            "/api/v1/goal/create_session",
            json={
                "kb_name": "placeholder_kb",
                "goal_config": {"goal_level": "foundation", "daily_minutes": 90},
            },
        )
        session_id = created.json()["data"]["session_id"]

        run_result = client.post(f"/api/v1/goal/session/{session_id}/run_plan")
        session = client.get(f"/api/v1/goal/session/{session_id}")
        plan = client.get(f"/api/v1/goal/session/{session_id}/plan")
        feedback = client.post(
            f"/api/v1/goal/session/{session_id}/feedback",
            json={
                "feedback_id": "fb_001",
                "task_id": "task_day1_001",
                "completion": "partial",
                "quiz": {"score": 2, "total": 5},
            },
        )
        replanned = client.post(
            f"/api/v1/goal/session/{session_id}/replan",
            json={"reason": "manual_feedback", "strategy": "rule_based"},
        )
        practice = client.post(
            f"/api/v1/goal/session/{session_id}/task/task_day1_001/generate_practice",
            json={"count": 1, "difficulty": "medium", "question_type": "choice"},
        )

    assert created.status_code == 200
    assert run_result.status_code == 200
    assert session.status_code == 200
    assert plan.status_code == 200
    assert feedback.status_code == 200
    assert replanned.status_code == 200
    assert practice.status_code == 200

    assert run_result.json()["data"]["plan_version"] == 1
    assert session.json()["data"]["plan_version"] == 1
    assert plan.json()["data"]["plan_version"] == 1
    assert feedback.json()["data"]["accepted"] is True
    assert replanned.json()["data"]["plan_version"] == 2
    assert replanned.json()["data"]["diff"]["added_tasks"] == ["task_day2_review_001"]
    assert practice.json()["data"]["practice_set_path"].endswith("task_day1_001.json")
