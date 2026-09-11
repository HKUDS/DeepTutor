"""HTTP enforcement of learning-policy Reading boundaries."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading, reading_extensions
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionRegistry,
    ReadingExtensionResult,
)


def _extension(extension_id: str):
    return SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id=extension_id,
            version="1.0.0",
            name=extension_id.title(),
            actions=[ReadingAction(id="open", label="Open")],
            result_types=["card"],
        ),
        run_action=lambda _action, _context: ReadingExtensionResult(type="card"),
    )


@pytest.fixture
def learner_client(mu_isolated_root, seed_user, make_user, monkeypatch, tmp_path):
    learner = _seed_learner(seed_user)
    current_user = make_user(learner["id"], username="student")

    async def install_user():
        token = set_current_user(current_user)
        try:
            yield current_user
        finally:
            reset_current_user(token)

    registry = ReadingExtensionRegistry([_extension("read_aloud"), _extension("quiz")])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )

    app = FastAPI()
    dependencies = [Depends(install_user)]
    app.include_router(
        reading.router,
        prefix="/api/reading",
        dependencies=dependencies,
    )
    app.include_router(
        reading_extensions.router,
        prefix="/api/reading",
        dependencies=dependencies,
    )
    return TestClient(app), learner, current_user, tmp_path


def _seed_material(root: Path, name: str, text: str):
    source = root / name
    source.write_text(text, encoding="utf-8")
    return ReadingStore().ingest(source)


def _save_learner_grant(user_id: str, material_id: str):
    from deeptutor.multi_user.grants import save_grant

    save_grant(
        user_id,
        {
            "enabled_tools": [],
            "mcp_tools": [],
            "cli_apps": [],
            "exec_enabled": False,
            "learning_policy": {
                "age_band": "9-12",
                "locked_persona": "teacher",
                "allowed_capabilities": ["chat", "immersive_reading"],
                "default_capability": "immersive_reading",
                "allowed_surfaces": ["chat", "reading"],
                "reading": {
                    "allow_upload": False,
                    "material_ids": [material_id],
                    "extensions": ["read_aloud"],
                },
            },
        },
    )


def _seed_learner(seed_user):
    seed_user("admin", role="admin")
    return seed_user("student")


def test_reading_upload_material_and_listing_follow_the_policy(learner_client, as_user):
    client, learner, current_user, tmp_path = learner_client
    with as_user(current_user.id, username="student"):
        from deeptutor.reading.catalog_store import ReadingCatalogStore

        allowed = _seed_material(tmp_path, "allowed.txt", "Allowed passage.")
        private = _seed_material(tmp_path, "private.txt", "Private passage.")
        catalog = ReadingCatalogStore()
        catalog.register_manifest(allowed)
        catalog.register_manifest(private)
        workspace = catalog.create_workspace(
            "Mixed collection",
            [allowed.material_id, private.material_id],
        )
        _save_learner_grant(learner["id"], allowed.material_id)

    denied_upload = client.post(
        "/api/reading/materials",
        files={"file": ("new.txt", b"new material", "text/plain")},
    )
    assert denied_upload.status_code == 403
    assert "cannot upload" in denied_upload.json()["detail"]

    rows = client.get("/api/reading/materials").json()
    assert [row["material_id"] for row in rows] == [allowed.material_id]
    assert client.get(f"/api/reading/materials/{allowed.material_id}").status_code == 200
    denied_material = client.get(f"/api/reading/materials/{private.material_id}")
    assert denied_material.status_code == 403
    assert "not assigned" in denied_material.json()["detail"]

    library = client.get("/api/reading/library/materials").json()
    assert [row["material_id"] for row in library["materials"]] == [allowed.material_id]
    assert library["counts"]["all"] == 1

    duplicate = client.post(
        "/api/reading/library/duplicate-check",
        json={"files": [{"filename": "private.txt"}]},
    ).json()
    assert duplicate["matches"] == []

    visible_workspace = client.get(f"/api/reading/workspaces/{workspace.workspace_id}").json()[
        "workspace"
    ]
    assert [tab["material"]["material_id"] for tab in visible_workspace["tabs"]] == [
        allowed.material_id
    ]

    denied_delete = client.delete(f"/api/reading/materials/{allowed.material_id}")
    assert denied_delete.status_code == 403
    assert "cannot modify" in denied_delete.json()["detail"]
    assert client.get(f"/api/reading/materials/{allowed.material_id}").status_code == 200


def test_reading_extensions_and_actions_follow_the_policy(learner_client, as_user):
    client, learner, current_user, tmp_path = learner_client
    with as_user(current_user.id, username="student"):
        material = _seed_material(tmp_path, "allowed.txt", "Allowed passage.")
        _save_learner_grant(learner["id"], material.material_id)

    rows = client.get("/api/reading/extensions").json()
    assert [row["id"] for row in rows] == ["read_aloud"]

    allowed = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/read_aloud/actions/open",
        json={"locator": 1},
    )
    assert allowed.status_code == 200, allowed.text

    denied = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/quiz/actions/open",
        json={"locator": 1},
    )
    assert denied.status_code == 403
    assert "not allowed" in denied.json()["detail"]
