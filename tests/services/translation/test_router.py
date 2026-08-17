import json

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_translation_health_and_empty_board(monkeypatch):
    from deeptutor.services.translation import router as router_module

    class FakeService:
        def _board(self, **kwargs):
            assert kwargs["source_type"] == "bilingual"
            assert kwargs["source_id"] == "p1"
            return {
                "tasks": [],
                "summary": {
                    "total": 0,
                    "queued": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0,
                    "filtered_total": 0,
                    "filtered_queued": 0,
                    "filtered_running": 0,
                    "filtered_completed": 0,
                    "filtered_failed": 0,
                    "is_running": False,
                    "last_run_at": 0,
                },
                "sources": [],
            }

    monkeypatch.setattr(router_module, "get_translation_task_service", lambda: FakeService())
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/translation")
    client = TestClient(app)

    assert client.get("/api/v1/translation/health").json()["status"] == "healthy"
    response = client.get(
        "/api/v1/translation/tasks",
        params={"source_type": "bilingual", "source_id": "p1"},
    )
    assert response.status_code == 200
    assert response.json()["tasks"] == []


def test_plan_maps_invalid_source_id_to_bad_request(monkeypatch):
    from deeptutor.services.translation import router as router_module

    class FakeService:
        async def plan_with_review(self, source_type, source_id, force=False):
            raise ValueError("Invalid bilingual pairing id")

    monkeypatch.setattr(router_module, "get_translation_task_service", lambda: FakeService())
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/translation")
    client = TestClient(app)

    response = client.post(
        "/api/v1/translation/tasks/plan",
        json={"source_type": "bilingual", "source_id": "../../outside"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid bilingual pairing id"


def test_cancel_route_invokes_service(monkeypatch):
    from deeptutor.services.translation import router as router_module

    class FakeService:
        def __init__(self):
            self.run_id: str | None = None
            self.cancel_called = False

        def cancel_run(self, run_id: str):
            self.cancel_called = True
            self.run_id = run_id
            return {"run_id": run_id, "status": "cancelled"}

    service = FakeService()
    monkeypatch.setattr(router_module, "get_translation_task_service", lambda: service)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/translation")
    client = TestClient(app)

    response = client.post("/api/v1/translation/tasks/runs/run-1/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert service.cancel_called is True
    assert service.run_id == "run-1"


def test_stream_starts_run_and_emits_group_event(monkeypatch):
    from deeptutor.services.translation import router as router_module

    task = {
        "id": "task-1",
        "source_type": "bilingual",
        "source_id": "p1",
        "chapter_id": "ch1",
        "status": "queued",
        "group_index": 3,
    }
    board = {
        "tasks": [task],
        "summary": {
            "total": 1,
            "queued": 1,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "filtered_total": 1,
            "filtered_queued": 1,
            "filtered_running": 0,
            "filtered_completed": 0,
            "filtered_failed": 0,
            "is_running": False,
            "last_run_at": 0,
        },
        "sources": [],
    }

    class FakeService:
        def __init__(self):
            self.run_called = False

        def _board(self, **kwargs):
            return board

        def start_run(self, **kwargs):
            return {"run_id": "run-1", "task_ids": [task["id"]]}

        async def run(self, run_id):
            self.run_called = True

        def subscribe(self, run_id):
            async def events():
                yield {"type": "snapshot", "board": board}
                yield {
                    "type": "group_translated",
                    "task": {**task, "status": "completed", "translation": "译文"},
                    "board": board,
                }

            return events()

    service = FakeService()
    monkeypatch.setattr(router_module, "get_translation_task_service", lambda: service)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/translation")
    client = TestClient(app)

    response = client.get(
        "/api/v1/translation/tasks/stream",
        params={"source_type": "bilingual", "source_id": "p1", "chapter_id": "ch1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert service.run_called is True
    assert "event: group_translated" in response.text
    assert '"translation":"译文"' in response.text


def test_stream_without_active_tasks_returns_snapshot_only(monkeypatch):
    from deeptutor.services.translation import router as router_module

    board = {
        "tasks": [],
        "summary": {
            "total": 0,
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "filtered_total": 0,
            "filtered_queued": 0,
            "filtered_running": 0,
            "filtered_completed": 0,
            "filtered_failed": 0,
            "is_running": False,
            "last_run_at": 0,
        },
        "sources": [],
    }

    class FakeService:
        def __init__(self):
            self.subscribed = False

        def _board(self, **kwargs):
            return board

        def start_run(self, **kwargs):
            return {"run_id": None, "task_ids": []}

        async def run(self, run_id):
            raise AssertionError("stream should not start a run without active tasks")

        def subscribe(self, run_id):
            self.subscribed = True

            async def events():
                while True:
                    yield {"type": "heartbeat"}

            return events()

    service = FakeService()
    monkeypatch.setattr(router_module, "get_translation_task_service", lambda: service)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/translation")
    client = TestClient(app)

    response = client.get(
        "/api/v1/translation/tasks/stream",
        params={"source_type": "bilingual", "source_id": "p1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: ") == 1
    assert response.text.endswith("\n\n")
    payload = json.loads(response.text.split("data: ", 1)[1])
    assert payload == {"type": "snapshot", "run_id": None, "sequence": 0, "board": board}
    assert service.subscribed is False
