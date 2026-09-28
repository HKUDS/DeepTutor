from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading_extensions
from deeptutor.learning.storage import LearningStore
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionRegistry,
    ReadingExtensionResult,
)
from deeptutor.reading.models import ReadingPosition
from deeptutor.services.path_service import PathService


@pytest.fixture
def material(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Visible passage with a verified phrase.", encoding="utf-8")
    manifest = ReadingStore().ingest(source)
    yield manifest
    PathService.reset_instance()


def _client(monkeypatch, extension) -> TestClient:
    registry = ReadingExtensionRegistry([extension])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def _extension(run_action, *, requires=(), result_types=("card",)):
    return SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id="sample",
            version="1.0.0",
            name="Sample",
            actions=[
                ReadingAction(
                    id="open",
                    label="Open",
                    requires=list(requires),
                )
            ],
            result_types=list(result_types),
        ),
        run_action=run_action,
    )


def test_action_receives_only_server_verified_visible_text(material, monkeypatch):
    captured = {}

    def run(_action, context):
        captured.update(context.model_dump())
        return ReadingExtensionResult(type="card", payload={"body": "ok"})

    client = _client(monkeypatch, _extension(run))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "selection": "forged text", "locale": "en"},
    )
    assert response.status_code == 200, response.text
    assert captured["selection"] == ""
    assert captured["visible_text"] == "Visible passage with a verified phrase."
    records = LearningStore().list_reading_records()
    assert len(records.activities) == 1
    assert records.activities[0].material_id == material.material_id
    assert records.activities[0].extension_id == "sample"
    assert records.activities[0].action == "open"
    assert records.activities[0].locator == 1
    assert records.activities[0].result_type == "card"
    assert "visible_text" not in records.activities[0].model_dump()


def test_action_succeeds_when_activity_store_fails(material, monkeypatch):
    def fail_activity(*_args, **_kwargs):
        raise OSError("activity database unavailable")

    monkeypatch.setattr(reading_extensions, "_record_reading_activity", fail_activity)
    client = _client(
        monkeypatch,
        _extension(lambda *_: ReadingExtensionResult(type="card", payload={"body": "ok"})),
    )

    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )
    assert response.status_code == 200
    assert response.json()["payload"]["body"] == "ok"


def test_source_anchor_is_loaded_from_server_position(material, monkeypatch):
    ReadingStore().save_position(
        material.material_id,
        ReadingPosition(locator=1, source_anchor="server-anchor"),
    )
    captured = {}

    def run(_action, context):
        captured.update(context.model_dump())
        return ReadingExtensionResult(type="card")

    client = _client(monkeypatch, _extension(run))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "source_anchor": "forged-anchor"},
    )

    assert response.status_code == 200, response.text
    assert captured["source_anchor"] == "server-anchor"


def test_selection_requirement_rejects_unverified_text(material, monkeypatch):
    client = _client(
        monkeypatch,
        _extension(lambda *_: pytest.fail("must not run"), requires=("selection",)),
    )
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "selection": "not in the material"},
    )
    assert response.status_code == 400


def test_selection_matches_across_line_breaks_the_text_layer_dropped(monkeypatch, tmp_path):
    # Margin line numbers: extracted onto their own lines, but the browser's
    # selection glues each one to the word before it.
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "paper.txt"
    source.write_text(
        "applications for Large Language\n1\nModels (LLMs). However, current LLMs rely on "
        "static pre-training knowledge\n2\nand lack adaptation.",
        encoding="utf-8",
    )
    manifest = ReadingStore().ingest(source)
    captured = {}

    def run(_action, context):
        captured.update(context.model_dump())
        return ReadingExtensionResult(type="card", payload={"body": "ok"})

    client = _client(monkeypatch, _extension(run, requires=("selection",)))
    try:
        response = client.post(
            f"/api/reading/materials/{manifest.material_id}/extensions/sample/actions/open",
            json={
                "locator": 1,
                "selection": "Large Language1 Models (LLMs). However, current LLMs rely on "
                "static pre-training knowledge2 and lack",
            },
        )
    finally:
        PathService.reset_instance()
    assert response.status_code == 200, response.text
    assert captured["selection"] == (
        "Large Language 1 Models (LLMs). However, current LLMs rely on "
        "static pre-training knowledge 2 and lack"
    )


def test_oversized_unit_returns_protocol_error(material, monkeypatch):
    unit_path = ReadingStore().root / material.material_id / "units" / "0001.txt"
    unit_path.write_text("x" * 60_001, encoding="utf-8")
    client = _client(
        monkeypatch,
        _extension(lambda *_: pytest.fail("must not run")),
    )

    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )

    assert response.status_code == 422
    assert "too large" in response.json()["detail"]


