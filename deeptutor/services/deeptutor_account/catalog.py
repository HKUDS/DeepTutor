"""Publish the available Studio chat models to the owner's model catalog."""

from __future__ import annotations

import hashlib
from typing import Any

from deeptutor.services.config.model_catalog import MODEL_CAPABILITY_KEYS, ModelCatalogService

from .client import DeepTutorAccountError

PROFILE_ID = "llm-profile-deeptutor"
MANAGED_BY = "deeptutor_device_login"


def parse_models(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise DeepTutorAccountError("invalid_response", 502)
    models = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id, metadata = row.get("id"), row.get("model_serve")
        if (
            not isinstance(model_id, str)
            or not model_id
            or model_id.startswith("@")
            or not isinstance(metadata, dict)
            or metadata.get("official") is False
        ):
            continue
        capabilities = metadata.get("capabilities")
        if not isinstance(capabilities, list) or "chat" not in capabilities:
            continue
        label = metadata.get("label")
        models[model_id] = {
            "id": model_id,
            "label": label if isinstance(label, str) and label else model_id,
            "capabilities": {key: key in capabilities for key in MODEL_CAPABILITY_KEYS},
            "available": metadata.get("available") is True,
        }
    return list(models.values())


def publish_models(
    service: ModelCatalogService, base_url: str, models: list[dict[str, Any]]
) -> None:
    rows = [
        {
            "id": f"llm-model-deeptutor-{hashlib.sha256(item['id'].encode()).hexdigest()[:16]}",
            "name": item["label"],
            "model": item["id"],
            "capabilities": item["capabilities"],
            "managed_by": MANAGED_BY,
        }
        for item in models
        if item["available"]
    ]
    if not rows and not service.path.exists():
        return

    def mutate(catalog: dict[str, Any]) -> None:
        llm = catalog["services"]["llm"]
        active = llm.get("active_profile_id")
        profiles = [p for p in llm["profiles"] if p.get("managed_by") != MANAGED_BY]
        if rows:
            profiles.append(
                {
                    "id": PROFILE_ID,
                    "name": "DeepTutor",
                    "binding": "deeptutor",
                    "base_url": base_url,
                    "api_key": "",
                    "api_format": "openai_chat",
                    "managed_by": MANAGED_BY,
                    "read_only": True,
                    "owner_bound": True,
                    "models": rows,
                }
            )
        llm["profiles"] = profiles
        if rows and active in (None, "", PROFILE_ID):
            llm["active_profile_id"] = PROFILE_ID
            if llm.get("active_model_id") not in {row["id"] for row in rows}:
                llm["active_model_id"] = rows[0]["id"]
        elif not rows and active == PROFILE_ID:
            llm["active_profile_id"] = None
            llm["active_model_id"] = None

    service.update(mutate)


def preserve_managed_profile(current: dict[str, Any], proposed: dict[str, Any]) -> None:
    """Keep a Settings draft from overwriting a model list published by Studio."""
    live = current.get("services", {}).get("llm", {})
    llm = proposed["services"]["llm"]
    profiles = [
        profile
        for profile in llm.get("profiles", [])
        if profile.get("id") != PROFILE_ID and profile.get("managed_by") != MANAGED_BY
    ]
    managed = next(
        (
            profile
            for profile in live.get("profiles", [])
            if profile.get("managed_by") == MANAGED_BY
        ),
        None,
    )
    llm["profiles"] = [*profiles, managed] if managed else profiles
    if llm.get("active_profile_id") == PROFILE_ID:
        if not managed:
            llm["active_profile_id"] = None
            llm["active_model_id"] = None
        elif llm.get("active_model_id") not in {row["id"] for row in managed["models"]}:
            llm["active_model_id"] = managed["models"][0]["id"]
