"""Server-side model grant resolution and redacted model views."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.model_selection import list_llm_options

from .context import get_current_user
from .grants import load_grant
from .paths import get_admin_path_service

SERVICES = ("llm", "embedding", "search")


def admin_catalog_service() -> ModelCatalogService:
    return ModelCatalogService(path=get_admin_path_service().get_settings_file("model_catalog"))


def admin_catalog() -> dict[str, Any]:
    return admin_catalog_service().load()


def _profile_by_id(catalog: dict[str, Any], service: str, profile_id: str) -> dict[str, Any] | None:
    for profile in catalog.get("services", {}).get(service, {}).get("profiles", []) or []:
        if str(profile.get("id") or "") == profile_id:
            return profile
    return None


def _model_by_id(profile: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    for model in profile.get("models", []) or []:
        if str(model.get("id") or "") == model_id:
            return model
    return None


def redacted_model_access(user_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    user = get_current_user()
    if user_id is None:
        user_id = user.id
    grant = load_grant(user_id)
    catalog = admin_catalog()
    result: dict[str, list[dict[str, Any]]] = {"llm": [], "embedding": [], "search": []}
    for service in SERVICES:
        for item in grant.get("models", {}).get(service, []) or []:
            profile_id = str(item.get("profile_id") or item.get("id") or "")
            profile = _profile_by_id(catalog, service, profile_id)
            if not profile:
                result[service].append(
                    {
                        "profile_id": profile_id,
                        "name": item.get("name") or profile_id or "Unavailable profile",
                        "source": "admin",
                        "available": False,
                    }
                )
                continue
            model_ids = item.get("model_ids") or []
            if service == "search":
                result[service].append(
                    {
                        "profile_id": profile_id,
                        "name": profile.get("name") or profile.get("provider") or profile_id,
                        "provider": profile.get("provider", ""),
                        "source": "admin",
                        "available": True,
                    }
                )
                continue
            for model_id in model_ids:
                model = _model_by_id(profile, str(model_id))
                result[service].append(
                    {
                        "profile_id": profile_id,
                        "model_id": str(model_id),
                        "name": (model or {}).get("name") or str(model_id),
                        "model": (model or {}).get("model") or "",
                        "source": "admin",
                        "available": model is not None,
                    }
                )
    return result


def allowed_llm_options() -> list[dict[str, Any]]:
    user = get_current_user()
    if user.is_admin:
        return list_llm_options(admin_catalog())
    return [
        {
            "profile_id": item.get("profile_id"),
            "model_id": item.get("model_id"),
            "label": item.get("name") or item.get("model") or item.get("model_id"),
            "model": item.get("model") or "",
            "source": "admin",
        }
        for item in redacted_model_access(user.id).get("llm", [])
        if item.get("available")
    ]


def apply_allowed_llm_selection(selection: dict[str, Any] | None) -> dict[str, Any] | None:
    """Allow only admin-granted LLM profile/model selections for ordinary users."""
    user = get_current_user()
    if user.is_admin or not selection:
        return selection
    profile_id = str(selection.get("profile_id") or "")
    model_id = str(selection.get("model_id") or "")
    for item in redacted_model_access(user.id).get("llm", []):
        if item.get("profile_id") == profile_id and item.get("model_id") == model_id:
            return selection
    raise PermissionError("This model is not assigned to your account.")


def redacted_catalog_summary() -> dict[str, Any]:
    return {"model_access": deepcopy(redacted_model_access())}
