"""Upgrade compatibility and provider-scoped saves on real catalog files."""

from copy import deepcopy

import pytest

from deeptutor.services.config.model_catalog import ModelCatalogService, redact_catalog_secrets
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
from deeptutor.services.settings.provider_edit import merge_provider_edit


def legacy(tmp_path):
    store = ModelCatalogService(tmp_path / "model_catalog.json")
    catalog = store.load()
    catalog["future_extension"] = {"keep": True}
    for service in ("llm", "task", "embedding"):
        catalog["services"][service].update(
            {
                "active_profile_id": service + "-first",
                "active_model_id": service + "-model",
                "profiles": [
                    {
                        "id": service + "-first",
                        "name": "My account",
                        "binding": "custom",
                        "api_key": "test-old-key",
                        "base_url": "https://example.invalid/v1",
                        "extra_headers": {"X-Account": "test-secret-header"},
                        "future_profile": [1, 2],
                        "models": [
                            {
                                "id": service + "-model",
                                "model": "existing-model",
                                "context_window": "65536",
                                "future_model": {"temperature": 0.3},
                            }
                        ],
                    }
                ],
            }
        )
    return store, store.save(catalog)


def test_old_catalog_round_trip_keeps_all_configuration(tmp_path):
    store, current = legacy(tmp_path)
    original = deepcopy(current)
    profile = redact_catalog_secrets(current)["services"]["llm"]["profiles"][0]
    merged = merge_provider_edit(current, "llm", profile)
    assert store.save(merged) == original
    assert store.load() == original
    assert current == original


def test_save_one_provider_keeps_siblings_other_services_and_unknown_fields(tmp_path):
    store, current = legacy(tmp_path)
    sibling = deepcopy(current["services"]["llm"]["profiles"][0])
    sibling["id"] = "second-account"
    sibling["models"][0]["id"] = "second-model"
    current["services"]["llm"]["profiles"].append(sibling)
    current = store.save(current)
    changed = redact_catalog_secrets(current)["services"]["llm"]["profiles"][1]
    changed["models"][0]["model"] = "new-model"
    result = store.save(merge_provider_edit(current, "llm", changed))
    assert result["services"]["llm"]["active_profile_id"] == "llm-first"
    assert result["services"]["llm"]["profiles"][0] == current["services"]["llm"]["profiles"][0]
    assert result["services"]["task"] == current["services"]["task"]
    assert result["services"]["embedding"] == current["services"]["embedding"]
    assert result["future_extension"] == current["future_extension"]
    assert result["services"]["llm"]["profiles"][1]["extra_headers"] == sibling["extra_headers"]


def test_saved_draft_key_wins_and_shared_key_updates_existing_connection(tmp_path):
    store, current = legacy(tmp_path)
    current["connections"] = [
        {
            "id": "account",
            "provider": "custom",
            "name": "Account",
            "api_key": "test-live",
            "base_url": "",
        }
    ]
    for service in ("llm", "embedding"):
        current["services"][service]["profiles"][0]["connection_id"] = "account"
    current = store.save(current)
    parked = deepcopy(current)
    parked["connections"][0]["api_key"] = "test-rotated"
    public = redact_catalog_secrets(parked)
    merged = merge_provider_edit(
        current,
        "llm",
        public["services"]["llm"]["profiles"][0],
        connection=public["connections"][0],
        stored_draft=parked,
    )
    result = store.save(merged)
    assert result["connections"][0]["api_key"] == "test-rotated"
    for service in ("llm", "embedding"):
        assert result["services"][service]["profiles"][0]["api_key"] == "test-rotated"
        assert (
            result["services"][service]["active_model_id"]
            == current["services"][service]["active_model_id"]
        )


def test_unrelated_connection_cannot_be_updated(tmp_path):
    _, current = legacy(tmp_path)
    with pytest.raises(ValueError, match="connection"):
        merge_provider_edit(
            current, "llm", current["services"]["llm"]["profiles"][0], connection={"id": "other"}
        )


