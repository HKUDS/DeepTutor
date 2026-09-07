"""Turn assembly for the exploring-loop agent.

This is the loop's *host*: it owns everything :class:`~deeptutor.agents.loop.agent_loop.AgentLoop`
needs to run a turn — the LLM client, the round and token budgets, the tool
surface, the message list, tool dispatch and kwargs injection, the capability
hooks — and none of what makes a turn a *chat* turn.

What a specific loop owns is stated as three class attributes
(:attr:`~AgenticLoopPipeline.prompt_module`, :attr:`~AgenticLoopPipeline.prompt_agent`,
:attr:`~AgenticLoopPipeline.prompt_assembler_class`): which prompt pack to load
and how to assemble it into a system prompt. Chat is the default profile
because chat is what the base blocks describe; a loop with its own protocol —
mastery tutoring — subclasses and swaps the profile instead of adding a
correction block on top of chat's.

Tool composition is deliberately *not* one of those seams. A specialised loop
gets the same surface a chat turn would (the user's composer toggles, the same
auto-mount rules) plus its capability's own tools, so switching modes never
silently takes a tool away. A loop that wants a narrower surface overrides
:meth:`~AgenticLoopPipeline._compose_enabled_tools`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from deeptutor.agents._shared.tool_composition import (
    ToolMountFlags,
    compose_enabled_tools,
    default_optional_tools,
    user_has_mastery_topics,
    user_has_memory,
    user_has_notebooks,
    user_has_question_bank,
)
from deeptutor.agents._shared.tool_runtime import (
    bind_workspace_tool_runtime,
    drop_unconfigured_generation_tools,
)
from deeptutor.agents.loop.agent_loop import AgentLoop
from deeptutor.agents.loop.context_budget import LLMRequestSnapshot, build_context_budget
from deeptutor.agents.loop.prompt_blocks import LoopPromptAssembler
from deeptutor.capabilities import (
    LoopExtension,
    PromptBlock,
    active_loop_capabilities,
    any_exclusive_capability_active,
)
from deeptutor.capabilities.protocol import END_LOOP
from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import ToolLookup
from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)
from deeptutor.knowledge.manifest import KbManifest, render_manifest_note
from deeptutor.runtime.agentic import (
    DispatchOutcome,
    LLMClientConfig,
    UsageTracker,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
    dispatch_tool_calls,
)
from deeptutor.runtime.agentic.tool_dispatch import MAX_PARALLEL_TOOL_CALLS
from deeptutor.runtime.providers import ToolScope
from deeptutor.runtime.providers.view import ProviderToolView, build_tool_view
from deeptutor.runtime.registry.deferred_tools import DeferredToolLoader
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.config import get_chat_params
from deeptutor.services.llm import (
    get_llm_config,
    get_token_limit_kwargs,  # noqa: F401  (re-exported for tests)
    prepare_multimodal_messages,
    supports_tools,  # noqa: F401  (re-exported for tests)
)
from deeptutor.services.llm.context_window import resolve_effective_context_window
from deeptutor.services.prompt import get_prompt_manager
from deeptutor.services.prompt.lookup import prompt_text as _prompt_text
from deeptutor.tools.builtin import PARTNER_BUILTIN_TOOL_NAMES

logger = logging.getLogger(__name__)

# Chat memory tools a partner turn replaces with the partner_* variants.
_PARTNER_SUPPRESSED_TOOLS: tuple[str, ...] = ("read_memory", "write_memory")


LOOP_EXCLUDED_TOOLS: set[str] = set()
LOOP_OPTIONAL_TOOLS = default_optional_tools(excluded=LOOP_EXCLUDED_TOOLS)

KB_SEED_MAX_KBS = 3
KB_SEED_CHARS_PER_KB = 4000
# Exploring-loop budget: max LLM rounds in one turn's loop. A round without
# tool calls ends the loop early — that is the normal exit.
DEFAULT_MAX_ROUNDS = 8
CONTEXT_WINDOW_GUARD_RATIO = 0.9
_DispatchOutcome = DispatchOutcome


def _read_int(cfg: Any, *, key: str, default: int) -> int:
    if isinstance(cfg, dict):
        value = cfg.get(key, default)
    else:
        value = default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalise_user_reply(raw: Any) -> tuple[str, list[dict[str, str]] | None]:
    if isinstance(raw, str):
        return raw, None
    if isinstance(raw, dict):
        text = str(raw.get("text") or "")
        answers_raw = raw.get("answers")
        if isinstance(answers_raw, list) and answers_raw:
            answers: list[dict[str, str]] = []
            for entry in answers_raw:
                if not isinstance(entry, dict):
                    continue
                qid = str(entry.get("questionId") or entry.get("id") or "").strip()
                if qid:
                    answers.append({"questionId": qid, "text": str(entry.get("text") or "")})
            return text, answers or None
        return text, None
    return str(raw or ""), None


def _format_user_reply_body(
    text: str,
    answers: list[dict[str, str]] | None,
    ask_user_payload: dict[str, Any],
    *,
    prompts: dict[str, Any] | None = None,
) -> str:
    prompt_map = prompts or {}
    empty = _prompt_text(prompt_map, ("empty", "empty_reply"), "(empty reply)")
    skipped = _prompt_text(prompt_map, ("empty", "skipped_reply"), "(skipped)")
    question_fallback = _prompt_text(prompt_map, ("empty", "question_fallback"), "(question)")
    user_answered = _prompt_text(prompt_map, ("empty", "user_answered"), "User answered:")
    if answers:
        prompts_by_id: dict[str, str] = {}
        for q in ask_user_payload.get("questions") or []:
            if isinstance(q, dict):
                qid = str(q.get("id") or "")
                prompts_by_id[qid] = str(q.get("prompt") or qid)
        lines = [user_answered]
        for entry in answers:
            qid = entry.get("questionId", "")
            prompt = prompts_by_id.get(qid) or qid or question_fallback
            value = (entry.get("text") or "").strip() or skipped
            lines.append(f"- {prompt}\n  -> {value}")
        return "\n".join(lines)
    flat = (text or "").strip() or empty
    return f"{user_answered} {flat}"


def _merge_prompt_packs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Overlay *override* onto *base*, one nesting level at a time.

    Recursive because a pack's sections are dicts (``loop``, ``notices``): a
    loop that restates ``loop.system`` must not thereby drop ``loop.user`` and
    every notice its engine still emits.
    """
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_prompt_packs(current, value)
        else:
            merged[key] = value
    return merged


def _flatten_ask_user_summary(ask_user_payload: dict[str, Any]) -> str:
    questions = ask_user_payload.get("questions") or []
    if isinstance(questions, list) and questions:
        prompts = [str(q.get("prompt") or "") for q in questions if isinstance(q, dict)]
        prompts = [p for p in prompts if p]
        if prompts:
            return " | ".join(prompts)
    return str(ask_user_payload.get("question") or "")


