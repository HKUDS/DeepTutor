from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import visualizers as visualizers_router
from deeptutor.visualizers.registry import VisualizerRegistry
from deeptutor.visualizers.store import VisualizerStore


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    registry = VisualizerRegistry(
        store=VisualizerStore(
            root=tmp_path / "visualizers",
            state_file=tmp_path / "visualizers.json",
        )
    )
    monkeypatch.setattr(
        visualizers_router,
        "get_visualizer_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(visualizers_router.router, prefix="/api/visualizers")
    return TestClient(app)


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "visualizer.json",
            json.dumps(
                {
                    "id": "fraction_tiles",
                    "display_name": "Fraction Tiles",
                    "description": "Interactive fraction tiles.",
                    "render_target": "iframe",
                    "renderer_entry": "index.html",
                    "payload_format": "application/json",
                    "payload_kind": "json",
                    "prompt": "Return strict JSON with fraction rows.",
                }
            ),
        )
        archive.writestr("index.html", "<!doctype html><title>Fraction Tiles</title>")
    return buffer.getvalue()


def test_visualizer_catalog_install_import_and_asset_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    initial = client.get("/api/visualizers/list").json()["visualizers"]
    assert next(item for item in initial if item["id"] == "geogebra")["installed"] is False

    response = client.post("/api/visualizers/bundled/geogebra/install")
    assert response.status_code == 200
    assert response.json()["status"] == "installed"

    imported = client.post(
        "/api/visualizers/import",
        files={"file": ("fraction-tiles.zip", _archive(), "application/zip")},
    )
    assert imported.status_code == 200
    assert imported.json()["visualizer"] == "fraction_tiles"

    asset = client.get("/api/visualizers/fraction_tiles/assets/index.html")
    assert asset.status_code == 200
    assert "Fraction Tiles" in asset.text
    assert "connect-src 'none'" in asset.headers["content-security-policy"]
    assert asset.headers["cross-origin-resource-policy"] == "same-origin"

    disabled = client.post("/api/visualizers/fraction_tiles/disable")
    assert disabled.status_code == 200
    assert client.get("/api/visualizers/fraction_tiles/assets/index.html").status_code == 404

    assert client.post("/api/visualizers/fraction_tiles/enable").status_code == 200
    assert client.delete("/api/visualizers/fraction_tiles").status_code == 200
