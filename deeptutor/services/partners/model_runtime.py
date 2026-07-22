"""Helpers for resolving per-partner LLM model selection."""

from __future__ import annotations

from typing import Any

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection import LLMSelection
from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection


def normalize_partner_llm_selection(value: Any) -> dict[str, str] | None:
    """Return a validated selection dict, or ``None`` for system default."""
    selection = LLMSelection.from_payload(value)
    return selection.to_dict() if selection else None


def resolve_partner_llm_config(partner_config: Any) -> LLMConfig:
    """Resolve the effective LLM config for a partner config object.

    Configs store ``llm_selection`` as a stable catalog reference. Configs
    migrated from TutorBot may still carry a raw ``model`` string, which is
    applied as a model-only override on top of the system default provider.
    """
    selection = normalize_partner_llm_selection(getattr(partner_config, "llm_selection", None))
    if selection:
        return resolve_llm_config_for_selection(selection)

    base = resolve_llm_config_for_selection(None)
    legacy_model = str(getattr(partner_config, "model", "") or "").strip()
    if legacy_model:
        return base.model_copy(update={"model": legacy_model})
    return base


__all__ = ["normalize_partner_llm_selection", "resolve_partner_llm_config"]
