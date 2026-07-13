"""Tests for the selective_access_log middleware in main.py.

Verifies that non-200 responses are logged with the 5-element args tuple
(client_addr, method, full_path, http_version, status_code) — the shape that
was needed for uvicorn's AccessFormatter in #334 — while 200s stay silent.

The real middleware logs through the ``deeptutor.access`` logger, which carries
its own stdout handler with ``propagate=False`` (uvicorn's own access log is
disabled on every launch path). Because it does not propagate to root, we
capture by attaching a handler directly to that logger rather than via caplog.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

ACCESS_LOGGER = "deeptutor.access"


def _build_app_with_middleware():
    """Build a minimal app that replicates the selective_access_log middleware."""
    test_app = FastAPI()
    _access_logger = logging.getLogger(ACCESS_LOGGER)

    @test_app.middleware("http")
    async def selective_access_log(request: Request, call_next):
        response = await call_next(request)
        if response.status_code != 200:
            _access_logger.info(
                '%s - "%s %s HTTP/%s" %d',
                request.client.host if request.client else "-",
                request.method,
                request.url.path,
                request.scope.get("http_version", "1.1"),
                response.status_code,
            )
        return response

    @test_app.get("/ok")
    def ok():
        return {"status": "ok"}

    @test_app.get("/not-found")
    def not_found():
        return JSONResponse({"error": "not found"}, status_code=404)

    return test_app


class _RecordCollector(logging.Handler):
    """Capture emitted records directly on the access logger (no propagation)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _CaptureAccess:
    def __enter__(self) -> _RecordCollector:
        self._logger = logging.getLogger(ACCESS_LOGGER)
        self._handler = _RecordCollector()
        self._prev_level = self._logger.level
        self._logger.setLevel(logging.INFO)
        self._logger.addHandler(self._handler)
        return self._handler

    def __exit__(self, *exc) -> None:
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._prev_level)


class TestSelectiveAccessLog:
    """selective_access_log middleware must emit 5-arg tuples for the formatter."""

    def test_non_200_log_has_five_args(self):
        """Non-200 response log record args must have 5 elements (#334)."""
        app = _build_app_with_middleware()
        with _CaptureAccess() as cap:
            with TestClient(app) as client:
                client.get("/not-found")

        assert len(cap.records) >= 1
        record = cap.records[0]
        assert len(record.args) == 5, (
            f"Expected 5-element args for AccessFormatter, got {len(record.args)}"
        )
        client_addr, method, path, http_version, status_code = record.args
        assert method == "GET"
        assert path == "/not-found"
        assert http_version in ("1.0", "1.1", "2")
        assert status_code == 404

    def test_200_not_logged(self):
        """200 responses should not produce deeptutor.access log records."""
        app = _build_app_with_middleware()
        with _CaptureAccess() as cap:
            with TestClient(app) as client:
                client.get("/ok")

        ok_records = [
            r for r in cap.records if r.args and len(r.args) >= 3 and "/ok" in str(r.args[2])
        ]
        assert len(ok_records) == 0
