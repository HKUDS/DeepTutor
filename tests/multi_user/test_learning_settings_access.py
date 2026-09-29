"""Learning accounts may select granted models and save presentation preferences."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def learning_settings_client(mu_isolated_root, seed_user, as_user, monkeypatch):
    from deeptutor.api.routers import auth, settings
    from deeptutor.multi_user.grants import save_grant

    seed_user("admin", role="admin")
    learner = seed_user("student")
    save_grant(
        learner["id"],
        {
            "learning_policy": {
                "age_band": "13-15",
                "locked_persona": "teacher",
                "allowed_capabilities": ["chat", "immersive_reading"],
                "default_capability": "chat",
                "allowed_surfaces": ["chat", "reading"],
            }
        },
    )
    preferences = {"theme": "snow", "language": "en"}
    monkeypatch.setattr(settings, "load_ui_settings", lambda: dict(preferences))
    monkeypatch.setattr(settings, "patch_ui_settings", lambda **patch: preferences.update(patch))
    monkeypatch.setattr(
        settings,
        "allowed_llm_options",
        lambda: {"active": None, "options": []},
    )
    app = FastAPI()
    app.dependency_overrides[auth.require_auth] = lambda: None
    app.include_router(
        settings.router,
        prefix="/api/settings",
        dependencies=[Depends(auth.require_learning_surface)],
    )
    with as_user(learner["id"], username="student"):
        yield TestClient(app), preferences


def test_learner_can_read_model_choices(learning_settings_client):
    client, _ = learning_settings_client
    response = client.get("/api/settings/llm-options")
    assert response.status_code == 200
    assert response.json() == {"active": None, "options": []}


def test_learner_can_save_appearance_without_opening_settings_router(learning_settings_client):
    client, preferences = learning_settings_client
    response = client.put(
        "/api/settings/ui", json={"theme": "dark", "code_block_show_line_numbers": False}
    )
    assert response.status_code == 200
    assert preferences["theme"] == "dark"
    assert preferences["code_block_show_line_numbers"] is False
    assert client.get("/api/settings").status_code == 403
    assert client.put("/api/settings/catalog", json={"catalog": {}}).status_code == 403
    assert (
        client.put("/api/settings/voice-autoplay", json={"voice_autoplay": True}).status_code == 403
    )
