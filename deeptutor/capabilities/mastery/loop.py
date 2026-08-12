"""Mastery path loop-capability hooks."""

from __future__ import annotations

from importlib import resources
import logging
from typing import Any

from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext

logger = logging.getLogger(__name__)


def _bind_pending_ask_user_args(kwargs: dict[str, Any], path_id: str) -> dict[str, Any]:
    """Replace model-authored quiz display data with persisted public state.

    Binding at this adapter boundary prevents the model from changing question
    ids or reassigning A/B/C labels after a pause or on a later turn. Generic
    clarification cards remain untouched when no mastery question is pending.
    """
    if not path_id:
        return kwargs
    try:
        from deeptutor.learning.pending import public_pending_question
        from deeptutor.learning.storage import LearningStore

        progress = LearningStore().load(path_id)
        pending = progress.pending_question if progress is not None else None
    except Exception:
        logger.warning("Failed to load pending mastery question for ask_user", exc_info=True)
        return kwargs
    if pending is None:
        return kwargs

    updated = dict(kwargs)
    updated["questions"] = [public_pending_question(pending).to_ask_user_dict()]
    # Remove the accepted legacy shape so it cannot compete with the canonical
    # question list in ``build_ask_user_payload``.
    updated.pop("question", None)
    updated.pop("options", None)
    return updated


class MasteryLoopCapability:
    """Turn-scoped integration for mastery-path tutoring.

    Reuses the full chat tool surface (rag / read_source / ask_user / … under
    the same user toggles as chat) and adds the mastery engine tools on top.
    """

    name = "mastery"
    owned_tools = MASTERY_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("mastery_mode"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        override = _prompt_text(prompts, ("mastery", "system"))
        content = override or _load_system_prompt(language)
        return PromptBlock("mastery_tutor", content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if not self.is_active(context):
            return kwargs
        path_id = str(context.metadata.get("mastery_path_id") or "").strip()
        if tool_name == "ask_user":
            return _bind_pending_ask_user_args(kwargs, path_id)
        if tool_name in MASTERY_TOOL_NAMES:
            updated = dict(kwargs)
            updated["_mastery_path_id"] = path_id
            updated["_session_id"] = str(context.session_id or "").strip()
            updated["_turn_id"] = str(context.metadata.get("turn_id") or "").strip()
            return updated
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["MasteryLoopCapability"]
