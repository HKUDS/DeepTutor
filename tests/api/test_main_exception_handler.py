from __future__ import annotations

from fastapi.testclient import TestClient


def test_unhandled_exception_returns_json_error() -> None:
    from deeptutor.api.main import app

    @app.get("/api/v1/__test_unhandled_exception__")
    def _raise_unhandled() -> None:
        raise RuntimeError("intentional test failure")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/__test_unhandled_exception__")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "detail": "RuntimeError: intentional test failure",
        "type": "RuntimeError",
    }
