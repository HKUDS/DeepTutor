from __future__ import annotations

import io
from pathlib import Path
import tomllib
from typing import Any
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading_extensions
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import ReadingContext, ReadingExtensionRegistry
from deeptutor.reading.read_aloud import ReadAloudExtension
from deeptutor.services.path_service import PathService
from deeptutor.services.voice import VoiceProviderError


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


def _audio_client(monkeypatch, synthesize) -> TestClient:
    registry = ReadingExtensionRegistry([ReadAloudExtension()])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    monkeypatch.setattr(reading_extensions, "synthesize_speech", synthesize)
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def test_read_aloud_audio_uses_stored_text_not_client_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Stored unit text only.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    captured: dict[str, Any] = {}

    async def synthesize(text: str, **_: Any):
        captured["text"] = text
        return b"natural-audio", "audio/mpeg"

    client = _audio_client(monkeypatch, synthesize)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/read-aloud",
            json={"locator": 1, "locale": "en", "text": "Forged speech"},
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 200, response.text
    assert response.content == b"natural-audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert captured == {"text": "Stored unit text only."}


def test_read_aloud_audio_wraps_pcm_for_browser_playback(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Natural speech.", encoding="utf-8")
    material = ReadingStore().ingest(source)
    pcm = b"\x00\x00\x01\x00" * 12

    async def synthesize(_: str, **__: Any):
        return pcm, "audio/pcm;rate=24000;channels=1"

    client = _audio_client(monkeypatch, synthesize)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/read-aloud",
            json={"locator": 1},
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.readframes(audio.getnframes()) == pcm


def test_read_aloud_audio_rejects_invalid_locator(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Natural speech.", encoding="utf-8")
    material = ReadingStore().ingest(source)

    async def synthesize(_: str, **__: Any):
        raise AssertionError("invalid locator must not reach the provider")

    client = _audio_client(monkeypatch, synthesize)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/read-aloud",
            json={"locator": 2},
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == 400


def test_read_aloud_audio_requires_the_extension_grant(monkeypatch, tmp_path):
    monkeypatch.setattr(
        reading_extensions,
        "allowed_reading_extensions",
        lambda: {"vocabulary"},
    )
    client = _audio_client(monkeypatch, lambda *_: None)
    response = client.post("/api/reading/materials/mat/read-aloud", json={"locator": 1})
    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ValueError("No active TTS model is configured."), 400),
        (VoiceProviderError("provider down"), 502),
    ],
)
def test_read_aloud_audio_maps_provider_failures(monkeypatch, tmp_path, error, status_code):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Natural speech.", encoding="utf-8")
    material = ReadingStore().ingest(source)

    async def synthesize(_: str, **__: Any):
        raise error

    client = _audio_client(monkeypatch, synthesize)
    try:
        response = client.post(
            f"/api/reading/materials/{material.material_id}/read-aloud",
            json={"locator": 1},
        )
    finally:
        PathService.reset_instance()

    assert response.status_code == status_code


def test_read_aloud_rejects_undeclared_actions():
    context = ReadingContext(material_id="material", locator=1, visible_text="Text")

    try:
        ReadAloudExtension().run_action("summarize", context)
    except ValueError as exc:
        assert "Unsupported read-aloud action" in str(exc)
    else:
        raise AssertionError("undeclared action must fail")
