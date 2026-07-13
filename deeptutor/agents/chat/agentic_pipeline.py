"""Chat capability assembly for the exploring-loop agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deeptutor.agents._shared.tool_composition import (
    ToolMountFlags,
    compose_enabled_tools,
    default_optional_tools,
    user_has_memory,
    user_has_notebooks,
)
from deeptutor.agents.chat.agent_loop import AgentLoop
from deeptutor.agents.chat.prompt_blocks import ChatPromptAssembler
from deeptutor.capabilities import (
    LoopCapability,
    active_loop_capabilities,
    any_exclusive_capability_active,
)
from deeptutor.core.agentic import (
    DispatchOutcome,
    LLMClientConfig,
    UsageTracker,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
    dispatch_tool_calls,
)
from deeptutor.core.agentic.tool_dispatch import MAX_PARALLEL_TOOL_CALLS
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)
from deeptutor.runtime.registry.deferred_tools import (
    DeferredToolLoader,
    render_deferred_tools_manifest,
)
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.config import get_chat_params
from deeptutor.services.llm import (
    get_llm_config,
    get_token_limit_kwargs,  # noqa: F401  (re-exported for tests)
    prepare_multimodal_messages,
    supports_tools,  # noqa: F401  (re-exported for tests)
)
from deeptutor.services.llm.context_window import resolve_effective_context_window
from deeptutor.services.prompt import get_prompt_manager
from deeptutor.tools.builtin import PARTNER_BUILTIN_TOOL_NAMES

logger = logging.getLogger(__name__)

# Chat memory tools a partner turn replaces with the partner_* variants.
_PARTNER_SUPPRESSED_TOOLS: tuple[str, ...] = ("read_memory", "write_memory")


CHAT_EXCLUDED_TOOLS: set[str] = set()
CHAT_OPTIONAL_TOOLS = default_optional_tools(excluded=CHAT_EXCLUDED_TOOLS)

# Generation tools are user-toggleable + grant-gated, but only usable once an
# admin has configured an active model for the service. Drop them from a turn's
# tool list when unconfigured so the model never sees a tool that can only error.
_GENERATION_TOOL_SERVICES: dict[str, str] = {"imagegen": "imagegen", "videogen": "videogen"}


def _drop_unconfigured_generation_tools(tools: list[str]) -> list[str]:
    present = [name for name in tools if name in _GENERATION_TOOL_SERVICES]
    if not present:
        return tools
    try:
        from deeptutor.services.config.model_catalog import get_model_catalog_service

        service = get_model_catalog_service()
        catalog = service.load()
        configured = {
            name
            for name in present
            if (service.get_active_model(catalog, _GENERATION_TOOL_SERVICES[name]) or {}).get(
                "model"
            )
        }
    except Exception:
        logger.debug("generation-tool config probe failed; dropping them", exc_info=True)
        configured = set()
    return [name for name in tools if name not in _GENERATION_TOOL_SERVICES or name in configured]


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


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...], default: str) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return value if isinstance(value, str) and value else default


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


def _flatten_ask_user_summary(ask_user_payload: dict[str, Any]) -> str:
    questions = ask_user_payload.get("questions") or []
    if isinstance(questions, list) and questions:
        prompts = [str(q.get("prompt") or "") for q in questions if isinstance(q, dict)]
        prompts = [p for p in prompts if p]
        if prompts:
            return " | ".join(prompts)
    return str(ask_user_payload.get("question") or "")


class AgenticChatPipeline:
    """Run chat as one exploring agent loop followed by a respond stage."""

    def __init__(
        self,
        language: str = "en",
        *,
        max_rounds: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
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
        self.registry = get_tool_registry()
        self._usage = UsageTracker(model=self.model)
        self._deferred_loader: DeferredToolLoader | None = None
        self._deferred_pool: list[Any] = []
        self._exec_enabled = False

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

        try:
            self._prompts: dict[str, Any] = (
                get_prompt_manager().load_prompts(
                    module_name="chat",
                    agent_name="agentic_chat",
                    language=self.language,
                )
                or {}
            )
        except Exception as exc:
            logger.warning("Failed to load agentic_chat prompts: %s", exc)
            self._prompts = {}
        self._prompt_assembler = ChatPromptAssembler(
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
        )

    @property
    def usage(self) -> UsageTracker:
        return self._usage

    @property
    def max_rounds(self) -> int:
        return max(1, self._max_rounds)

    def effective_max_rounds(self, context: UnifiedContext) -> int:
        """Round budget for this turn, lifted to satisfy any capability minimum.

        A capability that needs guaranteed loop headroom — the subagent
        capability, which must allow its full consult budget plus a finishing
        round — sets ``context.metadata["_min_loop_rounds"]``; the loop honours
        the larger of that and the configured budget. A generic seam (like
        solve's ``solve_max_replans``) so the loop stays capability-agnostic.
        """
        try:
            floor = int(context.metadata.get("_min_loop_rounds") or 0)
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

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        await self._prepare_deferred_tools(context)
        self._exec_enabled = await self._exec_allowed(context)
        enabled_tools = self._compose_enabled_tools(context)
        use_native_tools = bool(enabled_tools) and self._can_use_native_tool_calling()
        tool_schemas = (
            self._build_llm_tool_schemas(enabled_tools, context) if use_native_tools else None
        )
        if tool_schemas is not None and self._deferred_loader is not None:
            tool_schemas.extend(self._deferred_loader.initial_schemas())
            self._deferred_loader.bind_live_schemas(tool_schemas)

        loop = AgentLoop(
            pipeline=self,
            context=context,
            stream=stream,
            client=self._build_openai_client(),
            enabled_tools=enabled_tools if use_native_tools else [],
            tool_schemas=tool_schemas,
        )
        await loop.run()

    # ---- prompt assembly -------------------------------------------------

    def _build_system_prompt(
        self,
        enabled_tools: list[str],
        context: UnifiedContext,
        *,
        include_tool_manifest: bool = True,
    ) -> str:
        return self._prompt_assembler.system_prompt(
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
                messages.append({"role": role, "content": content})
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

    def _tool_manifest(self, enabled_tools: list[str]) -> str:
        names = list(enabled_tools)
        if self._deferred_loader is not None:
            for name in sorted(self._deferred_loader.loaded_names):
                if name not in names:
                    names.append(name)
        try:
            return self.registry.build_prompt_text(
                names,
                format="list_with_usage",
                language=self.language,
            )
        except TypeError:
            return self.registry.build_prompt_text(names)
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
        try:
            from deeptutor.services.mcp import get_mcp_manager, load_loaded_tools

            await get_mcp_manager().ensure_started()
            # Caller-scoped whitelist (e.g. a partner's configured MCP tools)
            # intersected with the current user's grant. ``None`` means
            # unrestricted; a set narrows the deferred tools. Real non-admin
            # users fail closed when no MCP grant is present, while partner
            # turns defer to their owner-scoped metadata whitelist as the
            # authority (see ``_is_partner_turn``).
            from deeptutor.multi_user.tool_access import allowed_mcp_tools, combine_whitelists

            raw_filter = context.metadata.get("mcp_tools_filter")
            caller_allowed = (
                {str(name) for name in raw_filter} if isinstance(raw_filter, list) else None
            )
            user_allowed = None if self._is_partner_turn(context) else allowed_mcp_tools()
            allowed: set[str] | None = combine_whitelists(caller_allowed, user_allowed)
            pool = self.registry.deferred_tools()
            if allowed is not None:
                pool = [t for t in pool if t.get_definition().name in allowed]
            self._deferred_pool = pool
            if not pool:
                self._deferred_loader = None
                return
            self._deferred_loader = DeferredToolLoader(
                registry=self.registry,
                session_id=context.session_id,
                loaded=load_loaded_tools(context.session_id),
                allowed=allowed,
            )
        except Exception:
            logger.warning("deferred-tool preparation failed", exc_info=True)
            self._deferred_loader = None

    def _deferred_tools_manifest(self) -> str:
        if self._deferred_loader is None:
            return ""
        return render_deferred_tools_manifest(
            getattr(self, "_deferred_pool", None) or self.registry.deferred_tools(),
            language=self.language,
        )

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
            registry=self.registry,
            requested_tools=context.enabled_tools,
            optional_whitelist=CHAT_OPTIONAL_TOOLS,
            mount_flags=ToolMountFlags(
                has_kb=bool(self._selected_kbs(context)),
                # read_source is owned by the explore_context pre-pass (it runs
                # the investigation over attached sources), not the answer loop.
                # Keep it off the answer surface even when sources are present.
                has_sources=False,
                has_memory=user_has_memory(),
                has_notebooks=user_has_notebooks(),
                has_skills=bool(context.skills_manifest),
                has_deferred_tools=getattr(self, "_deferred_loader", None) is not None,
                has_exec=getattr(self, "_exec_enabled", False),
                has_code=getattr(self, "_exec_enabled", False),
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
        return _drop_unconfigured_generation_tools(composed)

    def _active_loop_capabilities(self, context: UnifiedContext) -> tuple[LoopCapability, ...]:
        return active_loop_capabilities(context)

    @staticmethod
    def _exclusive_capability_active(context: UnifiedContext) -> bool:
        """True when a knowledge capability owns the turn (replaces the surface).

        Suppresses rag scaffolding (KB seed / kb note) too — rag isn't mounted,
        so seeding or advertising it would be wrong.
        """
        return any_exclusive_capability_active(context)

    def _capability_owned_tools(self, context: UnifiedContext) -> tuple[str, ...]:
        """The active capabilities' own tools — added on top of chat's full surface."""
        names: list[str] = []
        for cap in self._active_loop_capabilities(context):
            names.extend(cap.owned_tools)
        return tuple(names)

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

    async def _capability_pre_loop_briefings(
        self,
        context: UnifiedContext,
        stream: StreamBus,
    ) -> str:
        """Run each active capability's optional async ``pre_loop`` hook and
        join their returned blocks into one seed fragment.

        The hook is optional (read via ``getattr`` so plain capabilities are
        unaffected) and runs once before the answer loop's first LLM call —
        see the ``pre_loop`` note on :class:`LoopCapability`. Failures are
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
        schemas = self.registry.build_openai_schemas(enabled_tools)
        kb_choices = self._selected_kbs(context)
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
            for row in AgenticChatPipeline._notebook_choices_full()
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
        from deeptutor.core.agentic import execute_tool_call

        stream = stream or StreamBus()
        return await execute_tool_call(
            registry=self.registry,
            tool_name=tool_name,
            tool_args=tool_args,
            stream=stream,
            source="chat",
            stage="responding",
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
            source="chat",
            stage=stage,
            iteration_index=iteration_index,
            registry=self.registry,
            kwarg_augmenter=self._augment_tool_kwargs,
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
            trace_id_prefix="chat-loop",
        )

    async def _await_user_reply_and_resolve(
        self,
        *,
        context: UnifiedContext,
        stream: StreamBus,
        dispatch: DispatchOutcome,
    ) -> bool:
        ask_user = (dispatch.pause_payload or {}).get("ask_user") or {}
        waiter = context.metadata.get("wait_for_user_reply")
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
        for tm in dispatch.tool_messages:
            if tm.get("tool_call_id") == dispatch.pause_tool_call_id:
                tm["content"] = directive
                break
        meta: dict[str, Any] = {
            "trace_kind": "user_reply",
            "ask_user_resolved": True,
            "ask_user_tool_call_id": dispatch.pause_tool_call_id,
            "reply_preview": (reply_text or "")[:200],
        }
        if answers:
            meta["answers"] = list(answers)
        await stream.progress("", source="chat", stage="responding", metadata=meta)
        return True

    def _augment_tool_kwargs(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        from deeptutor.services.path_service import get_path_service

        kwargs = dict(args)
        turn_id = str(context.metadata.get("turn_id", "") or "").strip()
        workspace_key = self._workspace_key(context)
        task_dir = (
            get_path_service().get_task_workspace("chat", workspace_key) if workspace_key else None
        )
        exec_dir = task_dir / "exec" if task_dir is not None else None
        if tool_name == "rag":
            kwargs.setdefault("mode", "hybrid")
        elif tool_name == "load_tools":
            kwargs["_tool_loader"] = self._deferred_loader
        elif tool_name == "exec":
            from deeptutor.services.sandbox import Mount

            kwargs["_sandbox_user_id"] = self._current_user_id()
            if exec_dir is not None:
                exec_dir.mkdir(parents=True, exist_ok=True)
                kwargs["_sandbox_workdir"] = str(exec_dir)
                kwargs["_sandbox_mounts"] = (
                    Mount(host_path=str(exec_dir), sandbox_path=str(exec_dir), read_only=False),
                )
        elif tool_name == "code_execution":
            from deeptutor.services.sandbox import Mount

            kwargs["_sandbox_user_id"] = self._current_user_id()
            code_dir = task_dir / "code_runs" if task_dir is not None else None
            if code_dir is not None:
                code_dir.mkdir(parents=True, exist_ok=True)
                kwargs["_sandbox_workdir"] = str(code_dir)
                kwargs["_sandbox_mounts"] = (
                    Mount(host_path=str(code_dir), sandbox_path=str(code_dir), read_only=False),
                )
        elif tool_name in ("imagegen", "videogen"):
            # Generated media lands in the turn's public workspace so it
            # surfaces as a download card via /api/outputs (same convention as
            # exec/code_execution artifacts).
            media_dir = task_dir / "media" if task_dir is not None else None
            if media_dir is not None:
                media_dir.mkdir(parents=True, exist_ok=True)
                kwargs["_workspace_dir"] = str(media_dir)
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
        # imagegen/videogen are long-running: wiring retrieve_meta gives them an
        # event_sink so their progress (esp. videogen's poll loop) streams to the
        # client, which resets the chat idle-timeout watchdog mid-render.
        if tool_name in ("imagegen", "videogen"):
            return derive_trace_metadata(
                tool_meta,
                label=self._t("labels.tool_call", default="Tool call"),
                call_kind="media_generation",
                query=str(tool_args.get("prompt", "") or ""),
            )
        # consult_subagent drives a live local agent that runs for as long as it
        # needs: wiring retrieve_meta gives it an event_sink so every native
        # output/log streams to the sidebar in real time (and keeps the
        # idle-timeout watchdog fed during a long agent run).
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
        if self._exclusive_capability_active(context):
            return ""
        kbs = self._selected_kbs(context)
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
                sources, source="chat", stage="responding", metadata={"trace_kind": "sources"}
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
        call_id = new_call_id("chat-kb-seed")
        retrieve_meta = build_trace_metadata(
            call_id=call_id,
            phase="responding",
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
            source="chat",
            stage="responding",
            metadata=merge_trace_metadata(final_meta, {"trace_kind": "llm_output"}),
        )

    async def _emit_protocol_fallback_final_response(
        self,
        stream: StreamBus,
        content: str,
    ) -> None:
        final_meta = build_trace_metadata(
            call_id=new_call_id("chat-final-response"),
            phase="responding",
            label=self._t("labels.final_response", default="Final response"),
            call_kind="llm_final_response",
            trace_id="chat-final-response",
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
            call_id=new_call_id("chat-final-response"),
            phase="responding",
            label=self._t("labels.final_response", default="Final response"),
            call_kind="llm_final_response",
            trace_id="chat-final-response",
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
            source="chat",
            stage="responding",
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
                source="chat",
                stage="responding",
                metadata={"trace_kind": "warning"},
            )

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
    def _selected_kbs(context: UnifiedContext) -> list[str]:
        return [str(kb).strip() for kb in context.knowledge_bases if str(kb).strip()]

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
        if self._exclusive_capability_active(context):
            return ""
        kbs = self._selected_kbs(context)
        if not kbs:
            return ""
        joined = ", ".join(kbs)
        if self.language == "zh":
            return f"用户已挂载知识库：{joined}。调用 rag 时，kb_name 必须从其中选一个。"
        return f"Attached knowledge bases: {joined}. When calling rag, kb_name must be one of these names."

    def _workspace_system_note(self, context: UnifiedContext) -> str:
        if not getattr(self, "_exec_enabled", False):
            return ""
        try:
            from deeptutor.services.path_service import get_path_service

            exec_dir = (
                get_path_service().get_task_workspace(
                    "chat",
                    self._workspace_key(context),
                )
                / "exec"
            )
        except Exception:
            return ""
        if self.language == "zh":
            return (
                "[本轮工作区]\n"
                f"脚本和临时文件应写入：{exec_dir}\n"
                "相对路径会解析到这个目录。需要创建 PDF、图片、表格或其他下载文件时，"
                "直接通过 exec 写入并运行脚本（如 heredoc：python - <<'PY' … PY，"
                "或 cat > gen.py <<'EOF' … EOF 后再运行）。生成的文件会自动以可下载"
                "卡片呈现给用户——在回答里描述你做了什么即可，不要粘贴原始 URL。"
            )
        return (
            "[Turn workspace]\n"
            f"Scripts and temporary files should be written under: {exec_dir}\n"
            "Relative paths resolve to this directory. When creating PDFs, images, "
            "spreadsheets, or other downloadable files, write and run scripts directly "
            "through exec (e.g. a heredoc: python - <<'PY' … PY, or cat > gen.py <<'EOF' "
            "… EOF then run it). Generated files are shown to the user automatically as "
            "downloadable cards — describe what you made, do not paste raw URLs."
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
    "AgenticChatPipeline",
    "CHAT_OPTIONAL_TOOLS",
    "KB_SEED_CHARS_PER_KB",
    "KB_SEED_MAX_KBS",
    "_DispatchOutcome",
    "_read_int",
]
