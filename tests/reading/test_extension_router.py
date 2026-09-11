from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading_extensions
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
