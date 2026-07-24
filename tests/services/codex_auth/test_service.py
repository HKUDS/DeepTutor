from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from deeptutor.services.codex_auth.contracts import CatalogSnapshot, CodexModel
from deeptutor.services.codex_auth.service import (
    CODEX_PROFILE_ID,
    MANAGED_BY,
    codex_model_id,
    remove_codex_catalog,
    sync_codex_catalog,
)
from deeptutor.services.config.model_catalog import ModelCatalogService


def _model(
    slug: str,
    *,
    display_name: str | None = None,
    priority: int = 1,
) -> CodexModel:
    return CodexModel(
        slug=slug,
        display_name=display_name or slug,
        priority=priority,
        visibility="list",
        default_reasoning_level="medium",
        supported_reasoning_levels=("medium", "high"),
        supports_reasoning_summary=True,
        supports_parallel_tool_calls=True,
        use_responses_lite=False,
    )


def _snapshot(
    source: str,
    *models: CodexModel,
) -> CatalogSnapshot:
    return CatalogSnapshot(
        models=models,
        source=source,  # type: ignore[arg-type]
        fetched_at=1_000,
        etag='"v1"',
        generation=1,
        account_hash="account-hash",
    )


def _seeded_service(tmp_path: Path) -> tuple[ModelCatalogService, dict]:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    original = service.load()
    llm = original["services"]["llm"]
    llm["profiles"] = [
        {
            "id": "llm-profile-existing",
            "name": "Existing",
            "binding": "siliconflow",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "existing-key",
            "models": [
                {
                    "id": "llm-model-existing",
                    "name": "DeepSeek V3",
                    "model": "deepseek-ai/DeepSeek-V3",
                },
                {
                    "id": "llm-model-backup",
                    "name": "Backup",
                    "model": "backup-model",
                },
            ],
        }
    ]
    llm["active_profile_id"] = "llm-profile-existing"
    llm["active_model_id"] = "llm-model-existing"
    saved = service.save(original)
    return service, saved


def _selection(catalog: dict) -> dict[str, str | None]:
    llm = catalog["services"]["llm"]
    return {
        "profile_id": llm.get("active_profile_id"),
        "model_id": llm.get("active_model_id"),
    }


def _managed_profile(catalog: dict) -> dict:
    return next(
        profile
        for profile in catalog["services"]["llm"]["profiles"]
        if profile.get("managed_by") == MANAGED_BY
    )


def test_sync_creates_read_only_managed_codex_profile_and_switches_exact_sol(
    tmp_path: Path,
) -> None:
    service, original = _seeded_service(tmp_path)
    state: dict = {}

    result = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol"), _model("gpt-5.6-terra", priority=2)),
        activate_sol=True,
        state=state,
    )

    profile = _managed_profile(result.catalog)
    assert profile["id"] == CODEX_PROFILE_ID
    assert profile["binding"] == "openai_codex"
    assert profile["api_key"] == ""
    assert profile["read_only"] is True
    assert [model["model"] for model in profile["models"]] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    ]
    assert result.auto_switched is True
    assert result.previous_selection == _selection(original)
    assert state["previous_selection"] == _selection(original)
    assert _selection(result.catalog) == {
        "profile_id": CODEX_PROFILE_ID,
        "model_id": codex_model_id("gpt-5.6-sol"),
    }


def test_stale_missing_alias_or_wrong_case_never_changes_active_selection(
    tmp_path: Path,
) -> None:
    cases = (
        _snapshot("stale-cache", _model("gpt-5.6-sol")),
        _snapshot("live", _model("gpt-5.6-terra", display_name="GPT-5.6-Sol")),
        _snapshot("live", _model("GPT-5.6-SOL")),
    )

    for index, snapshot in enumerate(cases):
        case_root = tmp_path / str(index)
        service, original = _seeded_service(case_root)
        result = sync_codex_catalog(service, snapshot, activate_sol=True, state={})
        assert result.auto_switched is False
        assert _selection(result.catalog) == _selection(original)


def test_refresh_replaces_only_managed_models_and_preserves_backup(tmp_path: Path) -> None:
    service, original = _seeded_service(tmp_path)
    state: dict = {}
    first = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol"), _model("old-model")),
        activate_sol=True,
        state=state,
    )
    existing_profile = deepcopy(
        next(
            profile
            for profile in first.catalog["services"]["llm"]["profiles"]
            if profile["id"] == "llm-profile-existing"
        )
    )

    refreshed = sync_codex_catalog(
        service,
        _snapshot("live", _model("new-model")),
        activate_sol=False,
        state=state,
    )

    assert [model["model"] for model in _managed_profile(refreshed.catalog)["models"]] == [
        "new-model"
    ]
    assert next(
        profile
        for profile in refreshed.catalog["services"]["llm"]["profiles"]
        if profile["id"] == "llm-profile-existing"
    ) == existing_profile
    assert state["previous_selection"] == _selection(original)


def test_logout_restores_backup_only_while_managed_codex_is_active(tmp_path: Path) -> None:
    service, original = _seeded_service(tmp_path)
    state: dict = {}
    sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol")),
        activate_sol=True,
        state=state,
    )

    removed = remove_codex_catalog(service, state)

    assert _selection(removed) == _selection(original)
    assert not any(
        profile.get("managed_by") == MANAGED_BY
        for profile in removed["services"]["llm"]["profiles"]
    )
    assert "previous_selection" not in state


def test_logout_does_not_override_later_user_selection(tmp_path: Path) -> None:
    service, _original = _seeded_service(tmp_path)
    state: dict = {}
    sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol")),
        activate_sol=True,
        state=state,
    )

    def select_backup(catalog: dict) -> None:
        llm = catalog["services"]["llm"]
        llm["active_profile_id"] = "llm-profile-existing"
        llm["active_model_id"] = "llm-model-backup"

    service.update(select_backup)
    removed = remove_codex_catalog(service, state)

    assert _selection(removed) == {
        "profile_id": "llm-profile-existing",
        "model_id": "llm-model-backup",
    }


def test_missing_backup_does_not_replace_current_user_selection(tmp_path: Path) -> None:
    service, _original = _seeded_service(tmp_path)
    state = {
        "previous_selection": {
            "profile_id": "deleted-profile",
            "model_id": "deleted-model",
        }
    }

    removed = remove_codex_catalog(service, state)

    assert _selection(removed) == {
        "profile_id": "llm-profile-existing",
        "model_id": "llm-model-existing",
    }


def test_catalog_sync_does_not_touch_neighboring_history_file(tmp_path: Path) -> None:
    history = tmp_path / "chat-history.json"
    history.write_text('{"model":"old"}', encoding="utf-8")
    service, _original = _seeded_service(tmp_path)

    sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol")),
        activate_sol=True,
        state={},
    )

    assert history.read_text(encoding="utf-8") == '{"model":"old"}'
