"""Scoped provider/model edits over the existing, lossless model catalog."""

from copy import deepcopy

from deeptutor.services.config.model_catalog import SERVICE_NAMES, restore_catalog_secrets
from deeptutor.services.config.provider_links import (
    PROVIDER_FIELDS,
    provider_source,
    referenced_models,
)


def _identity(ref):
    return {key: ref[key] for key in ("connection_id", "service", "profile_id") if ref.get(key)}


def _select_remaining(bucket, service):
    candidates = [
        p
        for p in bucket["profiles"]
        if not p.get("provider_only") and (service == "search" or p.get("models"))
    ]
    profile = next(
        (p for p in candidates if p["id"] == bucket.get("active_profile_id")),
        candidates[0] if candidates else None,
    )
    bucket["active_profile_id"] = profile["id"] if profile else None
    if service != "search":
        models = (profile or {}).get("models", [])
        if not any(m["id"] == bucket.get("active_model_id") for m in models):
            bucket["active_model_id"] = models[0]["id"] if models else None


def _task_choice(result, bucket, choice):
    """Validate one task model choice — the global one or a single task's.

    Returns the keys that describe it, so the global service and a per-task
    override are written from the same validation rather than from two.
    """
    mode = choice.get("mode")
    if mode == "inherit":
        return {"mode": mode}
    if mode == "reference":
        from deeptutor.services.model_selection.llm import apply_llm_selection_to_catalog

        selection = choice.get("selection")
        if not selection:
            raise ValueError("Choose a configured task model.")
        apply_llm_selection_to_catalog(result, selection)
        return {"mode": mode, "selection": deepcopy(selection)}
    if mode == "profiles":
        profile = next(
            (p for p in bucket["profiles"] if p["id"] == choice.get("active_profile_id")), None
        )
        if not profile or not any(
            m.get("id") == choice.get("active_model_id") for m in profile.get("models", [])
        ):
            raise ValueError("Choose a configured task model.")
        return {
            "mode": mode,
            "active_profile_id": profile["id"],
            "active_model_id": choice["active_model_id"],
        }
    raise ValueError("Choose a task model mode.")


