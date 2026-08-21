"""Security and transport tests for child-facing reading documents."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.immersive_reading.models import KidsBookAssignment
from deeptutor.immersive_reading.service import _write_json, get_kids_manager
import deeptutor.api.routers.kids as kids_router_module


class FakeImmersiveReadingService:
    def __init__(self, epub_path: Path) -> None:
        self.epub_path = epub_path

    def original_path(self, document_id: str) -> Path:
        assert document_id == "readingdoc001"
        return self.epub_path


def test_kids_epub_requires_device_session(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="Reading Doc",
            ).model_dump(mode="json")
        ],
    )

    epub_path = tmp_path / "original.epub"
    epub_path.write_bytes(b"PK-child-epub")
    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FakeImmersiveReadingService(epub_path),
    )

    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    endpoint = "/api/v1/kids/books/readingdoc001/epub"

    unauthenticated = client.get(endpoint)
    assert unauthenticated.status_code == 401

    selected = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    assert selected.status_code == 200
    authorized = client.get(
        endpoint,
        headers={"Authorization": f"Bearer {selected.json()['token']}"},
    )
    assert authorized.status_code == 200
    assert authorized.content == b"PK-child-epub"
    assert authorized.headers["content-type"] == "application/epub+zip"
