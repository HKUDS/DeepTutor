"""Resolve native LightRAG role choices inside the initiating user's scope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.model_access import allowed_llm_options, apply_allowed_llm_selection
from deeptutor.multi_user.models import CurrentUser
from deeptutor.services.config.lightrag_roles import LightRagRoleModels
from deeptutor.services.llm.capabilities import supports_vision
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.model_selection.reasoning import supported_reasoning_efforts
from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

ROLES = ("extract", "keyword", "query", "vlm")


def model_options() -> dict[str, Any]:
    """Access-filtered choices shared by the editor and runtime validator."""
    result = allowed_llm_options()
    options = []
    for row in result["options"]:
        levels = row.get("supported_reasoning_efforts")
        metadata = {"codex_supported_reasoning_levels": levels} if levels is not None else {}
        metadata["capabilities"] = {"reasoning": row.get("declared_reasoning")}
        options.append(
            {
                **row,
                "supported_reasoning_efforts": supported_reasoning_efforts(
                    row["provider"], row["model"], metadata=metadata
                ),
                "supports_vision": row.get(
                    "declared_vision", supports_vision(row["provider"], row["model"])
                ),
            }
        )
    return {**result, "options": options}


def resolve_selection(selection: LLMSelection, *, vision: bool = False) -> LLMConfig:
    apply_allowed_llm_selection(selection.to_dict())
    config = resolve_llm_config_for_selection(selection)
    if config.reasoning_effort is not None:
        option = next(
            (
                item
                for item in model_options()["options"]
                if item["profile_id"] == selection.profile_id
                and item["model_id"] == selection.model_id
            ),
            None,
        )
        if option is None or config.reasoning_effort not in option["supported_reasoning_efforts"]:
            raise ValueError("The selected model does not support this reasoning effort.")
    if vision and not supports_vision(config.binding, config.model):
        raise ValueError("The selected VLM model does not support image inputs.")
    return config


def settings_models(settings: dict[str, Any]) -> LightRagRoleModels | None:
    value = settings.get("role_models")
    return LightRagRoleModels.model_validate(value) if "role_models" in settings else None


def validate_models(models: LightRagRoleModels) -> None:
    resolve_selection(LLMSelection(**models.base.model_dump()))
    for role in ROLES:
        selection = models.selection_for(role)
        if selection is not None:
            resolve_selection(LLMSelection(**selection.model_dump()), vision=role == "vlm")


@dataclass(frozen=True)
class RoleCall:
    config: LLMConfig
    owner: CurrentUser
    max_async: int
    timeout: int


def runtime_limits(settings: dict[str, Any]) -> dict[str, dict[str, int]]:
    models = settings_models(settings)
    return {
        role: {
            "max_async": getattr(models, role).max_async
            if models
            else int(settings.get("llm_model_max_async", 4)),
            "timeout": getattr(models, role).timeout if models else 240,
        }
        for role in ROLES
    }


def resolve_query_roles() -> dict[str, RoleCall]:
    from deeptutor.services.config import load_lightrag_settings

    from .config import resolve_lightrag_query_llm_config

    settings = load_lightrag_settings()
    models = settings_models(settings)
    if models is None and settings.get("version") == 2:
        raise ValueError("Choose and save a LightRAG base model before querying.")
    limits = runtime_limits(settings)
    owner = get_current_user()
    result = {}
    # The legacy resolver is intentionally used only for old-format settings.
    legacy = resolve_lightrag_query_llm_config() if models is None else None
    for role in ("keyword", "query"):
        config = (
            legacy
            if models is None
            else resolve_selection(LLMSelection(**models.selection_for(role).model_dump()))
        )
        result[role] = RoleCall(config=config, owner=owner, **limits[role])
    return result
