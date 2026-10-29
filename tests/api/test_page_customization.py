import json

from pydantic import ValidationError
import pytest

from deeptutor.api.routers import settings
from deeptutor.services.settings.page_customization import (
    ChatPageCustomization,
    LearningPageCustomization,
)


@pytest.mark.asyncio
async def test_customization_sections_preserve_other_settings_and_are_private(
    monkeypatch, tmp_path
):
    path = tmp_path / "interface.json"
    path.write_text(json.dumps({"theme": "dark", "language": "zh"}))
    monkeypatch.setattr(settings, "_settings_file", lambda: path)
    await settings.update_learning_page_customization(
        LearningPageCustomization(hidden_features=["mastery"])
    )
    response = await settings.update_chat_page_customization(
        ChatPageCustomization(
            hidden_modes=["deep_research"],
            controls={"voice": False},
            starters={
                "explain": [{"label": "My title", "prompt": "Private personal prompt"}],
                "solve": [],
            },
        )
    )
    assert response["learning"]["hidden_features"] == ["mastery"]
    assert response["chat"]["controls"]["voice"] is False
    assert response["chat"]["controls"]["skills"] is True
    assert response["chat"]["starters"]["solve"] == []
    assert json.loads(path.read_text())["theme"] == "dark"
    assert "page_customization" not in await settings.get_ui_settings()
    # Changing the account-resolved file cannot expose the previous account's prompts.
    monkeypatch.setattr(settings, "_settings_file", lambda: tmp_path / "another-user.json")
    assert (await settings.get_page_customization())["chat"]["starters"] == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"starters": {"unknown": []}},
        {"starters": {"explain": [{"label": " ", "prompt": "ok"}]}},
        {"starters": {"explain": [{"label": "ok", "prompt": "x" * 4001}]}},
        {"starters": {"explain": [{"label": "ok", "prompt": "ok"}] * 21}},
        {"controls": {"install_module": True}},
    ],
)
def test_customization_rejects_invalid_or_unbounded_input(payload):
    with pytest.raises(ValidationError):
        ChatPageCustomization.model_validate(payload)


def test_learner_can_edit_personal_pages_but_not_runtime():
    from deeptutor.api.routers.auth import _learning_surface_for_path

    for method, path in [
        ("GET", "/api/settings/page-customization"),
        ("PUT", "/api/settings/page-customization/chat"),
        ("PUT", "/api/settings/page-customization/learning"),
    ]:
        assert _learning_surface_for_path(path, method=method, route_path=path) == "chat"
    assert (
        _learning_surface_for_path(
            "/api/settings/catalog", method="PUT", route_path="/api/settings/catalog"
        )
        == ""
    )


@pytest.mark.asyncio
async def test_legacy_health_url_uses_readiness_handler():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deeptutor.api.main import app, health_ready

    routes = {
        route.path: route
        for route in app.routes
        if getattr(route, "path", "") in {"/health", "/health/ready"}
    }
    assert routes["/health"].endpoint is routes["/health/ready"].endpoint
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ready=False)))
    assert (await health_ready(request)).status_code == 503
    request.app.state.ready = True
    request.app.state.application_container = SimpleNamespace(
        coordinator=SimpleNamespace(health=AsyncMock(return_value=True))
    )
    assert await health_ready(request) == {"status": "ready"}


@pytest.mark.asyncio
async def test_reading_only_learner_can_customize_pages_without_chat_access(monkeypatch):
    from types import SimpleNamespace

    from starlette.requests import Request

    from deeptutor.api.routers.auth import require_learning_surface
    from deeptutor.multi_user import learning_access

    def deny_surface(*args, **kwargs):
        raise AssertionError("Personal page choices must not require a chat grant")

    monkeypatch.setattr(learning_access, "assert_learning_surface", deny_surface)
    for method, path in [
        ("GET", "/api/settings/page-customization"),
        ("PUT", "/api/settings/page-customization/learning"),
    ]:
        request = Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": [],
                "route": SimpleNamespace(path=path),
            }
        )
        await require_learning_surface(request, None)
