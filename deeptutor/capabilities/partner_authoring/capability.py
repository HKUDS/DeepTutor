"""Additive chat capability that turns a request into a reviewable Partner draft."""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.partner_authoring.binding import (
    PARTNER_AUTHORING_CAPABILITY_NAME,
    is_partner_authoring_turn,
)
from deeptutor.capabilities.partner_authoring.tools import PARTNER_AUTHORING_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext


class PartnerAuthoringCapability:
    name = PARTNER_AUTHORING_CAPABILITY_NAME
    owned_tools = PARTNER_AUTHORING_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return is_partner_authoring_turn(context)

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        _ = (context, prompts)
        lang = "zh" if str(language or "").lower().startswith("zh") else "en"
        prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
        return PromptBlock(self.name, prompt.read_text(encoding="utf-8").strip())

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name == "propose_partner":
            kwargs["_partner_authoring_context"] = context
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""

    def finish_instruction(self, context: UnifiedContext, final_text: str) -> str:
        _ = final_text
        if context.extension(self.name).get("draft_created"):
            return ""
        return (
            "The user asked to create a Partner, but no reviewable draft exists yet. "
            "Call propose_partner now with a complete profile; do not merely describe one."
        )


__all__ = ["PartnerAuthoringCapability"]