def test_task_reference_reuses_credentials_and_keeps_legacy_models(tmp_path):
    store, current = legacy(tmp_path)
    before = deepcopy(current["services"]["task"]["profiles"])
    task = current["services"]["task"]
    task["mode"] = "reference"
    task["selection"] = {"profile_id": "llm-first", "model_id": "llm-model"}
    current["services"]["llm"]["profiles"][0]["api_key"] = "test-new-credential"
    saved = store.save(current)
    config = resolve_llm_runtime_config(saved, service=store, service_name="task")
    assert config.api_key == "test-new-credential"
    assert saved["services"]["task"]["profiles"] == before
    task["mode"] = "inherit"
    from deeptutor.services.model_selection.tasks import task_service_configured

    assert not task_service_configured(current)
    assert store.save(current)["services"]["task"]["profiles"] == before


@pytest.mark.asyncio
async def test_provider_api_preserves_other_saved_drafts_and_restores_draft_secret(
    tmp_path, monkeypatch
):
    import contextlib

    from deeptutor.api.routers import settings as router
    from deeptutor.services.config.settings_draft import SettingsDraftService

    store, current = legacy(tmp_path)
    drafts = SettingsDraftService(tmp_path / "draft.json")
    parked = deepcopy(current)
    parked["services"]["llm"]["profiles"][0]["api_key"] = "test-draft-key"
    parked["services"]["embedding"]["profiles"][0]["models"][0]["model"] = "unsaved-embedding"
    drafts.save({"catalog": parked, "extensions": {"appearance": {"preserved": True}}})
    monkeypatch.setattr(router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(router, "get_model_catalog_service", lambda: store)
    monkeypatch.setattr(router, "get_settings_draft_service", lambda: drafts)
    monkeypatch.setattr(router, "_runtime_catalog_write", contextlib.nullcontext)
    monkeypatch.setattr(
        router, "reconcile_codex_catalog_update", lambda current, proposed: proposed
    )
    profile = redact_catalog_secrets(parked)["services"]["llm"]["profiles"][0]
    profile["models"][0]["model"] = "edited-model"
    result = await router.apply_provider_edit(
        router.ProviderEditPayload(service="llm", profile=profile)
    )
    assert result["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == "***"
    assert store.load()["services"]["llm"]["profiles"][0]["api_key"] == "test-draft-key"
    assert store.load()["services"]["embedding"] == current["services"]["embedding"]
    assert (
        drafts.load()["catalog"]["services"]["embedding"]["profiles"][0]["models"][0]["model"]
        == "unsaved-embedding"
    )
    assert drafts.load()["extensions"] == {"appearance": {"preserved": True}}


@pytest.mark.asyncio
async def test_model_probe_uses_draft_key_without_saving_or_changing_default(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deeptutor.api.routers import settings as router
    from deeptutor.services.config.settings_draft import SettingsDraftService

    store, current = legacy(tmp_path)
    drafts = SettingsDraftService(tmp_path / "draft.json")
    parked = deepcopy(current)
    parked["services"]["task"]["profiles"][0]["api_key"] = "test-new-task-key"
    drafts.save({"catalog": parked})
    received = []
    monkeypatch.setattr(router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(router, "get_model_catalog_service", lambda: store)
    monkeypatch.setattr(router, "get_settings_draft_service", lambda: drafts)
    monkeypatch.setattr(
        router,
        "get_config_test_runner",
        lambda: SimpleNamespace(
            start=lambda service, catalog: (
                received.append((service, catalog)) or SimpleNamespace(id="test-run")
            )
        ),
    )
    await router.start_service_test(
        "task", router.CatalogPayload(catalog=redact_catalog_secrets(parked))
    )
    assert received[0][0] == "task"
    assert received[0][1]["services"]["task"]["profiles"][0]["api_key"] == "test-new-task-key"
    assert store.load() == current


@pytest.mark.asyncio
async def test_task_choice_rejects_missing_reference_without_writing(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from deeptutor.api.routers import settings as router
    from deeptutor.services.config.settings_draft import SettingsDraftService

    store, current = legacy(tmp_path)
    drafts = SettingsDraftService(tmp_path / "draft.json")
    monkeypatch.setattr(router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(router, "get_model_catalog_service", lambda: store)
    monkeypatch.setattr(router, "get_settings_draft_service", lambda: drafts)
    task = deepcopy(current["services"]["task"])
    task.update(mode="reference", selection={"profile_id": "not-saved", "model_id": "missing"})
    with pytest.raises(HTTPException) as error:
        await router.apply_catalog_service(
            router.CatalogServicePayload(service="task", config=task)
        )
    assert error.value.status_code == 400
    assert store.load() == current
