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
from deeptutor.capabilities.mastery.history import STATE_REFERENCE_NOTICE, share_mastery_history
from deeptutor.capabilities.mastery.loop import NATIVE_LOOP_FLAG
from deeptutor.capabilities.mastery.memory import MEMORY_NOTICE
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

    def blocks(self, **kwargs):
        if getattr(self, "native_tool_schemas", False):
            kwargs["include_tool_manifest"] = False
        return super().blocks(**kwargs)

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

    async def _prepare_deferred_tools(self, context):
        await super()._prepare_deferred_tools(context)
        self._deferred_outline_names = set()
        if normalize_mode(context.metadata.get("mastery_session_mode")) == "outline":
            return
        if (context.allowed_builtin_tools is not None
                and "load_tools" not in context.allowed_builtin_tools):
            return  # A restricted caller must retain eager access to owned tools.
        from deeptutor.runtime.providers.view import ProviderToolView
        from deeptutor.runtime.registry.deferred_tools import (
            DeferredToolLoader,
            render_deferred_tools_manifest,
        )
        from deeptutor.services.mcp import load_loaded_tools

        view = self._tool_view
        names = {"mastery_build", "mastery_revise", "mastery_revise_batch"}
        owned = set(self._capability_owned_tools(context))
        local = [view.registry.get(name) for name in sorted(names & owned)]
        local = [tool for tool in local if tool is not None]
        if not local:
            return
        self._deferred_outline_names = {tool.name for tool in local}
        pool = (*view.pool, *local)
        loaded = load_loaded_tools(context.session_id)
        if view.loader:
            loaded |= view.loader.loaded_names
        loader = DeferredToolLoader(registry=view.registry, session_id=context.session_id,
            loaded=loaded, allowed={tool.name for tool in pool},
            capability_names=self._deferred_outline_names)
        self._tool_view = ProviderToolView(registry=view.registry, loader=loader, pool=pool,
            manifest="\n\n".join(filter(None, [view.manifest,
                render_deferred_tools_manifest(local, language=self.language)])))
        self._deferred_loader = loader
        self._deferred_pool = list(pool)

    def _compose_enabled_tools(self, context):
        deferred = getattr(self, "_deferred_outline_names", set())
        return [name for name in super()._compose_enabled_tools(context) if name not in deferred]

    async def _capability_pre_loop_briefings(self, context, stream):
        briefing = await super()._capability_pre_loop_briefings(context, stream)
        snapshot = context.extension("mastery").get("status_snapshot")
        return briefing.replace(snapshot, "", 1).strip() if snapshot else briefing

    def _build_system_prompt(self, enabled_tools, context, *, include_tool_manifest=True):
        self._prompt_assembler.native_tool_schemas = (
            bool(enabled_tools) and self._can_use_native_tool_calling()
        )
        prompt = super()._build_system_prompt(
            enabled_tools, context, include_tool_manifest=include_tool_manifest,
        )
        snapshot = context.extension("mastery").get("status_snapshot")
        if snapshot:
            self._runtime_snapshots["mastery_status_snapshot"] = snapshot
        return prompt + STATE_REFERENCE_NOTICE + MEMORY_NOTICE

    def project_model_request(self, messages):
        from copy import deepcopy

        projected = deepcopy(messages)
        share_mastery_history(projected, len(projected))
        return projected

    def _build_loop_messages(self, **kwargs):
        messages = super()._build_loop_messages(**kwargs)
        share_mastery_history(messages, self._model_turn_start)
        return messages

    async def run(self, context: UnifiedContext, stream: Any) -> dict[str, Any]:
        # Tells MasteryLoopCapability that the playbook is already the
        # foundation of this prompt, so it does not contribute a second copy.
        context.metadata[NATIVE_LOOP_FLAG] = True
        import asyncio

        from deeptutor.learning.storage import LearningStore
        from deeptutor.services.workspace.knowledge import learning_source_access

        path_id = str(context.metadata.get("mastery_path_id") or "")
        topic = await asyncio.to_thread(LearningStore().get_topic, path_id) if path_id else None
        refs = []
        for source in topic.sources if topic else []:
            if source.kind.value == "knowledge_base":
                refs.append(source.source_id)
            elif source.kind.value == "file" and source.metadata.get("kb_name"):
                refs.append(source.metadata["kb_name"])
        context.knowledge_bases = list(dict.fromkeys([*context.knowledge_bases, *refs]))
        with learning_source_access(refs):
            return await super().run(context, stream)


__all__ = ["MasteryLoopPipeline", "MasteryPromptAssembler"]
