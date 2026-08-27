"""Structured prompt assembly for the chat agent loop."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.services.prompt.language import append_language_directive


class ChatPromptAssembler:
    """Build system prompts from explicit, category-named blocks."""

    def __init__(self, *, prompts: dict[str, Any], language: str) -> None:
        self.prompts = prompts
        self.language = "zh" if language.lower().startswith("zh") else "en"

    def system_prompt(
        self,
        *,
        context: UnifiedContext,
        tool_manifest: str,
        kb_note: str = "",
        deferred_tools_manifest: str = "",
        notebook_manifest: str = "",
        workspace_note: str = "",
        capability_blocks: list[PromptBlock] | None = None,
        include_tool_manifest: bool = True,
    ) -> str:
        return self.render(
            self.blocks(
                context=context,
                tool_manifest=tool_manifest,
                kb_note=kb_note,
                deferred_tools_manifest=deferred_tools_manifest,
                notebook_manifest=notebook_manifest,
                workspace_note=workspace_note,
                capability_blocks=capability_blocks,
                include_tool_manifest=include_tool_manifest,
            )
        )

    def render(self, blocks: list[PromptBlock]) -> str:
        """Join assembled blocks into the system prompt string.

        Split out of :meth:`system_prompt` so a caller that also needs the
        block list (the per-turn context-budget breakdown) can assemble once
        and render the very blocks it measures, instead of calling
        :meth:`blocks` a second time and risking drift.
        """
        joined = "\n\n---\n\n".join(
            f"## {block.name}\n{block.content.strip()}" for block in blocks if block.content.strip()
        )
        return append_language_directive(joined, self.language)

    def blocks(
        self,
        *,
        context: UnifiedContext,
        tool_manifest: str,
        kb_note: str = "",
        deferred_tools_manifest: str = "",
        notebook_manifest: str = "",
        workspace_note: str = "",
        capability_blocks: list[PromptBlock] | None = None,
        include_tool_manifest: bool = True,
    ) -> list[PromptBlock]:
        blocks: list[PromptBlock] = [
            PromptBlock("general", self._general_block(context)),
            PromptBlock("runtime_context", self._runtime_context_block()),
            PromptBlock("runtime_policy", self._t("runtime_policy")),
            PromptBlock("loop", self._t("loop.system")),
        ]
        # Capability playbooks sit high so they frame the whole turn when active;
        # empty blocks are omitted by ``system_prompt``'s join.
        blocks.extend(capability_blocks or [])
        if context.sidebar_context:
            blocks.append(PromptBlock("sidebar_tutor_context", context.sidebar_context))
        if context.persona_context:
            blocks.append(PromptBlock("persona_style", context.persona_context))
        partner_policy = self._partner_turn_policy(context)
        if partner_policy:
            blocks.append(PromptBlock("partner_turn_policy", partner_policy))
        if context.memory_context:
            blocks.append(PromptBlock("memory", context.memory_context))
        if include_tool_manifest:
            tools = tool_manifest or self._fallback_empty_tool_list()
            if kb_note:
                tools = f"{kb_note}\n\n{tools}"
            blocks.append(PromptBlock("tools", tools))
        elif kb_note:
            blocks.append(PromptBlock("knowledge_base_note", kb_note))
        if context.skills_manifest:
            blocks.append(PromptBlock("skills", context.skills_manifest))
        if context.source_manifest:
            blocks.append(PromptBlock("sources", context.source_manifest))
        if deferred_tools_manifest:
            blocks.append(PromptBlock("extended_tools", deferred_tools_manifest))
        if notebook_manifest:
            blocks.append(PromptBlock("notebooks", notebook_manifest))
        if workspace_note:
            blocks.append(PromptBlock("workspace", workspace_note))
        # Volatile content deliberately gets NO system block: the KB seed
        # rides in the trailing user message, so the system prompt stays
        # byte-stable for the whole turn (every loop round shares one prefix).
        return blocks

    def _general_block(self, context: UnifiedContext) -> str:
        """Product identity, or the partner identity when one is present.

        Partner turns carry ``metadata["agent_identity"]`` (user-given name +
        description); their identity comes from that and the Soul block, so
        the "You are DeepTutor" general is swapped for ``general_partner``.
        Chat turns carry no identity and render the general block unchanged.
        """
        identity = context.metadata.get("agent_identity")
        name = ""
        if isinstance(identity, dict):
            name = str(identity.get("name") or "").strip()
        if not name:
            return self._t("general")
        content = self._t(
            "general_partner",
            default='You are a companion created by the user. The name the user gave you is "{name}".',
        ).format(name=name)
        description = str(identity.get("description") or "").strip()
        if description:
            description_line = self._t(
                "general_partner_description",
                default="The user's description of you: {description}",
            ).format(description=description)
            content = f"{content}\n{description_line}"
        return content

    def _runtime_context_block(self) -> str:
        """Inject the real current date so the model can resolve relative time.

        Without this, a request like "今天上海天气怎样？" makes the model fall
        back to its training-data cutoff when composing a web_search query
        (e.g. "上海天气 2025年6月") — stale relative to the real system clock.
        The injected date lets it convert "今天 / 本月 / 今年 / 现在" to the
        correct date instead of guessing.

        Granularity is day only (no clock time): the system prompt is
        built once per turn and reused across every loop round, so omitting the
        time keeps it byte-stable within a day and preserves prompt-cache hits.
        Resolving relative dates does not need sub-day precision.
        """
        now = datetime.now().astimezone()
        # The date *format* is locale data, so it lives here; the guidance
        # prose around it is copy, so it lives in the per-language yaml like
        # every other block. The default below is only the invariant fact, not
        # a second copy of the prose.
        if self.language == "zh":
            dt_str = f"{now.year}年{now.month}月{now.day}日"
        else:
            dt_str = now.date().isoformat()
        template = self._t("runtime_context", default="Current date: {datetime}.")
        try:
            return template.format(datetime=dt_str)
        except (KeyError, IndexError, ValueError):
            return f"{template} {dt_str}".strip()

    def _partner_turn_policy(self, context: UnifiedContext) -> str:
        identity = context.metadata.get("agent_identity")
        if not isinstance(identity, dict):
            return ""
        if not str(identity.get("name") or "").strip():
            return ""
        return self._t("partner_turn_policy", default="")

    def user_message(
        self,
        *,
        context: UnifiedContext,
        kb_seed: str = "",
    ) -> str:
        template = self._t("loop.user", default="{user_message}")
        try:
            content = template.format(user_message=context.user_message)
        except (KeyError, IndexError, ValueError):
            content = context.user_message
        if kb_seed:
            content = f"{content}\n\n{kb_seed}"
        return content

    def finish_exhausted_instruction(self) -> str:
        return self._t(
            "loop.finish_exhausted",
            default=(
                "The round budget ran out before every gap was closed. Stop "
                "calling tools and answer now with what you have, noting "
                "briefly what remains uncertain."
            ),
        )

    def settle_exhausted_instruction(self) -> str:
        return self._t(
            "loop.settle_exhausted",
            default=(
                "The exploration round budget is exhausted. Do not start new "
                "searches or optional work. Complete only protocol steps, state "
                "transitions, or user interactions already made necessary by "
                "the work above, then provide the final user-facing answer."
            ),
        )

    def _fallback_empty_tool_list(self) -> str:
        return "- 无" if self.language == "zh" else "- none"

    def _t(self, key: str, default: str = "") -> str:
        value: Any = self.prompts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value if isinstance(value, str) else default


__all__ = ["ChatPromptAssembler", "PromptBlock"]
