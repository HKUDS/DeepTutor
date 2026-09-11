from __future__ import annotations

from pathlib import Path
import tomllib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import reading_extensions
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import ReadingContext, ReadingExtensionRegistry
from deeptutor.reading.read_aloud import ReadAloudExtension
from deeptutor.services.path_service import PathService


def test_read_aloud_returns_verified_visible_text_only():
    context = ReadingContext(
        material_id="material",
        locator=2,
        locale="zh-CN",
        visible_text="Visible passage",
    )

    result = ReadAloudExtension().run_action("read", context)

    assert result.type == "browser_speech"
    assert result.payload == {"text": "Visible passage", "locale": "zh-CN"}


def test_read_aloud_is_registered_as_a_packaged_extension():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    group = project["project"]["entry-points"]["deeptutor.reading_extensions"]

    assert group["read_aloud"] == "deeptutor.reading.read_aloud:ReadAloudExtension"


def test_read_aloud_crosses_the_authenticated_api_boundary_with_stored_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Stored unit text only.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    registry = ReadingExtensionRegistry([ReadAloudExtension()])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    client = TestClient(app)

    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/read_aloud/actions/read",
            json={"locator": 1, "visible_text": "Forged text", "locale": "zh-CN"},
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 200, response.text
    assert response.json() == {
        "type": "browser_speech",
        "title": "",
        "message": "",
        "payload": {"text": "Stored unit text only.", "locale": "zh-CN"},
    }


def test_read_aloud_rejects_undeclared_actions():
    context = ReadingContext(material_id="material", locator=1, visible_text="Text")

    try:
        ReadAloudExtension().run_action("summarize", context)
    except ValueError as exc:
        assert "Unsupported read-aloud action" in str(exc)
    else:
        raise AssertionError("undeclared action must fail")