@pytest.mark.parametrize(
    "run_action",
    [
        lambda *_: (_ for _ in ()).throw(RuntimeError("broken plugin")),
        lambda *_: ReadingExtensionResult(type="feedback"),
    ],
)
def test_extension_failures_are_isolated(material, monkeypatch, run_action):
    client = _client(monkeypatch, _extension(run_action))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["recoverable"] is True
    assert LearningStore().list_reading_records().activities == []


def test_hanging_extension_action_times_out(material, monkeypatch):
    async def run(*_args):
        await asyncio.sleep(1)

    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    client = _client(monkeypatch, _extension(run))

    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["recoverable"] is True


def test_timed_out_sync_extension_opens_circuit_without_queueing(material, monkeypatch):
    release = threading.Event()
    calls = 0

    def run(*_args):
        nonlocal calls
        calls += 1
        release.wait(timeout=1)
        return ReadingExtensionResult(type="card")

    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    client = _client(monkeypatch, _extension(run))

    try:
        first = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
            json={"locator": 1},
        )
        second = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
            json={"locator": 1},
        )

        assert first.status_code == 503
        assert second.status_code == 503
        assert calls == 1
    finally:
        release.set()


@pytest.mark.parametrize("use_uvloop", [False, True])
def test_async_reading_action_runs_on_its_event_loop(material, monkeypatch, use_uvloop):
    """Vocabulary/translation actions must work under Uvicorn's uvloop (#1448)."""
    if use_uvloop:
        pytest.importorskip("uvloop")

    async def run(*_args):
        asyncio.get_running_loop()
        return ReadingExtensionResult(type="card", payload={"body": "translated"})

    registry = ReadingExtensionRegistry([_extension(run)])
    monkeypatch.setattr(reading_extensions, "get_reading_extension_registry", lambda: registry)
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    with TestClient(app, backend_options={"use_uvloop": use_uvloop}) as client:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
            json={"locator": 1},
        )
    assert response.status_code == 200
    assert response.json()["payload"]["body"] == "translated"


@pytest.mark.parametrize("sync_wrapper", [False, True])
def test_async_reading_action_can_be_retried_after_timeout(material, monkeypatch, sync_wrapper):
    calls = 0

    async def run(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(1)
        return ReadingExtensionResult(type="card")

    handler = (lambda *args: run(*args)) if sync_wrapper else run
    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    client = _client(monkeypatch, _extension(handler))
    url = f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open"
    assert client.post(url, json={"locator": 1}).status_code == 503
    assert client.post(url, json={"locator": 1}).status_code == 200
    assert calls == 2


def test_reading_action_logs_the_cause_of_unavailability(material, monkeypatch, caplog):
    def run(*_args):
        raise RuntimeError("provider unavailable")

    client = _client(monkeypatch, _extension(run))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )
    assert response.status_code == 503
    assert any(
        record.exc_info and "action open failed" in record.message for record in caplog.records
    )


def test_sync_reading_failure_does_not_disable_retry(material, monkeypatch):
    calls = 0

    def run(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary provider failure")
        return ReadingExtensionResult(type="card")

    client = _client(monkeypatch, _extension(run))
    url = f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open"
    assert client.post(url, json={"locator": 1}).status_code == 503
    assert client.post(url, json={"locator": 1}).status_code == 200


def test_language_model_errors_are_reported_distinctly(material, monkeypatch):
    from deeptutor.services.llm.exceptions import LLMAuthenticationError

    def run(*_args):
        raise LLMAuthenticationError("Invalid API key")

    client = _client(monkeypatch, _extension(run))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["recoverable"] is True
    assert "language model" in detail["message"].lower()


def test_timed_out_async_extension_can_retry(material, monkeypatch):
    calls = 0

    async def run(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(1)
        return ReadingExtensionResult(type="card")

    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    client = _client(monkeypatch, _extension(run))

    first = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )
    second = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )

    assert first.status_code == 503
    assert first.json()["detail"]["reason"] == "timed_out"
    assert second.status_code == 200
    assert calls == 2


def test_async_extension_ignores_stale_circuit(material, monkeypatch):
    async def run(*_args):
        return ReadingExtensionResult(type="card", payload={"body": "ok"})

    extension = _extension(run)
    registry = ReadingExtensionRegistry([extension])
    registry.mark_timed_out("sample")
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    client = TestClient(app)

    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )

    assert response.status_code == 200, response.text
    assert response.json()["type"] == "card"


def test_plugin_exception_reason_is_returned(material, monkeypatch):
    client = _client(
        monkeypatch,
        _extension(lambda *_: (_ for _ in ()).throw(RuntimeError("broken plugin"))),
    )
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "broken plugin"