def merge_registry_edit(current, edit, *, stored_draft=None):
    """Only the addressed entity changes. Models never submit credentials."""
    result = deepcopy(current)
    kind, deleting = edit["kind"], edit.get("delete", False)
    if kind == "provider":
        ref = edit.get("ref") or {}
        fields = {
            k: deepcopy(v) for k, v in (edit.get("fields") or {}).items() if k in PROVIDER_FIELDS
        }
        try:
            source, _ = provider_source(result, ref)
        except ValueError:
            if deleting or not ref.get("connection_id") or not fields.get("provider"):
                raise ValueError(
                    "Choose an existing provider or create a named connection."
                ) from None
            source = {"id": ref["connection_id"]}
            result.setdefault("connections", []).append(source)
        if source.get("managed_by") and deleting:
            raise ValueError("Manage this account from its authentication settings.")
        if deleting:
            if referenced_models(result, ref):
                raise ValueError(
                    "This provider is used by models. Change or remove those models first."
                )
            items = (
                result["connections"]
                if ref.get("connection_id")
                else result["services"][ref["service"]]["profiles"]
            )
            items.remove(source)
        else:
            source.update(fields)
            if not str(source.get("name") or "").strip():
                raise ValueError("A provider name is required.")
    elif kind == "task_choice":
        choice = edit.get("task") or {}
        bucket = result["services"]["task"]
        task_kind = choice.get("task_kind")
        if task_kind is None:
            bucket.update(_task_choice(result, bucket, choice))
        else:
            from deeptutor.services.model_selection.tasks import TASK_KINDS, TASK_OVERRIDES_KEY

            if str(task_kind) not in {str(spec.kind) for spec in TASK_KINDS}:
                raise ValueError("Unknown background task.")
            overrides = bucket.setdefault(TASK_OVERRIDES_KEY, {})
            if choice.get("mode") == "global":
                # Following the global model is the absence of an override, not a
                # fourth stored mode: one fewer state to keep in agreement, and a
                # catalog that never accumulates rows for defaults.
                overrides.pop(str(task_kind), None)
                if not overrides:
                    bucket.pop(TASK_OVERRIDES_KEY, None)
            else:
                overrides[str(task_kind)] = _task_choice(result, bucket, choice)
    elif kind in {"model", "default"}:
        service = edit.get("service")
        if service not in SERVICE_NAMES:
            raise ValueError("Unknown model service.")
        bucket = result["services"][service]
        profile_id = edit.get("profile_id")
        if not profile_id:
            raise ValueError("A model profile ID is required.")
        profile = next((p for p in bucket["profiles"] if p["id"] == profile_id), None)
        model = deepcopy(edit.get("model") or {})
        config = deepcopy(edit.get("config") or {})
        ref = (config if service == "search" else model).get("provider_ref")
        if profile is None:
            if deleting or kind == "default" or not ref:
                raise ValueError("Choose an existing provider before creating a model.")
            owner, _ = provider_source(result, ref)
            if owner.get("owner_bound") or owner.get("managed_by"):
                raise ValueError(
                    "This account manages its models through sign-in. Use an imported model."
                )
            profile = {
                "id": profile_id,
                "name": owner.get("name", ""),
                "binding": ref.get("binding")
                or owner.get("binding")
                or owner.get("provider")
                or "custom",
                "provider_ref": deepcopy(ref),
                "models": [],
            }
            bucket["profiles"].append(profile)
        if ref:
            owner, _ = provider_source(result, ref)
            if (owner.get("owner_bound") or owner.get("managed_by")) and owner.get(
                "id"
            ) != profile_id:
                raise ValueError(
                    "This account manages its models through sign-in. Use an imported model."
                )
        if service == "search":
            if kind == "model":
                if deleting:
                    if profile.get("provider_ref"):
                        bucket["profiles"].remove(profile)
                    else:
                        profile["provider_only"] = True
                else:
                    for field in ("provider_ref", "display_name", "max_results"):
                        if field in config:
                            profile[field] = config[field]
                    profile.pop("provider_only", None)
        else:
            model_id = edit.get("model_id") or model.get("id")
            existing = next((m for m in profile["models"] if m["id"] == model_id), None)
            if kind == "model":
                if deleting:
                    if existing:
                        if (
                            service == "llm"
                            and result["services"].get("task", {}).get("mode") == "reference"
                            and result["services"]["task"].get("selection")
                            == {"profile_id": profile_id, "model_id": model_id}
                        ):
                            raise ValueError(
                                "This model is assigned to background tasks. Choose another task model first."
                            )
                        profile["models"].remove(existing)
                    if not profile["models"] and profile.get("provider_ref"):
                        bucket["profiles"].remove(profile)
                else:
                    if not model_id or not str(model.get("model") or "").strip():
                        raise ValueError("A model ID is required.")
                    if existing is None and not (ref or profile.get("provider_ref")):
                        raise ValueError("Choose an existing provider before creating a model.")
                    if existing is None:
                        existing = {"id": model_id}
                        profile["models"].append(existing)
                    # Unknown per-model fields round-trip; credentials are never model fields.
                    for field in ("api_key", "base_url", "extra_headers", "api_version"):
                        model.pop(field, None)
                    if "context_window" in model and (
                        model.get("context_window") != existing.get("context_window")
                        or model.get("context_window_source") == "default"
                    ):
                        existing.pop("context_window_tokens", None)
                    existing.update(model)
                    existing["id"] = model_id
            elif existing is None:
                raise ValueError("The selected model no longer exists.")
        if kind == "default" or (not deleting and not bucket.get("active_profile_id")):
            bucket["active_profile_id"] = profile_id
            if service != "search":
                bucket["active_model_id"] = edit.get("model_id") or model.get("id")
            if service == "task":
                bucket["mode"] = "profiles"
        if deleting:
            _select_remaining(bucket, service)
    else:
        raise ValueError("Unknown registry edit.")
    if stored_draft:
        result = restore_catalog_secrets(result, stored_draft)
    return restore_catalog_secrets(result, current)
