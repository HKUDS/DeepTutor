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
        def plan(self, source_type, source_id, force=False):
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
