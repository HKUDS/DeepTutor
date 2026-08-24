from __future__ import annotations

from pathlib import Path
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
    app.include_router(reading_extensions.router, prefix="/api/v1/reading")
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
        f"/api/v1/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "selection": "forged text", "locale": "en"},
    )
    assert response.status_code == 200, response.text
    assert captured["selection"] == ""
    assert captured["visible_text"] == "Visible passage with a verified phrase."


def test_selection_requirement_rejects_unverified_text(material, monkeypatch):
    client = _client(
        monkeypatch,
        _extension(lambda *_: pytest.fail("must not run"), requires=("selection",)),
    )
    response = client.post(
        f"/api/v1/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "selection": "not in the material"},
    )
    assert response.status_code == 400


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
        f"/api/v1/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["recoverable"] is True
