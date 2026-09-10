from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.model_catalog import CATALOG_SECRET_MASK
from deeptutor.services.config.settings_draft import SettingsDraftService


class _FakeCatalogService:
    def __init__(self, catalog: dict[str, Any]) -> None:
        self.catalog = deepcopy(catalog)

    def load(self) -> dict[str, Any]:
        return deepcopy(self.catalog)


def _catalog(api_key: str) -> dict[str, Any]:
    return {
        "services": {
            "llm": {
                "active_profile_id": "p1",
                "profiles": [
                    {
                        "id": "p1",
                        "name": "Review profile",
                        "api_key": api_key,
                        "models": [],
                    }
                ],
            }
        }
    }


@pytest.mark.asyncio
async def test_staging_a_preset_writes_only_the_reviewable_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live = _catalog("sk-live")
    catalog_service = _FakeCatalogService(live)
    draft_path = tmp_path / "settings_draft.json"
    draft_service = SettingsDraftService(path=draft_path)
    stored = draft_service.save(
        {
            "catalog": _catalog(CATALOG_SECRET_MASK),
            "extensions": {"memory": {"enabled": False}},
        }
    )

    guarded = 0

    def guarded_admin() -> None:
        nonlocal guarded
        guarded += 1

    monkeypatch.setattr(
        settings_router,
        "get_model_catalog_service",
        lambda: catalog_service,
    )
    monkeypatch.setattr(
        settings_router,
        "get_settings_draft_service",
        lambda: draft_service,
    )
    monkeypatch.setattr(
        settings_router,
        "_require_settings_admin",
        guarded_admin,
    )

    request = settings_router.SettingsPresetDraftRequest(
        catalog=stored["catalog"],
        extensions={},
    )
    response = await settings_router.stage_settings_preset(
        "university_study",
        request,
    )

    assert guarded == 1
    assert response["preset"]["id"] == "university_study"
    draft = response["draft"]
    assert draft["extensions"]["document_parsing"] == {"engine": "markitdown"}
    assert draft["extensions"]["enabled_tools"] == {
        "enabled_tools": ["brainstorm", "web_search", "paper_search", "reason"]
    }
    assert draft["extensions"]["memory"] == {"enabled": False}
    assert draft["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == (CATALOG_SECRET_MASK)

    saved = draft_service.load()
    assert saved["extensions"]["document_parsing"] == draft["extensions"]["document_parsing"]
    assert saved["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == "sk-live"
    assert catalog_service.load() == _catalog("sk-live")


@pytest.mark.asyncio
async def test_an_unknown_preset_does_not_touch_the_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    draft_service = SettingsDraftService(path=tmp_path / "settings_draft.json")
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: None)
    monkeypatch.setattr(settings_router, "get_settings_draft_service", lambda: draft_service)
    monkeypatch.setattr(settings_router, "_require_settings_admin", lambda: None)

    with pytest.raises(HTTPException) as raised:
        await settings_router.stage_settings_preset(
            "missing",
            settings_router.SettingsPresetDraftRequest(),
        )

    assert raised.value.status_code == 404
    assert not draft_service.path.exists()
