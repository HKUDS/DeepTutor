"""Provider/model separation keeps existing catalog identities and runtime behavior."""

from contextlib import nullcontext
from copy import deepcopy

import pytest

from deeptutor.services.config.model_catalog import ModelCatalogService, redact_catalog_secrets
from deeptutor.services.config.provider_links import resolve_profile_provider
from deeptutor.services.config.provider_runtime import (
    resolve_embedding_runtime_config,
    resolve_llm_runtime_config,
    resolve_search_runtime_config,
)
from deeptutor.services.model_selection.llm import list_llm_options
from deeptutor.services.settings.registry_edit import merge_registry_edit


def fixture(tmp_path):
    store = ModelCatalogService(tmp_path / "catalog.json")
    catalog = store.load()
    for service in ("llm", "task", "embedding", "search", "tts", "stt", "imagegen", "videogen"):
        catalog["services"][service] = {
            "active_profile_id": service,
            "active_model_id": service + "-one",
            "profiles": [
                {
                    "id": service,
                    "name": "Old account",
                    "binding": "custom",
                    "provider": "tavily",
                    "base_url": "https://legacy.test/v1/embeddings"
                    if service == "embedding"
                    else "https://legacy.test/v1",
                    "api_key": "old-secret",
                    "extra_headers": {"X-Saved": "header-secret"},
                    "unknown_profile_setting": {"stay": True},
                    "models": []
                    if service == "search"
                    else [
                        {
                            "id": service + "-" + suffix,
                            "name": suffix,
                            "model": "existing-" + suffix,
                            "context_window": "64000",
                            "dimension": "768",
                            "voice": "saved-voice",
                            "duration": "7",
                            "unknown_model_setting": [1, 2],
                        }
                        for suffix in ("one", "two")
                    ],
                }
            ],
        }
    catalog["unknown_catalog_setting"] = {"keep": True}
    return store, store.save(catalog)


def provider_edit(**fields):
    return {
        "kind": "provider",
        "ref": {"connection_id": "account"},
        "fields": {
            "provider": "custom",
            "name": "New account",
            "base_url": "https://new.test/v1",
            "api_key": "new-secret",
            **fields,
        },
    }


def add_model(catalog, service="llm", ref=None):
    model = {
        "id": "new-model",
        "model": "new-model-id",
        "name": "My model",
        "provider_ref": ref or {"connection_id": "account", "binding": "custom"},
    }
    return merge_registry_edit(
        catalog, {"kind": "model", "service": service, "profile_id": "new-profile", "model": model}
    )


def test_legacy_roundtrip_and_provider_only_edit_keeps_all_models_defaults_and_secrets(tmp_path):
    store, catalog = fixture(tmp_path)
    before = deepcopy(catalog)
    patch = {
        "kind": "provider",
        "ref": {"service": "llm", "profile_id": "llm"},
        "fields": {"name": "Renamed account", "api_key": "***", "models": []},
    }
    after = store.save(merge_registry_edit(catalog, patch))
    before["services"]["llm"]["profiles"][0]["name"] = "Renamed account"
    assert after == before
    assert store.load() == before


def test_new_model_reuses_connection_and_later_key_changes_without_copying_secrets(tmp_path):
    store, current = fixture(tmp_path)
    catalog = add_model(merge_registry_edit(current, provider_edit()))
    catalog = merge_registry_edit(
        catalog,
        {"kind": "default", "service": "llm", "profile_id": "new-profile", "model_id": "new-model"},
    )
    catalog = store.save(catalog)
    assert catalog["services"]["llm"]["profiles"][-1]["api_key"] == ""
    assert resolve_llm_runtime_config(catalog, service=store).api_key == "new-secret"
    catalog = store.save(
        merge_registry_edit(catalog, provider_edit(api_key="rotated-key", api_format="anthropic"))
    )
    resolved = resolve_llm_runtime_config(catalog, service=store)
    assert resolved.api_key == "rotated-key"
    assert resolved.api_format == "anthropic"
    assert catalog["services"]["llm"]["profiles"][0] == current["services"]["llm"]["profiles"][0]
    options = list_llm_options(catalog)["options"]
    assert [(o["profile_id"], o["model_id"]) for o in options[:2]] == [
        ("llm", "llm-one"),
        ("llm", "llm-two"),
    ]
    assert options[-1]["model_name"] == "My model"
    assert options[-1]["profile_name"] == "New account"


