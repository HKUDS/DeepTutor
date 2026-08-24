from __future__ import annotations

from fastapi.testclient import TestClient


def _client_with_failing_route() -> TestClient:
    from deeptutor.api.main import app

    @app.get("/api/v1/__test_unhandled_exception__")
    def _raise_unhandled() -> None:
        raise RuntimeError("intentional test failure")

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_returns_json_error() -> None:
    response = _client_with_failing_route().get("/api/v1/__test_unhandled_exception__")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "detail": "RuntimeError: intentional test failure",
        "type": "RuntimeError",
    }


def test_unhandled_exception_response_carries_cors_headers() -> None:
    """The 500 must travel back out through CORSMiddleware.

    An ``@app.exception_handler(Exception)`` is installed on Starlette's
    outermost ServerErrorMiddleware, so its response skips CORS entirely and a
    cross-origin caller sees an opaque CORS failure rather than the JSON body
    above — defeating the point of returning JSON at all. The boundary is a
    middleware registered inside CORS precisely so this header survives.
    """
    client = _client_with_failing_route()
    origin = "http://cross-origin.test"

    ok = client.get("/api/v1/health", headers={"Origin": origin})
    error = client.get("/api/v1/__test_unhandled_exception__", headers={"Origin": origin})

    assert error.status_code == 500
    # Whatever the CORS policy grants a normal response, it must also grant this one.
    assert error.headers.get("access-control-allow-origin") == ok.headers.get(
        "access-control-allow-origin"
    )
    assert error.headers.get("access-control-allow-origin") is not None
