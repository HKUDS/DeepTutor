"""Apply one provider editor without migrating or replacing the catalog."""

from copy import deepcopy
from typing import Any

from deeptutor.services.config.model_catalog import restore_catalog_secrets


def merge_provider_edit(
    current: dict[str, Any],
    service: str,
    profile: dict[str, Any],
    *,
    connection: dict[str, Any] | None = None,
    active_model_id: str | None = None,
    activate: bool = False,
    stored_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep existing IDs, other providers, defaults, and extension fields.

    Masked keys resolve from the saved draft first, then live settings. Shared
    credentials are updated by their existing connection ID, never by vendor.
    """
    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("A provider ID is required.")
    result = deepcopy(current)
    bucket = result["services"][service]
    profiles = bucket["profiles"]
    index = next((i for i, item in enumerate(profiles) if item.get("id") == profile_id), None)
    if index is None:
        profiles.append(deepcopy(profile))
    else:
        profiles[index] = deepcopy(profile)
    if connection is not None:
        connection_id = connection.get("id")
        if not connection_id or connection_id != profile.get("connection_id"):
            raise ValueError("The connection must belong to the provider being saved.")
        connections = result.setdefault("connections", [])
        index = next(
            (i for i, item in enumerate(connections) if item.get("id") == connection_id), None
        )
        if index is None:
            connections.append(deepcopy(connection))
        else:
            connections[index] = deepcopy(connection)
    if activate:
        if service == "task":
            bucket["mode"] = "profiles"
        models = profile.get("models", [])
        if service != "search" and not any(
            item.get("id") == active_model_id and item.get("model") for item in models
        ):
            raise ValueError("Choose a model before making this provider active.")
        bucket["active_profile_id"] = profile_id
        if service != "search":
            bucket["active_model_id"] = active_model_id
    if stored_draft:
        result = restore_catalog_secrets(result, stored_draft)
    return restore_catalog_secrets(result, current)
