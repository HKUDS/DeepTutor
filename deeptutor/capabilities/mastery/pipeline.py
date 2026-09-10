"""The mastery tutoring loop.

Mastery used to be a chat turn wearing a hat: the chat pipeline ran, and a
loop extension added nine tools and one system block on top of chat's own
playbook. That block then had to spend most of its length *arguing* with the
prompt above it — "this differs from ordinary chat, where ask_user is just a
tool", "posing a question ends the turn", "never write the choices as plain
text" — because the model had already been told, in the block before, how an
ordinary exploring turn behaves.

This class is the same loop engine with the tutor's own protocol stated first
instead. :class:`MasteryPromptAssembler` replaces the foundation of the system
prompt — identity, standing policy, what a round means — so "posing a question
ends the turn" arrives as this loop's native turn semantics rather than as an
exception to somebody else's.

What is deliberately *not* changed is the tool surface. A mastery turn mounts
exactly what a chat turn would (the learner's own composer toggles, the same
auto-mount rules) plus the mastery tools, so moving into a course never
silently takes a tool away. Narrowing that surface is a one-line override here
if it ever proves worth doing — which is the point of having this class at all.
"""

from __future__ import annotations

from typing import Any

from deeptutor.agents.loop.pipeline import AgenticLoopPipeline
from deeptutor.agents.loop.prompt_blocks import LoopPromptAssembler, PromptBlock
from deeptutor.capabilities.mastery.loop import NATIVE_LOOP_FLAG
from deeptutor.capabilities.mastery.mode import normalize_mode
from deeptutor.core.context import UnifiedContext


class MasteryPromptAssembler(LoopPromptAssembler):
    """Open the system prompt with the tutor's protocol, not chat's.

    The one block that varies is what *this* conversation is for. It sits
    directly after the tutor's identity and before the loop protocol, because
    a sitting's purpose is the frame everything below it is read through —
    "design the outline" and "clear what is due" produce very different right
    answers from the same playbook.
    """

    def foundation_blocks(self, context: UnifiedContext) -> list[PromptBlock]:
        kind = normalize_mode(context.metadata.get("mastery_session_mode"))
        return [
            PromptBlock("mastery_tutor", self._t("general")),
            PromptBlock("mastery_session_mode", self._t(f"session.{kind}")),
            PromptBlock("runtime_context", self._runtime_context_block()),
            PromptBlock("runtime_policy", self._t("runtime_policy")),
            PromptBlock("mastery_loop", self._t("loop.system")),
            PromptBlock("mastery_playbook", self._t("playbook")),
        ]


class MasteryLoopPipeline(AgenticLoopPipeline):
    """Run a mastery tutoring turn as one agent loop.

    Same engine, same tool surface, different protocol — see the module
    docstring.
    """

    prompt_module = "mastery"
    prompt_agent = "mastery_loop"
    # Labels, notices and the KB-seed header are engine copy, shared with every
    # loop; the mastery pack states only the tutor's own blocks.
    prompt_base_module = "chat"
    prompt_base_agent = "agentic_chat"
    prompt_assembler_class = MasteryPromptAssembler

    async def run(self, context: UnifiedContext, stream: Any) -> dict[str, Any]:
        # Tells MasteryLoopCapability that the playbook is already the
        # foundation of this prompt, so it does not contribute a second copy.
        context.metadata[NATIVE_LOOP_FLAG] = True
        return await super().run(context, stream)


__all__ = ["MasteryLoopPipeline", "MasteryPromptAssembler"]