def test_switch_one_legacy_model_provider_without_touching_sibling_or_unknown_fields(tmp_path):
    store, current = fixture(tmp_path)
    catalog = merge_registry_edit(current, provider_edit())
    original_profile = deepcopy(catalog["services"]["llm"]["profiles"][0])
    model = deepcopy(original_profile["models"][0])
    model["provider_ref"] = {"connection_id": "account", "binding": "custom"}
    catalog = store.save(
        merge_registry_edit(
            catalog, {"kind": "model", "service": "llm", "profile_id": "llm", "model": model}
        )
    )
    assert resolve_llm_runtime_config(catalog, service=store).api_key == "new-secret"
    assert (
        resolve_llm_runtime_config(
            catalog, service=store, llm_selection={"profile_id": "llm", "model_id": "llm-two"}
        ).api_key
        == "old-secret"
    )
    assert catalog["services"]["llm"]["profiles"][0]["models"][1] == original_profile["models"][1]
    assert (
        catalog["services"]["llm"]["profiles"][0]["extra_headers"]
        == original_profile["extra_headers"]
    )
    assert (
        store.get_active_model(catalog, "llm")
        is catalog["services"]["llm"]["profiles"][0]["models"][0]
    )


def test_missing_source_rejected_and_referenced_source_cannot_be_removed(tmp_path):
    _, catalog = fixture(tmp_path)
    with pytest.raises(ValueError, match="no longer configured"):
        add_model(catalog)
    catalog = add_model(merge_registry_edit(catalog, provider_edit()))
    with pytest.raises(ValueError, match="used by models"):
        merge_registry_edit(
            catalog, {"kind": "provider", "ref": {"connection_id": "account"}, "delete": True}
        )
    with pytest.raises(ValueError, match="used by models"):
        merge_registry_edit(
            catalog,
            {"kind": "provider", "ref": {"service": "llm", "profile_id": "llm"}, "delete": True},
        )


def test_model_save_does_not_promote_parked_credentials_or_sibling_drafts(tmp_path):
    _, current = fixture(tmp_path)
    parked = deepcopy(current)
    parked["services"]["llm"]["profiles"][0]["api_key"] = "unsaved-provider-key"
    parked["services"]["llm"]["profiles"][0]["models"][1]["model"] = "unsaved-sibling"
    model = deepcopy(current["services"]["llm"]["profiles"][0]["models"][0])
    model["name"] = "Renamed model"
    live = merge_registry_edit(
        current,
        {"kind": "model", "service": "llm", "profile_id": "llm", "model": model},
        stored_draft=parked,
    )
    assert live["services"]["llm"]["profiles"][0]["api_key"] == "old-secret"
    assert (
        live["services"]["llm"]["profiles"][0]["models"][1]
        == current["services"]["llm"]["profiles"][0]["models"][1]
    )


