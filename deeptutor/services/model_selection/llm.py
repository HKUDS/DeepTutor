"""Helpers for selecting configured LLM models without mutating settings."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from deeptutor.services.provider_registry import find_by_name


@dataclass(frozen=True, slots=True)
class LLMSelection:
    """A safe reference to one configured LLM model.

    The selection intentionally carries IDs only. Provider secrets stay in the
    server-side catalog and are resolved only at runtime.
    """

    profile_id: str
    model_id: str | None
    source: Literal["platform", "byok"] = "platform"
    generation: int | None = None

    @classmethod
    def from_payload(cls, value: Any) -> "LLMSelection | None":
        if isinstance(value, LLMSelection):
            return value
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("Invalid LLM selection: expected an object.")

        source = str(value.get("source") or "platform").strip().lower()
        if source not in {"platform", "byok"}:
            raise ValueError("Invalid LLM selection: source must be platform or byok.")

        profile_id = str(value.get("profile_id") or "").strip()
        model_id = str(value.get("model_id") or "").strip() or None
        if not profile_id and not model_id:
            return None
        if not profile_id:
            raise ValueError("Invalid LLM selection: profile_id is required.")
        if source == "platform" and not model_id:
            raise ValueError("Invalid LLM selection: model_id is required for platform.")

        raw_generation = value.get("generation")
        if raw_generation is None:
            raw_generation = value.get("profile_generation")
        generation: int | None = None
        if raw_generation is not None and raw_generation != "":
            try:
                generation = int(raw_generation)
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid LLM selection: generation must be an integer.") from exc
            if generation <= 0:
                raise ValueError("Invalid LLM selection: generation must be positive.")
        return cls(
            source=source,  # type: ignore[arg-type]
            profile_id=profile_id,
            model_id=model_id,
            generation=generation,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "profile_id": self.profile_id,
        }
        if self.model_id is not None:
            payload["model_id"] = self.model_id
        if self.generation is not None:
            payload["generation"] = self.generation
        return payload


def _coerce_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _llm_service(catalog: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(catalog, dict):
        return {}
    services = catalog.get("services")
    return services.get("llm", {}) if isinstance(services, dict) else {}


def list_llm_options(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted list of configured chat-selectable LLM models."""
    service = _llm_service(catalog)
    active_profile_id = str(service.get("active_profile_id") or "")
    active_model_id = str(service.get("active_model_id") or "")

    options: list[dict[str, Any]] = []
    for profile in service.get("profiles", []) or []:
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id") or "").strip()
        if not profile_id:
            continue
        provider = str(profile.get("binding") or "").strip()
        profile_name = str(profile.get("name") or provider or "LLM").strip()
        # Human-readable provider name from the registry ("OpenRouter",
        # "VolcEngine Coding Plan", ...) so the UI never shows binding keys.
        provider_spec = find_by_name(provider)
        provider_label = provider_spec.label if provider_spec else provider

        for model in profile.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or "").strip()
            model_value = str(model.get("model") or "").strip()
            if not model_id or not model_value:
                continue

            option: dict[str, Any] = {
                "profile_id": profile_id,
                "model_id": model_id,
                "profile_name": profile_name,
                "model_name": str(model.get("name") or model_value).strip(),
                "model": model_value,
                "provider": provider,
                "provider_label": provider_label,
                "is_active_default": (
                    profile_id == active_profile_id and model_id == active_model_id
                ),
            }
            context_window = _coerce_int(model.get("context_window"))
            if context_window is None:
                context_window = _coerce_int(model.get("context_window_tokens"))
            if context_window is not None:
                option["context_window"] = context_window
            options.append(option)

    return {
        "active": {"profile_id": active_profile_id, "model_id": active_model_id}
        if active_profile_id and active_model_id
        else None,
        "options": options,
    }


def apply_llm_selection_to_catalog(
    catalog: dict[str, Any],
    selection: LLMSelection | dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a catalog copy whose active LLM points at *selection*."""
    resolved = LLMSelection.from_payload(selection)
    selected = deepcopy(catalog)
    if resolved is None:
        return selected
    if resolved.source == "byok":
        # BYOK selections are references into the user's Vault, not entries in
        # the administrator's platform catalog.
        return selected

    service = _llm_service(selected)
    for profile in service.get("profiles", []) or []:
        if not isinstance(profile, dict) or profile.get("id") != resolved.profile_id:
            continue
        for model in profile.get("models", []) or []:
            if isinstance(model, dict) and model.get("id") == resolved.model_id:
                service["active_profile_id"] = resolved.profile_id
                service["active_model_id"] = resolved.model_id
                return selected
        break

    raise ValueError("Invalid LLM selection: selected profile/model was not found.")


__all__ = ["LLMSelection", "apply_llm_selection_to_catalog", "list_llm_options"]
