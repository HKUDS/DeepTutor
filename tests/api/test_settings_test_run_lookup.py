"""The Settings connection-test endpoints answer 404 for an unknown run id.

Before this, a stale id (server restarted, page reconnected) turned into a
``KeyError`` and a 500 on the event stream, and the frontend's test card showed
a failed request instead of "this run is gone".
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.test_runner import ConfigTestRunner


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ConfigTestRunner:
    empty = ConfigTestRunner()
    monkeypatch.setattr(settings_router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(settings_router, "get_config_test_runner", lambda: empty)
    return empty


def test_events_for_unknown_run_answer_404(runner: ConfigTestRunner) -> None:
    request = SimpleNamespace()

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(settings_router.stream_service_test_events("llm", "llm-gone", request))

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Unknown test run"


def test_cancel_for_unknown_run_answers_404(runner: ConfigTestRunner) -> None:
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(settings_router.cancel_service_test("llm", "llm-gone"))

    assert excinfo.value.status_code == 404


def test_cancel_for_known_run_confirms(runner: ConfigTestRunner) -> None:
    from deeptutor.services.config.test_runner import TestRun

    run = TestRun(id="llm-live", service="llm")
    runner._runs[run.id] = run  # noqa: SLF001 - the runner exposes no inject API

    assert asyncio.run(settings_router.cancel_service_test("llm", run.id)) == {
        "message": "Cancelled"
    }
    assert run.cancelled
