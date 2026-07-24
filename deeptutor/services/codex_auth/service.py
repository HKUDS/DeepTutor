"""Codex OAuth orchestration and managed model-catalog integration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService

from .constants import CODEX_DEFAULT_MODEL
from .contracts import CatalogSnapshot, CodexModel

MANAGED_BY = "openai_codex_oauth"
CODEX_PROFILE_ID = "llm-profile-openai-codex-managed"


@dataclass(frozen=True)
class CatalogSyncResult:
    catalog: dict[str, Any]
    auto_switched: bool
    previous_selection: dict[str, str | None] | None


def codex_model_id(slug: str) -> str:
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]
    return f"llm-model-openai-codex-{digest}"


def _managed_model(model: CodexModel) -> dict[str, Any]:
    return {
        "id": codex_model_id(model.slug),
        "name": model.display_name,
        "model": model.slug,
        "managed_by": MANAGED_BY,
        "codex_priority": model.priority,
        "codex_default_reasoning_level": model.default_reasoning_level,
        "codex_supported_reasoning_levels": list(model.supported_reasoning_levels),
        "codex_supports_reasoning_summary": model.supports_reasoning_summary,
        "codex_supports_parallel_tool_calls": model.supports_parallel_tool_calls,
        "codex_use_responses_lite": model.use_responses_lite,
    }


def _managed_profile(snapshot: CatalogSnapshot) -> dict[str, Any]:
    return {
        "id": CODEX_PROFILE_ID,
        "name": "OpenAI Codex",
        "binding": "openai_codex",
        "base_url": "https://chatgpt.com/backend-api",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "managed_by": MANAGED_BY,
        "read_only": True,
        "models": [_managed_model(model) for model in snapshot.models],
    }


def sync_codex_catalog(
    catalog_service: ModelCatalogService,
    snapshot: CatalogSnapshot,
    *,
    activate_sol: bool,
    state: dict[str, Any],
) -> CatalogSyncResult:
    auto_switched = False
    selection_to_store: dict[str, str | None] | None = None
    profile = _managed_profile(snapshot)
    sol_available = any(model.slug == CODEX_DEFAULT_MODEL for model in snapshot.models)

    def mutate(catalog: dict[str, Any]) -> None:
        nonlocal auto_switched, selection_to_store
        llm = catalog["services"]["llm"]
        profiles = llm.setdefault("profiles", [])
        managed_indexes = [
            index
            for index, existing in enumerate(profiles)
            if existing.get("managed_by") == MANAGED_BY
        ]
        if managed_indexes:
            first_index = managed_indexes[0]
            profiles[:] = [
                existing
                for existing in profiles
                if existing.get("managed_by") != MANAGED_BY
            ]
            profiles.insert(min(first_index, len(profiles)), profile)
        else:
            profiles.append(profile)

        current_profile_id = llm.get("active_profile_id")
        current_model_id = llm.get("active_model_id")
        previous_selection = state.get("previous_selection")
        should_switch = (
            activate_sol
            and snapshot.source == "live"
            and sol_available
            and current_profile_id != CODEX_PROFILE_ID
            and not isinstance(previous_selection, dict)
        )
        if should_switch:
            selection_to_store = {
                "profile_id": current_profile_id,
                "model_id": current_model_id,
            }
            llm["active_profile_id"] = CODEX_PROFILE_ID
            llm["active_model_id"] = codex_model_id(CODEX_DEFAULT_MODEL)
            auto_switched = True
        elif current_profile_id == CODEX_PROFILE_ID:
            valid_model_ids = {model["id"] for model in profile["models"]}
            if current_model_id not in valid_model_ids:
                llm["active_model_id"] = (
                    profile["models"][0]["id"] if profile["models"] else None
                )

    catalog = catalog_service.update(mutate)
    if selection_to_store is not None:
        state["previous_selection"] = selection_to_store
    previous = state.get("previous_selection")
    return CatalogSyncResult(
        catalog=catalog,
        auto_switched=auto_switched,
        previous_selection=dict(previous) if isinstance(previous, dict) else None,
    )


def remove_codex_catalog(
    catalog_service: ModelCatalogService,
    state: dict[str, Any],
) -> dict[str, Any]:
    previous = state.get("previous_selection")

    def mutate(catalog: dict[str, Any]) -> None:
        llm = catalog["services"]["llm"]
        current_is_managed = llm.get("active_profile_id") == CODEX_PROFILE_ID
        llm["profiles"] = [
            profile
            for profile in llm.get("profiles", [])
            if profile.get("managed_by") != MANAGED_BY
        ]
        if current_is_managed and isinstance(previous, dict):
            profile_id = previous.get("profile_id")
            model_id = previous.get("model_id")
            backup_profile = next(
                (
                    profile
                    for profile in llm["profiles"]
                    if profile.get("id") == profile_id
                ),
                None,
            )
            backup_model_ids = {
                model.get("id") for model in (backup_profile or {}).get("models", [])
            }
            if backup_profile is not None and model_id in backup_model_ids:
                llm["active_profile_id"] = profile_id
                llm["active_model_id"] = model_id

    catalog = catalog_service.update(mutate)
    state.pop("previous_selection", None)
    return catalog


__all__ = [
    "CODEX_PROFILE_ID",
    "MANAGED_BY",
    "CatalogSyncResult",
    "codex_model_id",
    "remove_codex_catalog",
    "sync_codex_catalog",
]