class AgenticLoopPipeline:
    """Run one turn as a single exploring agent loop.

    Subclass to build a loop that is not chat: point the three profile
    attributes below at your own prompt pack and assembler. Everything else —
    the tool surface, dispatch, budgets, capability hooks — is inherited as-is.
    """

    #: Prompt pack this loop reads its copy from, resolved by the prompt
    #: manager as ``<module>/<agent>`` per language.
    prompt_module: str = "chat"
    prompt_agent: str = "agentic_chat"
    #: Optional pack loaded *underneath* the one above, key by key. Most of a
    #: pack is engine copy — tool-call labels, retry notices, the snip marker —
    #: which belongs to the loop machinery rather than to any one loop. A
    #: specialised pack states only what makes it that loop and inherits the
    #: rest from here, so a new notice added to the engine reaches every loop
    #: instead of silently falling back to an English default in all but one.
    prompt_base_module: str | None = None
    prompt_base_agent: str | None = None
    #: Assembler that turns the turn's fragments into the system prompt. The
    #: base one describes chat; a loop with its own protocol supplies its own
    #: (see :meth:`LoopPromptAssembler.foundation_blocks`).
    prompt_assembler_class: type[LoopPromptAssembler] = LoopPromptAssembler
    #: Namespace for the turn's on-disk scratch directory. Deliberately shared
    #: with chat across every loop: ``PathService.is_public_output_path`` keys
    #: the ``/files/outputs`` download route off it, so a per-loop namespace
    #: would make generated files unreachable rather than merely tidier.
    workspace_namespace: str = "chat"

    def __init__(
        self,
        language: str = "en",
        *,
        max_rounds: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        initial_tool_choice: str | None = None,
        event_source: str = "chat",
        event_stage: str = "responding",
        emit_result: bool = True,
    ) -> None:
        self.language = "zh" if language.lower().startswith("zh") else "en"
        self.llm_config = get_llm_config()
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        self.model = getattr(self.llm_config, "model", None)
        self.api_key = getattr(self.llm_config, "api_key", None)
        self.base_url = getattr(self.llm_config, "base_url", None)
        self.api_version = getattr(self.llm_config, "api_version", None)
        self.extra_headers = getattr(self.llm_config, "extra_headers", None) or {}
        self.reasoning_effort = getattr(self.llm_config, "reasoning_effort", None)
        # Process-wide registry. Stays the base for the whole turn; the
        # per-turn scoped view lives on ``_tool_view`` (see ``tool_lookup``).
        self.registry: ToolLookup = get_tool_registry()
        self._usage = UsageTracker(model=self.model)
        self._tool_view: ProviderToolView | None = None
        self._deferred_loader: DeferredToolLoader | None = None
        self._deferred_pool: list[Any] = []
        self._exec_enabled = False
        self._kb_manifests: list[KbManifest] = []
        # A selected capability may require one specific tool on the first
        # internal loop round. Later rounds return to model-directed selection.
        self.initial_tool_choice = (initial_tool_choice or "").strip() or None
        # The blocks the turn's system prompt was rendered from, kept for the
        # context-budget breakdown (see ``measure_context_budget``).
        self._last_prompt_blocks: list[PromptBlock] = []
        # The loop engine is capability-neutral. Chat keeps these defaults;
        # capabilities such as visualize can reuse the exact loop while owning
        # their stream namespace and final result envelope.
        self.event_source = str(event_source or "chat")
        self.event_stage = str(event_stage or "responding")
        self.emit_result = bool(emit_result)
        self.last_result: dict[str, Any] | None = None

        try:
            chat_cfg = get_chat_params()
        except Exception as exc:
            logger.warning("Failed to load chat params, using defaults: %s", exc)
            chat_cfg = {}
        try:
            self._chat_temperature = float(chat_cfg.get("temperature", 0.2))
        except (TypeError, ValueError):
            self._chat_temperature = 0.2
        self._max_rounds = _read_int(chat_cfg, key="max_rounds", default=DEFAULT_MAX_ROUNDS)
        self._exploring_max_tokens = _read_int(
            chat_cfg.get("exploring"), key="max_tokens", default=1600
        )
        self._respond_max_tokens = _read_int(
            chat_cfg.get("responding"), key="max_tokens", default=8000
        )
        # Per-capability overrides (e.g. deep solve forwards its own round
        # budget / temperature / answer-token cap, read from the solve
        # settings). Chat itself passes none and keeps the chat_cfg values.
        if max_rounds is not None:
            self._max_rounds = max(1, int(max_rounds))
        if temperature is not None:
            self._chat_temperature = float(temperature)
        if max_tokens is not None:
            self._respond_max_tokens = max(256, int(max_tokens))

        self._prompts: dict[str, Any] = self._load_prompt_pack()
        self._prompt_assembler = self.prompt_assembler_class(
            prompts=self._prompts,
            language=self.language,
        )
        self._client_config = LLMClientConfig(
            binding=self.binding,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            extra_headers=self.extra_headers or None,
            reasoning_effort=self.reasoning_effort,
            wire_api=getattr(self.llm_config, "wire_api", None) or "auto",
            api_format=getattr(self.llm_config, "api_format", None) or "auto",
        )

    def _load_prompt_pack(self) -> dict[str, Any]:
        """This loop's copy, with :attr:`prompt_base_module` merged underneath."""
        pack = self._read_prompt_pack(self.prompt_module, self.prompt_agent)
        if not self.prompt_base_module or not self.prompt_base_agent:
            return pack
        base = self._read_prompt_pack(self.prompt_base_module, self.prompt_base_agent)
        return _merge_prompt_packs(base, pack)

    def _read_prompt_pack(self, module_name: str, agent_name: str) -> dict[str, Any]:
        try:
            return (
                get_prompt_manager().load_prompts(
                    module_name=module_name,
                    agent_name=agent_name,
                    language=self.language,
                )
                or {}
            )
        except Exception as exc:
            logger.warning("Failed to load %s/%s prompts: %s", module_name, agent_name, exc)
            return {}

    @property
    def usage(self) -> UsageTracker:
        return self._usage

    @property
    def tool_lookup(self) -> ToolLookup:
        """Registry to use for this turn.

        The scoped view once ``_prepare_deferred_tools`` has resolved it —
        which is what refuses provider tools the caller is not authorised for
        at dispatch time — and the process registry before that.

        ``getattr`` because tests construct partially-initialised pipelines
        via ``__new__`` (the same reason the mount flags read that way).
        """
        view = getattr(self, "_tool_view", None)
        return view.registry if view is not None else self.registry

    @property
    def max_rounds(self) -> int:
        return max(1, self._max_rounds)

    def effective_max_rounds(self, context: UnifiedContext) -> int:
        """Round budget for this turn, lifted to satisfy any capability minimum.

        A capability that needs guaranteed loop headroom — the subagent
        capability, which must allow its full consult budget plus a finishing
        round — sets ``context.runtime.min_loop_rounds``; the loop honours
        the larger of that and the configured budget. A generic seam (like
        solve's ``solve_max_replans``) so the loop stays capability-agnostic.
        """
        try:
            floor = int(context.runtime.min_loop_rounds or 0)
        except (TypeError, ValueError):
            floor = 0
        return max(self.max_rounds, floor)

    @property
    def exploring_max_tokens(self) -> int:
        return max(128, self._exploring_max_tokens)

    @property
    def respond_max_tokens(self) -> int:
        return max(256, self._respond_max_tokens)

    @property
    def loop_max_tokens(self) -> int:
        """Single per-round token budget for the merged loop.

        The loop has no separate exploring/respond split, so every round —
        including the round that writes the final answer — uses one budget.
        It must be large enough for a full answer; the responding budget is
        that ceiling (tool-only rounds rarely approach it).
        """
        return self.respond_max_tokens

    async def run(self, context: UnifiedContext, stream: StreamBus) -> dict[str, Any]:
        if context.runtime.workspace is None:
            from deeptutor.services.workspace import get_content_workspace_service

            context.runtime.workspace = get_content_workspace_service().create_runtime_context(
                capability=context.active_capability or self.workspace_namespace,
                session_id=context.session_id or "direct",
                turn_id=context.runtime.turn_id or self._workspace_key(context),
            )
        await self._prepare_deferred_tools(context)
        await self._prepare_kb_manifests(context)
        self._exec_enabled = await self._exec_allowed(context)
        enabled_tools = self._compose_enabled_tools(context)
        use_native_tools = bool(enabled_tools) and self._can_use_native_tool_calling()
        tool_schemas = (
            self._build_llm_tool_schemas(enabled_tools, context) if use_native_tools else None
        )
        if tool_schemas is not None and self._tool_view is not None:
            self._tool_view.attach(tool_schemas)

        loop = AgentLoop(
            pipeline=self,
            context=context,
            stream=stream,
            client=self._build_openai_client(),
            enabled_tools=enabled_tools if use_native_tools else [],
            tool_schemas=tool_schemas,
        )
        self.last_result = await loop.run()
        return self.last_result

    # ---- prompt assembly -------------------------------------------------

    def _build_system_prompt(
        self,
        enabled_tools: list[str],
        context: UnifiedContext,
        *,
        include_tool_manifest: bool = True,
    ) -> str:
        # Assemble once, then render: the context-budget breakdown is measured
        # from these very blocks, so a second ``blocks()`` call could drift from
        # the prompt actually sent.
        self._last_prompt_blocks = self._prompt_assembler.blocks(
            context=context,
            tool_manifest=self._tool_manifest(enabled_tools),
            kb_note=self._kb_system_note(context),
            deferred_tools_manifest=(
                self._deferred_tools_manifest() if include_tool_manifest else ""
            ),
            notebook_manifest=self._build_notebook_manifest(),
            workspace_note=self._workspace_system_note(context),
            capability_blocks=self._capability_system_blocks(context),
            include_tool_manifest=include_tool_manifest,
        )
        return self._prompt_assembler.render(self._last_prompt_blocks)

    def _build_loop_messages(
        self,
        *,
        context: UnifiedContext,
        enabled_tools: list[str],
        kb_seed: str = "",
        include_tool_manifest: bool = True,
    ) -> list[dict[str, Any]]:
        """Build the turn's ONE conversation.

        The loop appends each round (assistant + ``role=tool`` results) to
        this list, so the system prompt stays byte-stable for the whole turn
        and the KB cache prefix is preserved. The KB seed rides inside the
        trailing user message, not the system prompt.
        """
        system_prompt = self._build_system_prompt(
            enabled_tools,
            context,
            include_tool_manifest=include_tool_manifest,
        )
        user_content = self._prompt_assembler.user_message(
            context=context,
            kb_seed=kb_seed,
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for item in context.conversation_history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, (str, list)):
                message: dict[str, Any] = {"role": role, "content": content}
                if role == "assistant" and isinstance(item.get("_provider_response_state"), dict):
                    message["_provider_response_state"] = item["_provider_response_state"]
                messages.append(message)
            elif role == "system" and isinstance(content, str) and content.strip():
                # ContextBuilder emits the compressed-history summary as a
                # leading system message; deliver it right after the system
                # prompt so compacted turns stay visible to the model.
                header = _prompt_text(
                    self._prompts,
                    ("notices", "conversation_summary_header"),
                    "[Conversation summary]",
                )
                messages.append({"role": "system", "content": f"{header}\n{content}"})
        messages.append({"role": "user", "content": user_content})
        return self._prepare_messages_with_attachments(messages, context)

    def _finish_exhausted_instruction(self) -> str:
        return self._prompt_assembler.finish_exhausted_instruction()

    def _settle_exhausted_instruction(self) -> str:
        return self._prompt_assembler.settle_exhausted_instruction()

    def _tool_manifest(self, enabled_tools: list[str]) -> str:
        names = list(enabled_tools)
        if self._deferred_loader is not None:
            for name in sorted(self._deferred_loader.loaded_names):
                if name not in names:
                    names.append(name)
        try:
            return self.tool_lookup.build_prompt_text(
                names,
                format="list_with_usage",
                language=self.language,
            )
        except TypeError:
            return self.tool_lookup.build_prompt_text(names)
        except Exception:
            logger.warning("failed to build tool prompt text", exc_info=True)
            return ""

    def _tool_result_snip_marker(self) -> str:
        return self._t(
            "notices.tool_result_snipped",
            default=(
                "[earlier tool result snipped to stay within context window; "
                "call the same tool again if the content is still needed]"
            ),
        )

    def _prepare_messages_with_attachments(
        self,
        messages: list[dict[str, Any]],
        context: UnifiedContext,
    ) -> list[dict[str, Any]]:
        return prepare_multimodal_messages(
            messages,
            context.attachments,
            binding=self.binding,
            model=self.model,
        ).messages

    # ---- deferred tools / tool composition ------------------------------

    @staticmethod
    def _is_partner_turn(context: UnifiedContext) -> bool:
        """Whether this turn runs under a partner's synthetic scope.

        A partner turn executes as a synthetic non-admin user but acts as the
        admin owner's extension. Authorization for these turns travels through
        context metadata (the owner-scoped ``mcp_tools_filter`` / exec gate),
        not the synthetic user's grant file — so callers must bypass real-user
        grant resolution and defer to that metadata whitelist instead.
        """
        return str((context.metadata or {}).get("source") or "") == "partner"

    async def _prepare_deferred_tools(self, context: UnifiedContext) -> None:
        """Resolve this turn's external-provider (MCP / CLI) tool surface.

        The policy — grant intersection, resource-derived grants, filtering,
        the progressive-disclosure loader, the manifest — lives in
        ``runtime.providers``. All the pipeline owns is translating the turn's
        context into a :class:`ToolScope`.
        """
        self._pageindex_providers: set[str] = set()
        self._pageindex_cloud_instructions = ""
        self._pageindex_oss_instructions = ""
        pageindex_tools: list[Any] = []
        try:
            for kb, bundle in await self._pageindex_sdk_tool_bundles(context):
                self._pageindex_providers.add(bundle.provider)
                if bundle.provider == "pageindex-oss":
                    self._pageindex_oss_instructions = bundle.instructions
                else:
                    self._pageindex_cloud_instructions = bundle.instructions
                pageindex_tools.extend(bundle.tools)
        except Exception:
            logger.warning("PageIndex SDK tool preparation failed", exc_info=True)
        try:
            view = await build_tool_view(
                base_registry=self.registry,
                scope=self._tool_scope(context),
                language=self.language,
                refusal_message=self._t(
                    "notices.tool_not_available",
                    default=(
                        "This tool is not available in this conversation. Only "
                        "the tools listed in the prompt can be called."
                    ),
                ),
                overlay_tools=pageindex_tools,
                preloaded_names=[tool.name for tool in pageindex_tools],
            )
        except Exception:
            # ``build_tool_view`` is contractually non-raising; this is defence
            # in depth because it is the turn's first await — a failure here
            # would kill the turn before a single stream event is emitted.
            logger.warning("deferred-tool preparation failed", exc_info=True)
            view = ProviderToolView.empty(self.registry)
        self._tool_view = view
        self._deferred_loader = view.loader
        # Kept as a plain list: the context-budget chip counts the provider
        # tools whose schemas never entered the window.
        self._deferred_pool = list(view.pool)

    def _tool_scope(self, context: UnifiedContext) -> ToolScope:
        """Per-turn policy inputs for the provider layer."""
        raw_filter = context.metadata.get("mcp_tools_filter")
        return ToolScope(
            owner_id=self._current_owner_id(),
            is_partner=self._is_partner_turn(context),
            session_id=context.session_id,
            caller_whitelist=(
                frozenset(str(name) for name in raw_filter)
                if isinstance(raw_filter, list)
                else None
            ),
            exclusive_capability=self._exclusive_capability_active(context),
        )

    async def _pageindex_sdk_tool_bundles(self, context: UnifiedContext):
        from deeptutor.multi_user.knowledge_access import resolve_kb
        from deeptutor.services.rag.factory import PAGEINDEX_OSS_PROVIDER, PAGEINDEX_PROVIDER
        from deeptutor.services.rag.pipelines.pageindex.tools import build_sdk_tool_bundle
        from deeptutor.services.rag.provider_binding import resolve_bound_provider

        bundles = []
        seen_providers: set[str] = set()
        for kb in self._selected_kbs(context):
            resource = resolve_kb(kb, require_write=False)
            base_dir = str(resource.base_dir)
            provider = resolve_bound_provider(base_dir, resource.name)
            if provider not in {PAGEINDEX_PROVIDER, PAGEINDEX_OSS_PROVIDER}:
                continue
            # Cloud tools are account-wide and OSS selection already permits at
            # most one local library, so one SDK bundle per provider is enough.
            if provider in seen_providers:
                continue
            bundles.append(
                (
                    kb,
                    await build_sdk_tool_bundle(
                        resource.name,
                        base_dir,
                        provider=provider,
                    ),
                )
            )
            seen_providers.add(provider)
        return bundles

    def _deferred_tools_manifest(self) -> str:
        view = getattr(self, "_tool_view", None)
        return view.manifest if view is not None else ""

    async def _exec_allowed(self, context: UnifiedContext) -> bool:
        try:
            from deeptutor.services.sandbox import IsolationLevel, get_sandbox_service

            # A partner turn runs as a synthetic non-admin user but IS the admin
            # owner's extension (partners are anchored to the admin workspace), so
            # exec follows the owner's authority — not the partner's "user" role.
            # The owner still gates exec per-partner via the builtin-tool whitelist.
            is_partner = self._is_partner_turn(context)

            level = await get_sandbox_service().isolation_level()
            if level is IsolationLevel.SYSTEM:
                # Admin can switch exec off per user (grant v2). ``None``
                # follows the policy: SYSTEM isolation serves everyone.
                from deeptutor.multi_user.tool_access import exec_override

                return exec_override() is not False
            if level is IsolationLevel.APPLICATION:
                if is_partner:
                    return True
                try:
                    from deeptutor.multi_user.context import get_current_user

                    return bool(get_current_user().is_admin)
                except Exception:
                    # Single-user local runtime: APPLICATION isolation is the
                    # same explicit opt-in posture TutorBot uses for local dev.
                    return True
            return False
        except Exception:
            logger.warning("exec policy gate failed; disabling exec", exc_info=True)
            return False

    def _compose_enabled_tools(self, context: UnifiedContext) -> list[str]:
        is_partner = self._is_partner_turn(context)
        composed = compose_enabled_tools(
            registry=self.tool_lookup,
            requested_tools=context.enabled_tools,
            optional_whitelist=LOOP_OPTIONAL_TOOLS,
            mount_flags=ToolMountFlags(
                # PageIndex KBs are read via the preloaded MCP tools, not rag —
                # a conversation with only PageIndex KBs doesn't mount rag at all.
                # Excludes KBs owned by an exclusive capability (an Obsidian vault
                # is read via its own tools, never rag) so a pure-vault turn still
                # doesn't mount rag, while co-selected LlamaIndex KBs do (#650).
                has_kb=bool(self._coexisting_rag_kbs(context)),
                # read_source is owned by the explore_context pre-pass (it runs
                # the investigation over attached sources), not the answer loop.
                # Keep it off the answer surface even when sources are present.
                has_sources=False,
                has_memory=user_has_memory(),
                has_notebooks=user_has_notebooks(),
                has_question_bank=user_has_question_bank(),
                has_skills=bool(context.skills_manifest),
                has_deferred_tools=getattr(self, "_deferred_loader", None) is not None,
                has_exec=getattr(self, "_exec_enabled", False),
                # Reaching a mastery topic is a chat-wide affordance, not part
                # of any capability: the learner names what they are studying
                # and gets a card that opens the real study screen. Only the
                # atlas listing is withheld from a mastery turn, which reads
                # its own through ``mastery_paths``.
                has_mastery_nav=self._mastery_nav_available(context),
                has_mastery_topics=(
                    self._mastery_nav_available(context)
                    and not context.metadata.get("mastery_mode")
                ),
            ),
            capability_owned=self._capability_owned_tools(context),
            exclusive=self._exclusive_capability_active(context),
            builtin_whitelist=(
                set(context.allowed_builtin_tools)
                if context.allowed_builtin_tools is not None
                else None
            ),
            # Partners get the partner_* memory/history tools force-mounted and
            # chat's read_memory/write_memory suppressed — the split-memory model
            # (own workspace writable, owner's memory read-only) lives in those
            # tools, not in chat's.
            forced=PARTNER_BUILTIN_TOOL_NAMES if is_partner else (),
            suppressed=_PARTNER_SUPPRESSED_TOOLS if is_partner else (),
        )
        composed = drop_unconfigured_generation_tools(composed)
        lookup_get = getattr(self.tool_lookup, "get", None)
        if callable(lookup_get) and lookup_get("workspace_export") is not None:
            composed.append("workspace_export")
        return list(dict.fromkeys(composed))

    def _mastery_nav_available(self, context: UnifiedContext) -> bool:
        """Whether this turn should be able to point at a mastery topic.

        Resolved once per turn and cached on the context: the gate opens a
        SQLite connection, and the two flags derived from it are read
        independently.
        """
        cached = context.metadata.get("_mastery_nav_available")
        if isinstance(cached, bool):
            return cached
        available = user_has_mastery_topics()
        context.metadata["_mastery_nav_available"] = available
        return available

    def _active_loop_capabilities(self, context: UnifiedContext) -> tuple[LoopExtension, ...]:
        return active_loop_capabilities(context)

    @staticmethod
    def _exclusive_capability_active(context: UnifiedContext) -> bool:
        """True when a knowledge capability owns the turn (replaces the surface).

        The capability's own tools replace chat's built-ins. rag scaffolding
        (mount / KB seed / kb note) is still provided for any co-selected KBs the
        capability does NOT own — see ``_coexisting_rag_kbs`` (issue #650).
        """
        return any_exclusive_capability_active(context)

    def _capability_owned_tools(self, context: UnifiedContext) -> tuple[str, ...]:
        """The active capabilities' own tools — added on top of chat's full surface."""
        names: list[str] = []
        for cap in self._active_loop_capabilities(context):
            names.extend(cap.owned_tools)
        return tuple(names)

    def _capability_rebinding_tools(self, context: UnifiedContext) -> frozenset[str]:
        """Tools that repoint the rest of the round at a different target.

        Optional, like ``pre_loop``: a capability declares the tools whose
        effect the round's other calls must see (``mastery_switch`` moves the
        turn onto another path), and the dispatcher runs them first and
        re-binds the rest against the result.
        """
        names: list[str] = []
        for cap in self._active_loop_capabilities(context):
            names.extend(getattr(cap, "rebinding_tools", ()) or ())
        return frozenset(names)

    def _capability_system_blocks(self, context: UnifiedContext):
        blocks = []
        for cap in self._active_loop_capabilities(context):
            block = cap.system_block(
                context,
                language=self.language,
                prompts=self._prompts,
            )
            if block is not None:
                blocks.append(block)
        return blocks

    def _capability_pre_loop_seed(self, context: UnifiedContext) -> str:
        seeds = [
            seed.strip()
            for cap in self._active_loop_capabilities(context)
            if (seed := cap.pre_loop_seed(context))
        ]
        return "\n\n".join(seed for seed in seeds if seed)

    def _capability_finish_instruction(self, context: UnifiedContext, final_text: str) -> str:
        """Let an active capability reject a narrow tool-less finish once.

        This is a protocol guard, not a content generator: capabilities return
        a short instruction only when their own state proves that required tool
        work remains. A guard failure must not sink the learner's answer.
        """
        for cap in self._active_loop_capabilities(context):
            hook = getattr(cap, "finish_instruction", None)
            if not callable(hook):
                continue
            try:
                instruction = hook(context, final_text)
            except Exception:
                logger.warning(
                    "finish guard failed for capability %s",
                    getattr(cap, "name", "?"),
                    exc_info=True,
                )
                continue
            content = str(instruction or "").strip()
            if content:
                return content
        return ""

    def _capability_tool_round_output_policy(
        self,
        context: UnifiedContext,
        final_text: str,
        tool_names: tuple[str, ...],
    ) -> str:
        """Let a finish-guard capability classify a tool round's prose."""
        for cap in self._active_loop_capabilities(context):
            hook = getattr(cap, "tool_round_output_policy", None)
            if not callable(hook):
                continue
            try:
                policy = str(hook(context, final_text, tool_names) or "").strip()
            except Exception:
                logger.warning(
                    "tool-round policy failed for capability %s",
                    getattr(cap, "name", "?"),
                    exc_info=True,
                )
                continue
            if policy in {"publish", "discard"}:
                return policy
        return ""

    def _capability_final_text_override(
        self,
        context: UnifiedContext,
        final_text: str,
    ) -> str | None:
        """Return a capability-owned canonical answer after private protocol work."""
        for cap in self._active_loop_capabilities(context):
            hook = getattr(cap, "final_text_override", None)
            if not callable(hook):
                continue
            try:
                override = hook(context, final_text)
            except Exception:
                logger.warning(
                    "final-text override failed for capability %s",
                    getattr(cap, "name", "?"),
                    exc_info=True,
                )
                continue
            if override is not None:
                return str(override).strip()
        return None

    def _has_capability_finish_guard(self, context: UnifiedContext) -> bool:
        """Whether a capability may need to inspect a tool-less finish first."""
        return any(
            callable(getattr(cap, "finish_instruction", None))
            for cap in self._active_loop_capabilities(context)
        )

    def _capability_buffers_visible_output(self, context: UnifiedContext) -> bool:
        """Whether an active capability must see a round before the user does.

        Buffering a round costs the turn its streaming: nothing reaches the
        reader until the round is complete and its protocol has ruled. That is
        the right trade only for a capability whose rounds are *protocol
        artefacts* — a visualization payload, a private invoke/no-invoke
        decision — where the prose either never belongs to the reader or is
        republished verbatim by ``final_text_override`` and would otherwise
        appear twice.

        It is the wrong trade for a capability that merely guards how a turn
        may *end*. Mastery and Partner authoring stream ordinary teaching prose
        and reject a finish only in the uncommon case (a question that was
        never posed, a draft that was never created). Buffering every round of
        theirs to catch that case removed streaming from those surfaces
        entirely; a rejected finish is instead withdrawn after the fact by the
        round's ``narration`` marker, which is how the reader's answer text is
        reconciled anyway.

        Declared explicitly rather than inferred, because the two groups are
        indistinguishable from their hooks: both define ``finish_instruction``.
        """
        return any(
            bool(getattr(cap, "buffers_visible_output", False))
            for cap in self._active_loop_capabilities(context)
        )

    async def _capability_pre_loop_briefings(
        self,
        context: UnifiedContext,
        stream: StreamBus,
    ) -> str:
        """Run each active capability's optional async ``pre_loop`` hook and
        join their returned blocks into one seed fragment.

        The hook is optional (read via ``getattr`` so plain capabilities are
        unaffected) and runs once before the answer loop's first LLM call —
        see the ``pre_loop`` note on :class:`LoopExtension`. Failures are
        swallowed: a pre-pass is best-effort grounding and must never sink the
        turn.
        """
        blocks: list[str] = []
        for cap in self._active_loop_capabilities(context):
            hook = getattr(cap, "pre_loop", None)
            if not callable(hook):
                continue
            try:
                block = await hook(context, stream, usage=self._usage)
            except Exception:
                logger.warning(
                    "pre_loop hook failed for capability %s",
                    getattr(cap, "name", "?"),
                    exc_info=True,
                )
                continue
            content = (getattr(block, "content", "") or "").strip()
            if content:
                blocks.append(content)
        return "\n\n".join(blocks)

    def _build_llm_tool_schemas(
        self,
        enabled_tools: list[str],
        context: UnifiedContext,
    ) -> list[dict[str, Any]]:
        schemas = self.tool_lookup.build_openai_schemas(enabled_tools)
        kb_choices = self._coexisting_rag_kbs(context)
        notebook_choices = self._notebook_choices()
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            if not isinstance(function, dict):
                continue
            parameters = function.get("parameters")
            if not isinstance(parameters, dict):
                continue
            properties = parameters.get("properties") or {}
            if function.get("name") == "rag" and isinstance(properties, dict):
                if isinstance(properties.get("query"), dict):
                    properties["query"].setdefault("minLength", 1)
                if isinstance(properties.get("kb_name"), dict):
                    properties["kb_name"]["enum"] = kb_choices
            if function.get("name") == "geogebra_analysis" and isinstance(properties, dict):
                properties.pop("image_base64", None)
                required = parameters.get("required")
                if isinstance(required, list):
                    parameters["required"] = [n for n in required if n != "image_base64"]
            if (
                function.get("name") in {"list_notebook", "write_note"}
                and isinstance(properties, dict)
                and notebook_choices
                and isinstance(properties.get("notebook_id"), dict)
            ):
                nb_schema = properties["notebook_id"]
                nb_schema["enum"] = [choice["id"] for choice in notebook_choices]
                rendered = "; ".join(f"{c['id']} = {c['name']}" for c in notebook_choices)
                nb_schema["description"] = (
                    f"{nb_schema.get('description', '').rstrip(' .')}. Available: {rendered}."
                )
            parameters["additionalProperties"] = False
        return schemas

    # ---- notebook / context helpers -------------------------------------

    def _build_notebook_manifest(self) -> str:
        choices = self._notebook_choices_full()
        if not choices:
            return ""
        capped = choices[:30]
        lines = ["[用户的笔记本列表]" if self.language == "zh" else "[User's notebooks]"]
        for entry in capped:
            nid = entry.get("id", "")
            name = entry.get("name", nid)
            count = entry.get("record_count", 0)
            lines.append(f"- `{nid}` - {name} ({count} records)")
        if len(choices) > len(capped):
            lines.append(
                f"... (+{len(choices) - len(capped)} more; call `list_notebook` to see the rest)"
            )
        return "\n".join(lines)

    @staticmethod
    def _notebook_choices_full() -> list[dict[str, Any]]:
        try:
            from deeptutor.services.notebook import get_notebook_manager

            notebooks = get_notebook_manager().list_notebooks() or []
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        for nb in notebooks:
            nid = str(nb.get("id") or "").strip()
            if not nid:
                continue
            name = str(nb.get("name") or nb.get("title") or nid).strip() or nid
            try:
                count = int(nb.get("record_count") or 0)
            except (TypeError, ValueError):
                count = 0
            rows.append({"id": nid, "name": name, "record_count": count})
        return rows

    @staticmethod
    def _notebook_choices() -> list[dict[str, str]]:
        return [
            {"id": str(row["id"]), "name": str(row["name"])}
            for row in AgenticLoopPipeline._notebook_choices_full()
        ]

    # ---- tool execution --------------------------------------------------

    async def _execute_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        stream: StreamBus | None = None,
        retrieve_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from deeptutor.runtime.agentic import execute_tool_call

        stream = stream or StreamBus()
        return await execute_tool_call(
            registry=self.tool_lookup,
            tool_name=tool_name,
            tool_args=tool_args,
            stream=stream,
            source=self.event_source,
            stage=self.event_stage,
            retrieve_meta=retrieve_meta,
            empty_tool_result_message=self._t("notices.empty_tool_result"),
            start_retrieval_message=self._t(
                "notices.start_retrieval", default="Starting retrieval"
            ),
            retrieve_label=self._t("labels.retrieve", default="Retrieve"),
            unknown_error_message_factory=lambda tn: self._t(
                "notices.tool_unknown_error",
                tool=tn,
                default=f"An unknown error occurred while executing {tn}.",
            ),
        )

    async def _dispatch_tool_calls(
        self,
        *,
        tool_calls: list[dict[str, Any]],
        context: UnifiedContext,
        stream: StreamBus,
        iteration_index: int,
        stage: str = "exploring",
    ) -> DispatchOutcome:
        too_many = None
        if len(tool_calls) > MAX_PARALLEL_TOOL_CALLS:
            too_many = self._t(
                "notices.too_many_tool_calls",
                requested=len(tool_calls),
                limit=MAX_PARALLEL_TOOL_CALLS,
            )
        return await dispatch_tool_calls(
            tool_calls=tool_calls,
            context=context,
            stream=stream,
            source=self.event_source,
            stage=stage,
            iteration_index=iteration_index,
            registry=self.tool_lookup,
            kwarg_augmenter=self._augment_tool_kwargs,
            rebinding_tools=self._capability_rebinding_tools(context),
            retrieve_meta_factory=lambda meta, tn, ta: self._retrieve_trace_metadata(
                meta, context=context, tool_name=tn, tool_args=ta
            ),
            tool_call_label=self._t("labels.tool_call", default="Tool call"),
            retrieve_label=self._t("labels.retrieve", default="Retrieve"),
            empty_tool_result_message=self._t("notices.empty_tool_result"),
            start_retrieval_message=self._t(
                "notices.start_retrieval", default="Starting retrieval"
            ),
            too_many_tool_calls_message=too_many,
            unknown_error_message_factory=lambda tn: self._t(
                "notices.tool_unknown_error",
                tool=tn,
                default=f"An unknown error occurred while executing {tn}.",
            ),
            trace_id_prefix=f"{self.event_source}-loop",
        )

    async def _notify_pause_hooks(
        self,
        context: UnifiedContext,
        hook_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Tell the active loop capabilities about an ``ask_user`` boundary.

        These hooks record side state (a mastery path commits the question's
        awaiting/answered transitions here) — they do not produce the reply.
        So one failing is a bookkeeping problem, not a reason to throw away a
        turn the learner is in the middle of: log it and keep the conversation
        alive, rather than surfacing a traceback where a question should be.
        """
        for capability in self._active_loop_capabilities(context):
            hook = getattr(capability, hook_name, None)
            if not callable(hook):
                continue
            try:
                await hook(*args, **kwargs)
            except Exception:
                logger.warning(
                    "Loop capability %s failed in %s",
                    getattr(capability, "name", type(capability).__name__),
                    hook_name,
                    exc_info=True,
                )

    async def _await_user_reply_and_resolve(
        self,
        *,
        context: UnifiedContext,
        stream: StreamBus,
        dispatch: DispatchOutcome,
    ) -> bool:
        ask_user = (dispatch.pause_payload or {}).get("ask_user") or {}
        await self._notify_pause_hooks(context, "on_user_pause", context, ask_user)
        waiter = context.runtime.wait_for_user_reply
        if not callable(waiter):
            await self._emit_terminator_final_response(
                stream,
                {
                    "tool_name": (dispatch.pause_payload or {}).get("tool_name", "ask_user"),
                    "content": _flatten_ask_user_summary(ask_user),
                    "metadata": {"ask_user": ask_user},
                },
            )
            return False

        raw_reply = await waiter()
        if raw_reply is None:
            return False
        reply_text, answers = _normalise_user_reply(raw_reply)
        await self._notify_pause_hooks(
            context,
            "on_user_resume",
            context,
            ask_user,
            reply_text=reply_text,
            answers=answers,
        )
        # The reply happened, so it belongs in the transcript whether or not the
        # loop goes on — emit the trace before deciding to stop.
        meta: dict[str, Any] = {
            "trace_kind": "user_reply",
            "ask_user_resolved": True,
            "ask_user_tool_call_id": dispatch.pause_tool_call_id,
            "reply_preview": (reply_text or "")[:200],
        }
        if answers:
            meta["answers"] = list(answers)
        await stream.progress(
            "",
            source=self.event_source,
            stage=self.event_stage,
            metadata=meta,
        )

        # Neutral stop signal for loop plugins (e.g. a crisis redirect): the
        # outer capability owns the final message, so skip further LLM rounds.
        # Everything below only exists to feed the answer back to the model.
        if context.interaction.end_loop or context.metadata.get(END_LOOP):
            return False

        workspace_export_message = await self._resolve_workspace_export(
            context=context,
            dispatch=dispatch,
            reply_text=reply_text,
            answers=answers,
        )

        body_text = _format_user_reply_body(
            reply_text,
            answers,
            ask_user,
            prompts=self._prompts,
        )
        continue_directive = self._t(
            "notices.ask_user_resolved_directive",
            default=(
                "[ask_user resolved. Continue the user's original request using these answers. "
                "Do not stop with an acknowledgement.]"
            ),
        )
        directive = f"{body_text}\n\n{continue_directive}"
        if workspace_export_message:
            directive = f"{workspace_export_message}\n\n{directive}"
        for tm in dispatch.tool_messages:
            if tm.get("tool_call_id") == dispatch.pause_tool_call_id:
                tm["content"] = directive
                break
        return True

    @staticmethod
    async def _resolve_workspace_export(
        *,
        context: UnifiedContext,
        dispatch: DispatchOutcome,
        reply_text: str,
        answers: list[dict[str, str]] | None,
    ) -> str:
        """Execute an approved export exactly once at the pause boundary."""
        if (dispatch.pause_payload or {}).get("tool_name") != "workspace_export":
            return ""
        call_id = dispatch.pause_tool_call_id or ""
        metadata = dispatch.tool_metadata_by_id.get(call_id) or {}
        request = metadata.get("workspace_export")
        if not isinstance(request, dict):
            return "[workspace export failed: authorization metadata was unavailable]"
        question_id = str(request.get("question_id") or "")
        allow_label = str(request.get("allow_label") or "")
        response_values = [reply_text]
        response_values.extend(
            str(answer.get("text") or "")
            for answer in answers or []
            if not question_id or answer.get("questionId") == question_id
        )
        approved = any(
            value.strip().casefold() == allow_label.casefold()
            for value in response_values
            if value.strip()
        )
        if not approved:
            return "[workspace export denied; no file was written]"
        workspace = context.runtime.workspace
        if workspace is None or str(request.get("workspace_id") or "") != workspace.workspace_id:
            return "[workspace export failed: the workspace binding changed]"
        try:
            from deeptutor.services.workspace import get_content_workspace_service

            service = get_content_workspace_service()
            binding = service.binding_by_id(workspace.workspace_id)
            completed = await asyncio.to_thread(
                service.export_once,
                binding,
                source_path=str(request.get("source_path") or ""),
                destination_path=str(request.get("destination_path") or ""),
                overwrite=bool(request.get("overwrite", False)),
                expected_sha256=str(request.get("sha256") or ""),
            )
        except (OSError, ValueError) as exc:
            return f"[workspace export failed: {exc}]"
        return (
            "[workspace export authorized once and completed: "
            f"{completed['source_path']} -> {completed['destination_path']}]"
        )

    def _augment_tool_kwargs(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        runtime_workspace = context.runtime.workspace
        if runtime_workspace is not None:
            task_dir = None
        else:
            # Compatibility for tests and third-party direct callers that
            # invoke the kwargs seam without first calling run(). Real turns
            # are initialized at run() and never enter this branch.
            from deeptutor.services.path_service import get_path_service

            workspace_key = self._workspace_key(context)
            task_dir = (
                get_path_service().get_task_workspace(self.workspace_namespace, workspace_key)
                if workspace_key
                else None
            )
        kwargs = bind_workspace_tool_runtime(
            tool_name,
            args,
            context,
            fallback_task_dir=task_dir,
            sandbox_user_id=self._current_user_id(),
        )
        task_dir = Path(runtime_workspace.output_dir) if runtime_workspace is not None else task_dir
        if tool_name == "rag":
            kwargs.setdefault("mode", "hybrid")
        elif tool_name == "kb_files":
            # The report is read by the user as much as by the model, so it is
            # written in the turn's language. Injected server-side; the tool
            # exposes no ``language`` parameter for the model to get wrong.
            kwargs["language"] = context.language or "en"
        elif tool_name == "load_tools":
            kwargs["_tool_loader"] = self._deferred_loader
        elif tool_name == "cron":
            # Owner routing is supplied server-side — the model never picks
            # where a scheduled task's output lands.
            meta = context.metadata or {}
            cron_job_id = str(meta.get("cron_job_id") or meta.get("_cron_job_id") or "")
            kwargs["_cron_in_context"] = bool(
                cron_job_id or str(meta.get("source") or "") == "cron"
            )
            if self._is_partner_turn(context):
                channel_meta = meta.get("channel_metadata")
                kwargs["_cron_owner"] = {
                    "kind": "partner",
                    "partner_id": str(meta.get("partner_id") or ""),
                    "channel": str(meta.get("channel") or ""),
                    "chat_id": str(meta.get("chat_id") or ""),
                    "session_key": str(meta.get("session_key") or ""),
                    "channel_meta": dict(channel_meta) if isinstance(channel_meta, dict) else {},
                    "language": context.language or "en",
                }
            else:
                from deeptutor.multi_user.context import get_current_user

                user = get_current_user()
                kwargs["_cron_owner"] = {
                    "kind": "chat",
                    "user_id": user.id,
                    "is_admin": user.is_admin,
                    "session_id": context.session_id,
                    "language": context.language or "en",
                }
        elif tool_name in {"reason", "brainstorm"}:
            kwargs.setdefault("context", context.user_message)
        elif tool_name == "paper_search":
            kwargs.setdefault("max_results", 3)
            kwargs.setdefault("years_limit", 3)
            kwargs.setdefault("sort_by", "relevance")
        elif tool_name == "web_search":
            kwargs.setdefault("query", context.user_message)
            if task_dir is not None:
                kwargs.setdefault("output_dir", str(task_dir / "web_search"))
        elif tool_name == "write_note":
            kwargs["conversation_history"] = list(context.conversation_history or [])
            kwargs["current_user_message"] = context.user_message or ""
        elif tool_name == "geogebra_analysis":
            first_image = next(
                (
                    att
                    for att in (context.attachments or [])
                    if getattr(att, "type", "") == "image" and getattr(att, "base64", "")
                ),
                None,
            )
            if first_image is not None:
                raw_b64 = first_image.base64
                if raw_b64.startswith("data:"):
                    kwargs["image_base64"] = raw_b64
                else:
                    mime = getattr(first_image, "mime_type", "") or "image/png"
                    kwargs["image_base64"] = f"data:{mime};base64,{raw_b64}"
            kwargs["language"] = context.language or "zh"
        for cap in self._active_loop_capabilities(context):
            kwargs = cap.augment_kwargs(tool_name, kwargs, context)
        return kwargs

    def _retrieve_trace_metadata(
        self,
        tool_meta: dict[str, Any],
        *,
        context: UnifiedContext,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        _ = context
        if tool_name == "rag":
            return derive_trace_metadata(
                tool_meta,
                label=self._t("labels.retrieve", default="Retrieve"),
                call_kind="rag_retrieval",
                trace_role="retrieve",
                trace_group="retrieve",
                query=str(tool_args.get("query", "") or ""),
            )
        # The remaining entries are pure label/call_kind customisation: every
        # tool now gets an event_sink and a call_state unconditionally
        # (``execute_tool_call``), so a long-running tool no longer has to pose
        # as a retrieval to stream its progress. What it still needs from here
        # is the call_kind the frontend renders it by.
        if tool_name in ("imagegen", "videogen"):
            return derive_trace_metadata(
                tool_meta,
                label=self._t("labels.tool_call", default="Tool call"),
                call_kind="media_generation",
                query=str(tool_args.get("prompt", "") or ""),
            )
        # consult_subagent drives a live local agent; the frontend keys its
        # in-place transcript row off this call_kind.
        if tool_name == "consult_subagent":
            return derive_trace_metadata(
                tool_meta,
                label=self._t("labels.consult_subagent", default="Consult agent"),
                call_kind="subagent_consult",
                query=str(tool_args.get("question", "") or ""),
            )
        return None

    # ---- KB seed ---------------------------------------------------------

    async def _retrieve_kb_seed_block(
        self,
        context: UnifiedContext,
        stream: StreamBus,
    ) -> str:
        # Only traditional RAG KBs are pre-seeded. PageIndex and capability-owned
        # KBs are read with their tools inside the reasoning loop.
        kbs = self._coexisting_rag_kbs(context)
        query = (context.user_message or "").strip()
        if not kbs or not query:
            return ""
        if len(kbs) > KB_SEED_MAX_KBS:
            kbs = kbs[:KB_SEED_MAX_KBS]
        results = await asyncio.gather(*(self._seed_search_one_kb(kb, query, stream) for kb in kbs))
        sections: list[str] = []
        sources: list[dict[str, Any]] = []
        for kb, result in zip(kbs, results, strict=False):
            if result is None:
                continue
            text, kb_sources = result
            sections.append(f"## {kb}\n{text}")
            sources.extend(kb_sources)
        if not sections:
            return ""
        if sources:
            await stream.sources(
                sources,
                source=self.event_source,
                stage=self.event_stage,
                metadata={"trace_kind": "sources"},
            )
        header = self._t(
            "knowledge_base_seed.header",
            default=(
                "[Knowledge Base Context]\n"
                "Passages retrieved from attached knowledge bases for the current question."
            ),
        )
        return header + "\n\n" + "\n\n".join(sections)

    async def _seed_search_one_kb(
        self,
        kb_name: str,
        query: str,
        stream: StreamBus,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        call_id = new_call_id(f"{self.event_source}-kb-seed")
        retrieve_meta = build_trace_metadata(
            call_id=call_id,
            phase=self.event_stage,
            label=self._t("labels.retrieve", default="Retrieve"),
            call_kind="rag_retrieval",
            trace_id=call_id,
            trace_role="retrieve",
            trace_group="retrieve",
            query=query,
        )
        result = await self._execute_tool_call(
            "rag",
            {"query": query, "kb_name": kb_name, "mode": "hybrid"},
            stream=stream,
            retrieve_meta=retrieve_meta,
        )
        if not result.get("success"):
            return None
        metadata = result.get("metadata") or {}
        if metadata.get("error_type") or metadata.get("needs_reindex"):
            return None
        text = str(metadata.get("content") or metadata.get("answer") or "").strip()
        if not text:
            return None
        if len(text) > KB_SEED_CHARS_PER_KB:
            text = text[:KB_SEED_CHARS_PER_KB].rstrip() + "\n...[truncated]"
        return text, list(result.get("sources") or [])

    # ---- emissions / context guard --------------------------------------

    async def _emit_final_text(
        self,
        stream: StreamBus,
        text: str,
        final_meta: dict[str, Any],
    ) -> None:
        if not text:
            return
        await stream.content(
            text,
            source=self.event_source,
            stage=self.event_stage,
            metadata=merge_trace_metadata(final_meta, {"trace_kind": "llm_output"}),
        )

    async def _emit_protocol_fallback_final_response(
        self,
        stream: StreamBus,
        content: str,
    ) -> None:
        final_meta = build_trace_metadata(
            call_id=new_call_id(f"{self.event_source}-final-response"),
            phase=self.event_stage,
            label=self._t("labels.final_response", default="Final response"),
            call_kind="llm_final_response",
            trace_id=f"{self.event_source}-final-response",
            trace_role="response",
            trace_group="stage",
            fallback=True,
        )
        await self._emit_final_text(stream, content, final_meta)

    async def _emit_terminator_final_response(
        self,
        stream: StreamBus,
        payload: dict[str, Any] | None,
    ) -> None:
        if not payload:
            return
        content = str(payload.get("content") or "").strip()
        if not content:
            return
        final_meta = build_trace_metadata(
            call_id=new_call_id(f"{self.event_source}-final-response"),
            phase=self.event_stage,
            label=self._t("labels.final_response", default="Final response"),
            call_kind="llm_final_response",
            trace_id=f"{self.event_source}-final-response",
            trace_role="response",
            trace_group="stage",
            terminator_tool=str(payload.get("tool_name") or ""),
        )
        merged: dict[str, Any] = {"trace_kind": "llm_output"}
        tool_metadata = payload.get("metadata") or {}
        if isinstance(tool_metadata, dict) and tool_metadata:
            merged["tool_metadata"] = dict(tool_metadata)
        await stream.content(
            content,
            source=self.event_source,
            stage=self.event_stage,
            metadata=merge_trace_metadata(final_meta, merged),
        )

    async def _guard_context_window(
        self,
        messages: list[dict[str, Any]],
        stream: StreamBus,
    ) -> None:
        try:
            window = resolve_effective_context_window(
                context_window=getattr(self.llm_config, "context_window", None),
                model=str(self.model or ""),
                max_tokens=getattr(self.llm_config, "max_tokens", None),
            )
        except Exception:
            return
        if not window or window <= 0:
            return
        budget = int(window * CONTEXT_WINDOW_GUARD_RATIO)
        if self._estimate_messages_tokens(messages) <= budget:
            return
        snipped = False
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            marker = self._tool_result_snip_marker()
            if msg.get("content") == marker:
                continue
            msg["content"] = marker
            snipped = True
            if self._estimate_messages_tokens(messages) <= budget:
                break
        if snipped:
            await stream.progress(
                self._t("notices.context_window_guard"),
                source=self.event_source,
                stage=self.event_stage,
                metadata={"trace_kind": "warning"},
            )

    def measure_context_budget(self, request: LLMRequestSnapshot) -> dict[str, Any] | None:
        """Break the turn's last real request down for the composer's chip.

        Measured after the fact from what was actually sent — never a dry run.
        Returns ``None`` when the measurement fails, so the turn is unaffected.
        """
        loaded = self._deferred_loader.loaded_names if self._deferred_loader is not None else set()
        return build_context_budget(
            blocks=self._last_prompt_blocks,
            request=request,
            model=str(self.model or ""),
            context_window=getattr(self.llm_config, "context_window", None),
            max_tokens=getattr(self.llm_config, "max_tokens", None),
            loaded_deferred_names=loaded,
            deferred_tool_count=self._unloaded_deferred_tool_count(loaded),
        )

    def _unloaded_deferred_tool_count(self, loaded: set[str]) -> int:
        """Extended tools whose full schemas never entered the window.

        They cost only their manifest line (the ``extended_tools`` block), so
        they are reported as a scalar rather than as a segment.
        """
        try:
            pool = getattr(self, "_deferred_pool", None) or []
            return sum(1 for tool in pool if tool.get_definition().name not in loaded)
        except Exception:
            logger.debug("deferred-tool count probe failed", exc_info=True)
            return 0

    @staticmethod
    def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
        from deeptutor.services.session.context_builder import count_tokens

        total = 0
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                total += count_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += count_tokens(str(part.get("text") or ""))
        return total

    # ---- LLM client ------------------------------------------------------

    def _build_openai_client(self):
        return build_openai_client(self._client_config)

    def _completion_kwargs(self, max_tokens: int) -> dict[str, Any]:
        return build_completion_kwargs(
            temperature=self._chat_temperature,
            model=self.model,
            max_tokens=max_tokens,
            binding=self.binding,
            reasoning_effort=self.reasoning_effort,
        )

    def _can_use_native_tool_calling(self) -> bool:
        return can_use_native_tool_calling(binding=self.binding, model=self.model)

    # ---- small helpers ---------------------------------------------------

    @staticmethod
    def _current_user_id() -> str:
        try:
            from deeptutor.multi_user.context import get_current_user

            return str(get_current_user().id or "anonymous")
        except Exception:
            return "anonymous"

    @staticmethod
    def _current_owner_id() -> str:
        """Id of the owning account — NOT the same as ``_current_user_id``.

        A partner resolves to the person who owns it and an administrator to the
        deployment id, which is how owner-keyed state (a caller's own MCP
        servers and their credentials) is addressed everywhere else. Using the
        raw current-user id here would have an admin's self-configured servers
        written under one name and read under another.
        """
        try:
            from deeptutor.multi_user.paths import current_owner_id

            return current_owner_id()
        except Exception:
            logger.debug("owner id resolution failed", exc_info=True)
            return ""

    @staticmethod
    def _selected_kbs(context: UnifiedContext) -> list[str]:
        return [str(kb).strip() for kb in context.knowledge_bases if str(kb).strip()]

    def _rag_kbs(self, context: UnifiedContext) -> list[str]:
        """Attached KBs served by rag; PageIndex KBs use their SDK tools."""
        from deeptutor.services.rag.pipelines.pageindex import is_pageindex_kb

        return [kb for kb in self._selected_kbs(context) if not is_pageindex_kb(kb)]

    def _capability_owned_kbs(self, context: UnifiedContext) -> set[str]:
        """Selected KBs consumed by an active capability's own tools (not rag).

        An exclusive knowledge capability (Obsidian) reads its vault through its
        own tools; those KB refs must be excluded from the rag surface. Read via
        ``getattr`` so plain capabilities without the seam are unaffected.
        """
        owned: set[str] = set()
        for cap in self._active_loop_capabilities(context):
            hook = getattr(cap, "owned_kbs", None)
            if callable(hook):
                owned |= set(hook(context))
        return owned

    def _coexisting_rag_kbs(self, context: UnifiedContext) -> list[str]:
        """rag-served KBs that coexist with an exclusive knowledge capability.

        When an Obsidian vault owns the turn, co-selected LlamaIndex KBs would
        otherwise be silently dropped (issue #650). These stay reachable via
        rag; vault KBs (which have no rag index) are excluded. Equals
        ``_rag_kbs`` for a plain chat turn (no capability owns any KB).
        """
        owned = self._capability_owned_kbs(context)
        return [kb for kb in self._rag_kbs(context) if kb not in owned]

    @staticmethod
    def _workspace_key(context: UnifiedContext) -> str:
        raw = str(
            context.metadata.get("turn_id")
            or context.session_id
            or context.metadata.get("message_id")
            or "direct"
        )
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
        return cleaned.strip("_") or "direct"

    def _kb_system_note(self, context: UnifiedContext) -> str:
        if not self._selected_kbs(context):
            return ""
        rag_note = ""
        # Coexisting rag KBs only: when an Obsidian vault owns the turn, its own
        # system block covers the vault, and this note tells the model the
        # co-selected LlamaIndex KBs are reachable via rag (issue #650). A
        # pure-vault turn yields no coexisting KBs, so the note stays empty.
        rag_kbs = self._coexisting_rag_kbs(context)
        if rag_kbs:
            joined = ", ".join(rag_kbs)
            rag_note = (
                f"用户已挂载知识库：{joined}。调用 rag 时，kb_name 必须从其中选一个。"
                if self.language == "zh"
                else (
                    f"Attached knowledge bases: {joined}. When calling rag, kb_name "
                    "must be one of these names."
                )
            )
        return rag_note + self._kb_manifest_system_note() + self._pageindex_system_note()

    async def _prepare_kb_manifests(self, context: UnifiedContext) -> None:
        """Read the attached KBs' document inventories once per turn.

        Retrieval cannot answer "how many files are in here" — the passages it
        returns say nothing about the size of the collection they came from. The
        inventory is read here instead (off the event loop: a directory walk per
        local KB, and a cached browse call for a connected library that exposes
        one) and rendered into the system prompt, which keeps the prompt
        byte-stable for the whole turn and makes counts answerable without a tool
        round-trip.

        PageIndex KBs are excluded: ``_pageindex_system_note`` already lists
        their documents for the SDK tools. Fails soft — a KB
        whose files cannot be read costs the manifest, not the turn.
        """
        self._kb_manifests = []
        kbs = self._rag_kbs(context)
        if not kbs:
            return
        try:
            self._kb_manifests = await asyncio.to_thread(self._collect_kb_manifests, kbs)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to build knowledge base manifests: %s", exc)

    @staticmethod
    def _collect_kb_manifests(kbs: list[str]) -> list[KbManifest]:
        from deeptutor.multi_user.knowledge_access import resolve_kb_manifest

        manifests: list[KbManifest] = []
        for kb in kbs:
            try:
                manifest = resolve_kb_manifest(kb)
            except Exception as exc:
                logger.warning("Failed to read documents of knowledge base '%s': %s", kb, exc)
                continue
            if manifest is not None:
                manifests.append(manifest)
        return manifests

    def _kb_manifest_system_note(self) -> str:
        """What the attached KBs contain, from :meth:`_prepare_kb_manifests`."""
        if not self._kb_manifests:
            return ""
        note = render_manifest_note(self._kb_manifests, language=self.language)
        return f"\n{note}" if note else ""

    def _pageindex_system_note(self) -> str:
        """Retrieval instructions for attached PageIndex KBs.

        Populated by ``_prepare_deferred_tools`` once per turn, so the system
        prompt stays byte-stable for the whole turn (KB cache prefix).
        """
        providers = getattr(self, "_pageindex_providers", None) or set()
        if not providers:
            return ""

        blocks: list[str] = []
        if "pageindex" in providers:
            instructions = str(getattr(self, "_pageindex_cloud_instructions", "") or "").strip()
            if self.language == "zh":
                blocks.append(
                    "\n以下知识库使用 PageIndex Cloud。使用已加载的 pageindex_cloud_* "
                    "SDK 工具先查看文档结构、再读取相关页面；不要使用 rag 读取这些 "
                    "PageIndex 知识库。\n\nPageIndex SDK 阅读说明：\n"
                    f"{instructions}"
                )
            else:
                blocks.append(
                    "\nThe following knowledge bases use PageIndex Cloud. Read them with "
                    "the preloaded pageindex_cloud_* SDK tools; inspect structure, then "
                    "read relevant pages. Do not use rag to read these PageIndex knowledge "
                    "bases.\n\nPageIndex SDK reading instructions:\n"
                    f"{instructions}"
                )
        if "pageindex-oss" in providers:
            instructions = str(getattr(self, "_pageindex_oss_instructions", "") or "").strip()
            if self.language == "zh":
                blocks.append(
                    "\n以下知识库使用 PageIndex OSS。使用已加载的 pageindex_oss_* 工具，"
                    "在当前推理循环中先查看文档结构、再读取相关页面；不要使用 rag 读取这些 "
                    "PageIndex 知识库。\n\nPageIndex SDK 阅读说明：\n"
                    f"{instructions}"
                )
            else:
                blocks.append(
                    "\nThe following knowledge bases use PageIndex OSS. Use the preloaded "
                    "pageindex_oss_* tools inside this reasoning loop; inspect structure, "
                    "then read relevant pages. Do not use rag to read these PageIndex knowledge "
                    "bases.\n\nPageIndex SDK reading instructions:\n"
                    f"{instructions}"
                )
        return "".join(blocks)

    def _workspace_system_note(self, context: UnifiedContext) -> str:
        runtime = getattr(context, "runtime", None)
        workspace = getattr(runtime, "workspace", None)
        if workspace is None:
            # Prompt-only/direct callers have no turn workspace to describe.
            # Never invent a physical fallback path or teach a second shell-
            # based execution protocol; the exec schema is the sole contract.
            return ""
        from deeptutor.agents._shared.workspace_prompt import workspace_system_note

        return workspace_system_note(
            context,
            language=self.language,
            allow_export=True,
        )

    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        value: Any = self._prompts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                value = default
                break
            value = value[part]
        if not isinstance(value, str):
            value = default
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return value
        return value


__all__ = [
    "AgenticLoopPipeline",
    "LOOP_OPTIONAL_TOOLS",
    "KB_SEED_CHARS_PER_KB",
    "KB_SEED_MAX_KBS",
    "_DispatchOutcome",
    "_read_int",
]