@pytest.mark.asyncio
async def test_registry_api_preserves_sibling_drafts_extensions_and_secret_masks(
    tmp_path, monkeypatch
):
    from deeptutor.api.routers import settings as router
    from deeptutor.services.config.settings_draft import SettingsDraftService

    store, current = fixture(tmp_path)
    drafts = SettingsDraftService(tmp_path / "draft.json")
    parked = deepcopy(current)
    parked["services"]["llm"]["profiles"][0]["models"][1]["model"] = "unsaved-sibling"
    parked["services"]["llm"]["profiles"][0]["api_key"] = "unsaved-key"
    drafts.save({"catalog": parked, "extensions": {"appearance": {"keep": True}}})
    monkeypatch.setattr(router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(router, "get_model_catalog_service", lambda: store)
    monkeypatch.setattr(router, "get_settings_draft_service", lambda: drafts)
    monkeypatch.setattr(router, "_runtime_catalog_write", nullcontext)
    model = deepcopy(current["services"]["llm"]["profiles"][0]["models"][0])
    model["name"] = "Saved name"
    response = await router.apply_registry_edit(
        router.RegistryEditPayload(kind="model", service="llm", profile_id="llm", model=model)
    )
    assert response["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == "***"
    assert store.load()["services"]["llm"]["profiles"][0]["api_key"] == "old-secret"
    assert (
        drafts.load()["catalog"]["services"]["llm"]["profiles"][0]["models"][1]["model"]
        == "unsaved-sibling"
    )
    assert drafts.load()["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == "unsaved-key"
    assert drafts.load()["extensions"] == {"appearance": {"keep": True}}


def test_search_reference_preserves_source_and_uses_saved_credentials(tmp_path):
    store, catalog = fixture(tmp_path)
    result = merge_registry_edit(
        catalog,
        {
            "kind": "model",
            "service": "search",
            "profile_id": "new-search",
            "config": {
                "provider_ref": {"service": "search", "profile_id": "search", "binding": "tavily"},
                "display_name": "My search",
                "max_results": 3,
            },
        },
    )
    result = merge_registry_edit(
        result, {"kind": "default", "service": "search", "profile_id": "new-search"}
    )
    result = store.save(result)
    config = resolve_search_runtime_config(result, service=store)
    assert config.provider == "tavily"
    assert config.api_key == "old-secret"
    assert config.max_results == 3
    result = merge_registry_edit(
        result, {"kind": "model", "service": "search", "profile_id": "search", "delete": True}
    )
    assert result["services"]["search"]["profiles"][0]["provider_only"] is True
    assert resolve_search_runtime_config(result, service=store).api_key == "old-secret"


@pytest.mark.parametrize(
    "binding,base,expected",
    [
        ("custom", "https://example.test/v1", "https://example.test/v1/embeddings"),
        ("ollama", "http://localhost:11434/v1", "http://localhost:11434/api/embed"),
        ("cohere", "https://api.cohere.com/v2", "https://api.cohere.com/v2/embed"),
    ],
)
def test_new_embedding_reference_resolves_service_endpoint(tmp_path, binding, base, expected):
    store, catalog = fixture(tmp_path)
    catalog = merge_registry_edit(catalog, provider_edit(provider=binding, base_url=base))
    catalog = add_model(catalog, "embedding", {"connection_id": "account", "binding": binding})
    catalog = merge_registry_edit(
        catalog,
        {
            "kind": "default",
            "service": "embedding",
            "profile_id": "new-profile",
            "model_id": "new-model",
        },
    )
    assert resolve_embedding_runtime_config(catalog, service=store).base_url == expected


def test_empty_selected_key_never_borrows_another_account_key(tmp_path):
    store, catalog = fixture(tmp_path)
    catalog = add_model(merge_registry_edit(catalog, provider_edit(api_key="")))
    catalog = merge_registry_edit(
        catalog,
        {"kind": "default", "service": "llm", "profile_id": "new-profile", "model_id": "new-model"},
    )
    assert resolve_llm_runtime_config(catalog, service=store).api_key == ""


def test_owner_bound_accounts_cannot_be_copied_into_unmanaged_models(tmp_path):
    _, catalog = fixture(tmp_path)
    catalog["services"]["llm"]["profiles"][0]["owner_bound"] = True
    with pytest.raises(ValueError, match="sign-in"):
        add_model(catalog, ref={"service": "llm", "profile_id": "llm", "binding": "openai_codex"})


def test_task_choice_saves_only_assignment_and_preserves_models(tmp_path):
    _, catalog = fixture(tmp_path)
    before = deepcopy(catalog["services"]["task"]["profiles"])
    result = merge_registry_edit(
        catalog,
        {
            "kind": "task_choice",
            "task": {
                "mode": "reference",
                "selection": {"profile_id": "llm", "model_id": "llm-two"},
            },
        },
    )
    assert result["services"]["task"]["profiles"] == before
    assert result["services"]["task"]["selection"] == {"profile_id": "llm", "model_id": "llm-two"}
    with pytest.raises(ValueError):
        merge_registry_edit(
            catalog,
            {
                "kind": "task_choice",
                "task": {
                    "mode": "reference",
                    "selection": {"profile_id": "missing", "model_id": "missing"},
                },
            },
        )


def test_one_task_can_be_pinned_without_moving_the_global_choice(tmp_path):
    _, catalog = fixture(tmp_path)
    result = merge_registry_edit(
        catalog,
        {
            "kind": "task_choice",
            "task": {
                "task_kind": "session_title",
                "mode": "profiles",
                "active_profile_id": "task",
                "active_model_id": "task-two",
            },
        },
    )
    bucket = result["services"]["task"]
    assert bucket["overrides"] == {
        "session_title": {
            "mode": "profiles",
            "active_profile_id": "task",
            "active_model_id": "task-two",
        }
    }
    # The global choice is untouched — pinning one task is not choosing for all.
    assert bucket["active_model_id"] == "task-one"

    # Back to following the global model: the row disappears rather than becoming
    # a fourth stored mode.
    cleared = merge_registry_edit(
        result, {"kind": "task_choice", "task": {"task_kind": "session_title", "mode": "global"}}
    )
    assert "overrides" not in cleared["services"]["task"]

    with pytest.raises(ValueError, match="Unknown background task"):
        merge_registry_edit(
            catalog,
            {"kind": "task_choice", "task": {"task_kind": "not_a_task", "mode": "inherit"}},
        )
    with pytest.raises(ValueError):
        merge_registry_edit(
            catalog,
            {
                "kind": "task_choice",
                "task": {
                    "task_kind": "session_title",
                    "mode": "profiles",
                    "active_profile_id": "task",
                    "active_model_id": "missing",
                },
            },
        )


def test_capability_detection_uses_metadata_not_names():
    from deeptutor.services.settings.provider_probe import detect_capabilities

    assert detect_capabilities([{"id": "gpt-embedding-search-video"}]) == []
    assert detect_capabilities(
        [
            {
                "id": "image",
                "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
            }
        ]
    ) == [{"category": "generation", "evidence": "metadata"}]
    assert detect_capabilities(
        [
            {"supportedGenerationMethods": ["embedContent"]},
            {"architecture": {"input_modalities": ["image"], "output_modalities": ["text"]}},
        ]
    ) == [
        {"category": "embedding", "evidence": "metadata"},
        {"category": "llm", "evidence": "metadata"},
    ]
    assert detect_capabilities([{"architecture": "invalid", "output_modalities": None}]) == []


def test_search_probe_uses_draft_credentials_and_cannot_fall_back(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun
    from deeptutor.services.search import providers
    from deeptutor.services.search.types import WebSearchResponse

    _, catalog = fixture(tmp_path)
    catalog["services"]["search"]["profiles"][0]["api_key"] = "draft-key"
    received = []

    def get(name, **kwargs):
        received.append((name, kwargs))
        return SimpleNamespace(
            search=lambda *a, **k: WebSearchResponse(query="test", answer="found", provider=name)
        )

    monkeypatch.setattr(providers, "get_provider", get)
    ConfigTestRunner()._test_search(TestRun(id="search-test", service="search"), catalog)
    assert received[0][0] == "tavily"
    assert received[0][1]["api_key"] == "draft-key"
    catalog["services"]["search"]["profiles"][0]["api_key"] = ""
    with pytest.raises(ValueError, match="api_key"):
        ConfigTestRunner()._test_search(TestRun(id="search-test", service="search"), catalog)
    assert len(received) == 1


def test_clear_legacy_context_alias_and_preserve_key_pool_on_rename(tmp_path):
    store, catalog = fixture(tmp_path)
    profile = catalog["services"]["llm"]["profiles"][0]
    profile["api_key"] = ["key-one", "key-two"]
    profile["models"][0].pop("context_window")
    profile["models"][0]["context_window_tokens"] = 32000
    edit = {
        "kind": "provider",
        "ref": {"service": "llm", "profile_id": "llm"},
        "fields": {"name": "Account with key pool", "api_key": ["***", "***"]},
    }
    renamed = merge_registry_edit(catalog, edit)
    assert renamed["services"]["llm"]["profiles"][0]["api_key"] == ["key-one", "key-two"]
    model = deepcopy(profile["models"][0])
    model.pop("context_window_tokens")
    model.update(context_window="", context_window_source="default")
    result = merge_registry_edit(
        catalog, {"kind": "model", "service": "llm", "profile_id": "llm", "model": model}
    )
    assert resolve_llm_runtime_config(result, service=store).context_window is None


def test_managed_account_and_model_names_survive_catalog_refresh(tmp_path):
    from deeptutor.services.codex_auth.contracts import CatalogSnapshot, CodexModel
    from deeptutor.services.codex_auth.service import (
        CODEX_PROFILE_ID,
        reconcile_codex_catalog_update,
        sync_codex_catalog,
    )

    store, catalog = fixture(tmp_path)
    model = CodexModel(
        slug="test-model",
        display_name="Provider name",
        priority=1,
        visibility="list",
        default_reasoning_level="medium",
        supported_reasoning_levels=("medium", "high"),
        supports_reasoning_summary=True,
        supports_parallel_tool_calls=True,
        use_responses_lite=False,
        context_window=128000,
    )
    snapshot = CatalogSnapshot(
        models=(model,),
        source="live",
        fetched_at=1000,
        etag=None,
        generation=1,
        account_hash="account",
    )
    sync_codex_catalog(store, snapshot, account_id="account")
    current = store.load()
    proposed = deepcopy(current)
    profile = next(
        p for p in proposed["services"]["llm"]["profiles"] if p["id"] == CODEX_PROFILE_ID
    )
    profile["user_name"] = "My signed-in account"
    profile["models"][0]["user_name"] = "My model label"
    profile["models"][0]["context_window"] = "999999"
    saved = store.save(reconcile_codex_catalog_update(current, proposed))
    managed = next(p for p in saved["services"]["llm"]["profiles"] if p["id"] == CODEX_PROFILE_ID)
    assert managed["name"] == "My signed-in account"
    assert managed["models"][0]["name"] == "My model label"
    assert managed["models"][0]["context_window"] == "128000"
    sync_codex_catalog(store, snapshot, account_id="account")
    managed = next(
        p for p in store.load()["services"]["llm"]["profiles"] if p["id"] == CODEX_PROFILE_ID
    )
    assert managed["name"] == "My signed-in account"
    assert managed["models"][0]["name"] == "My model label"
