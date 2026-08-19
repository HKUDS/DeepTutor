"""Setup loop capability — DeepTutor configuring its own install.

A *plain* :class:`~deeptutor.capabilities.protocol.LoopCapability`, not a
:class:`~deeptutor.capabilities.protocol.KnowledgeCapability`: configuring the
app is something the user asks for in the middle of ordinary work ("switch to
Chinese and use a better PDF parser"), so the turn keeps its normal tool
surface — knowledge bases, web search, the lot — and these four tools are added
on top. An exclusive capability would strip exactly the abilities a
configuration conversation is often about.

Activation is decided by :func:`~deeptutor.capabilities.setup.binding.is_setup_turn`
on objective signals rather than by the model's sense of relevance; see that
module for why.

The system block carries the install's current gaps. That is what lets the
model open with something useful ("your knowledge bases can't be built yet —
no embedding model is selected") instead of a menu, and it costs one filesystem
pass that ``is_active`` has already paid for.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.capabilities.setup.binding import (
    SETUP_CAPABILITY_NAME,
    cached_gaps,
    is_setup_turn,
    mark_intro_shown,
    setup_activation,
)
from deeptutor.capabilities.setup.tools import SETUP_TOOL_NAMES
from deeptutor.core.context import UnifiedContext


class SetupCapability:
    """Turn-scoped ability to inspect and change DeepTutor's own configuration."""

    name = SETUP_CAPABILITY_NAME
    owned_tools = SETUP_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return is_setup_turn(context)

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        reason = setup_activation(context)
        if not reason:
            return None
        override = _prompt_text(prompts, ("setup", "system"))
        content = override or _load_system_prompt(language)

        gaps = cached_gaps(context)
        if gaps:
            lines = "\n".join(f"- {gap.summary} {gap.remedy}".strip() for gap in gaps)
            content = f"{content}\n\n## What this install is currently missing\n{lines}"
        else:
            content = f"{content}\n\n## What this install is currently missing\n- Nothing."

        if reason == "intro":
            # The user did not raise this subject, so the opening has to earn its
            # place: name the one thing that is missing, offer to fix it, and
            # drop it if they would rather do something else.
            content = (
                f"{content}\n\n## This is the user's first conversation\n"
                "They have not asked about configuration. Answer whatever they "
                "actually said first. Then, in one or two sentences at the end, "
                "mention the single most important gap above and offer to set it "
                "up. Do not list every gap, do not open with it, and do not "
                "raise it again if they move on."
            )
            # Spent only here: an explicit or intent-driven turn must not consume
            # the one proactive offer an unconfigured install gets.
            mark_intro_shown()
        return PromptBlock(SETUP_CAPABILITY_NAME, content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        # Nothing server-owned to inject: these tools address settings by key
        # and resolve scope from the caller's own identity, so there is no
        # turn-scoped handle the model could otherwise forge.
        _ = (tool_name, context)
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
    lang = "zh" if str(language or "en").lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["SetupCapability"]
