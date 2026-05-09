"""TutorBot helpers for resolving per-bot LLM model selection."""

from __future__ import annotations

from typing import Any

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection import LLMSelection
from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection


def normalize_tutorbot_llm_selection(value: Any) -> dict[str, str] | None:
    """Return a validated selection dict, or ``None`` for system default."""
    selection = LLMSelection.from_payload(value)
    return selection.to_dict() if selection else None


def resolve_tutorbot_llm_config(bot_config: Any) -> LLMConfig:
    """Resolve the effective LLM config for a TutorBot config object.

    New configs store ``llm_selection`` as a stable catalog reference. Legacy
    configs may still contain a raw ``model`` string, which is applied as a
    model-only override on top of the current system default provider.
    """
    selection = normalize_tutorbot_llm_selection(getattr(bot_config, "llm_selection", None))
    if selection:
        return resolve_llm_config_for_selection(selection)

    base = resolve_llm_config_for_selection(None)
    legacy_model = str(getattr(bot_config, "model", "") or "").strip()
    if legacy_model:
        return base.model_copy(update={"model": legacy_model})
    return base


__all__ = ["normalize_tutorbot_llm_selection", "resolve_tutorbot_llm_config"]
