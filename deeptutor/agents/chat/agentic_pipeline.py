"""Single-loop agentic chat pipeline.

The chat capability runs as one iterative LLM loop. Each iteration is a
single streaming LLM call followed by, depending on the model's first-line
protocol label:

* ``FINISH`` → the post-label text IS the final user-facing answer; loop exits.
* ``TOOL``   → native tool_calls run in parallel; their results feed the next
  iteration. Tools may pause (``ask_user``) or terminate the turn.
* ``THINK``  → intermediate reasoning; loop continues so the next call can
  build on it.
* ``PAUSE``  → semantically a ``THINK`` whose prose is shown to the user.
  Same loop behavior as ``THINK`` (intermediate, no tools, loop continues),
  but the post-label text streams into the chat bubble like ``FINISH`` so
  the user sees the reasoning when it's worth showing.

This module is the *capability-specific* assembly layer. The generic engine
lives in :mod:`deeptutor.core.agentic`: label parsing, single-call streaming,
parallel tool dispatch, and the loop scheduler. Chat plugs in its own:

* tool composition + per-turn KB / source / notebook enums,
* system-prompt + message assembly (memory, skills, manifests, attachments),
* server-side tool-kwarg augmentation,
* context-window guard, force-finalize, answer-now fast path,
* protocol-violation copy (YAML-loaded, language-aware).

History compression (branch-safe) is handled upstream by
``ContextBuilder.build`` so it does not appear here.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from deeptutor.agents._shared.tool_composition import (
    ToolMountFlags,
    compose_enabled_tools,
    default_optional_tools,
    user_has_memory,
    user_has_notebooks,
)
from deeptutor.capabilities._shared import emit_capability_result
from deeptutor.core.agentic import (
    LABEL_PROBE_MAX_CHARS,
    LABEL_UNKNOWN,
    DispatchOutcome,
    LabeledStepResult,
    LabelProtocol,
    LLMClientConfig,
    UsageTracker,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
    dispatch_tool_calls,
    run_agentic_loop,
    run_labeled_step,
)
from deeptutor.core.agentic.labels import find_inline_labels, strip_label_probe_prefix
from deeptutor.core.agentic.tool_dispatch import MAX_PARALLEL_TOOL_CALLS
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.config import get_chat_params, load_system_settings  # noqa: F401
from deeptutor.services.llm import (
    clean_thinking_tags,
    get_llm_config,
    get_token_limit_kwargs,  # noqa: F401  (re-exported for tests)
    has_thinking_tags,
    prepare_multimodal_messages,
    supports_tools,  # noqa: F401  (re-exported for tests)
)
from deeptutor.services.provider_registry import find_by_name
from deeptutor.services.llm import (
    stream as llm_stream,
)
from deeptutor.services.llm.context_window import resolve_effective_context_window
from deeptutor.services.prompt import get_prompt_manager
from deeptutor.services.prompt.language import append_language_directive

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

CHAT_EXCLUDED_TOOLS: set[str] = set()
# User-toggleable tools — the composer / settings UI surface. Computed once
# at import time via the shared tool-composition policy so chat and quiz
# pipelines can't disagree about which tools the user controls.
CHAT_OPTIONAL_TOOLS = default_optional_tools(excluded=CHAT_EXCLUDED_TOOLS)

# Tool-iteration ceiling: high enough for multi-step chat loops with
# ask_user/tool repair, still bounded to prevent runaway loops. Overridable
# via ``capabilities.chat.max_iterations``.
DEFAULT_MAX_ITERATIONS = 20
# When messages exceed this fraction of the model's effective context
# window, the in-turn guard replaces the largest stale tool-result with a
# snip marker. Keeps headroom for the next LLM call without aborting.
CONTEXT_WINDOW_GUARD_RATIO = 0.9
TOOL_RESULT_SNIP_MARKER = (
    "[earlier tool result snipped to stay within context window — "
    "call the same tool again if the content is still needed]"
)
FINALIZATION_REPAIR_ATTEMPTS = 3

# Chat-only label strings (chat's protocol vocabulary). Kept as named
# constants for legibility in the chat YAML/copy code that references them.
LABEL_FINISH = "FINISH"
LABEL_TOOL = "TOOL"
LABEL_THINK = "THINK"
# ``PAUSE`` is chat-specific: semantically it's ``THINK`` made visible —
# same intermediate / no-tools / loop-continues behavior, but the
# post-label text is streamed into the user-facing chat bubble (so it
# lives in both ``intermediate`` AND ``final``). The LLM picks ``PAUSE``
# over ``THINK`` only when the reasoning itself is worth showing to the
# user.
LABEL_PAUSE = "PAUSE"

# Chat's label protocol, fed into the generic loop primitive.
_CHAT_PROTOCOL = LabelProtocol(
    allowed=(LABEL_FINISH, LABEL_TOOL, LABEL_THINK, LABEL_PAUSE),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset({LABEL_THINK, LABEL_PAUSE}),
    final=frozenset({LABEL_FINISH, LABEL_PAUSE}),
    tool_label=LABEL_TOOL,
)


# ---------------------------------------------------------------------------
# Answer-now lenient label parsing
# ---------------------------------------------------------------------------
# The main loop owns the canonical protocol and now tolerates common wrapper
# variants at the core parser level. Answer-now is still more permissive — it
# is a terminal, tool-less fast-path, so the safest UI behavior is to strip
# common spellings rather than render them as a literal label.

_ANSWER_NOW_WRAPPED_LABEL_RE = re.compile(
    r"^`+\s*(FINISH|TOOL|THINK|PAUSE)\s*`+(?P<after>.*)$",
    re.DOTALL,
)
_ANSWER_NOW_UNTERMINATED_WRAPPED_LABEL_RE = re.compile(
    r"^`+\s*(FINISH|TOOL|THINK|PAUSE)\s*$",
    re.DOTALL,
)
_LABEL_SEPARATOR_CHARS = "\n\r \t:：-–—"
_ANSWER_NOW_ALLOWED_LABELS: tuple[str, ...] = (
    LABEL_FINISH,
    LABEL_TOOL,
    LABEL_THINK,
    LABEL_PAUSE,
)


# Re-export for tests that still import this name. New code constructs the
# canonical ``DispatchOutcome`` directly.
_DispatchOutcome = DispatchOutcome


def _could_be_wrapped_answer_now_label(stripped: str) -> bool:
    """Whether a backtick-prefixed buffer may still become a label."""
    probe = stripped.lstrip("`").lstrip()
    if not probe:
        return True
    for label in _ANSWER_NOW_ALLOWED_LABELS:
        if label.startswith(probe):
            return True
        if probe.startswith(label):
            after = probe[len(label) :]
            if not after.strip("` \t\r\n"):
                return True
    return False


def _classify_answer_now_label(
    buffer: str,
    *,
    final: bool = False,
) -> tuple[str, str] | None:
    """Lenient label stripper used by :meth:`AgenticChatPipeline._run_answer_now`.

    Accepts the canonical double-backtick wrapping as well as common
    looser variants (single-backtick wrappers, unwrapped labels followed
    by a separator). Returns ``None`` when the buffer still looks like a
    partial label match — caller keeps buffering.
    """
    from deeptutor.core.agentic.labels import classify_label

    parsed = classify_label(buffer, allowed_labels=_ANSWER_NOW_ALLOWED_LABELS)
    if parsed is not None:
        return parsed

    stripped = strip_label_probe_prefix(buffer)
    wrapped = _ANSWER_NOW_WRAPPED_LABEL_RE.match(stripped)
    if wrapped:
        return wrapped.group(1), wrapped.group("after").lstrip(_LABEL_SEPARATOR_CHARS)
    unterminated = _ANSWER_NOW_UNTERMINATED_WRAPPED_LABEL_RE.match(stripped)
    if final and unterminated:
        return unterminated.group(1), ""

    for label in _ANSWER_NOW_ALLOWED_LABELS:
        for prefix in (f"`{label}`", label):
            if stripped.startswith(prefix):
                after = stripped[len(prefix) :]
                if after:
                    if after[0] in _LABEL_SEPARATOR_CHARS:
                        return label, after.lstrip(_LABEL_SEPARATOR_CHARS)
                    continue
                if final:
                    return label, ""
            if prefix.startswith(stripped):
                return None
    if stripped.startswith("`") and _could_be_wrapped_answer_now_label(stripped):
        return None
    return None


def _normalise_user_reply(
    raw: Any,
) -> tuple[str, list[dict[str, str]] | None]:
    """Normalise a waiter() reply into ``(text, answers)``.

    Accepts either a plain string (legacy / direct injection in tests)
    or a dict ``{"text": str, "answers": list | None}`` (runtime path
    that supports the v2 multi-question schema).
    """
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
                if not qid:
                    continue
                answers.append({"questionId": qid, "text": str(entry.get("text") or "")})
            return text, answers or None
        return text, None
    return str(raw or ""), None


def _format_user_reply_body(
    text: str,
    answers: list[dict[str, str]] | None,
    ask_user_payload: dict[str, Any],
) -> str:
    """Render the ``User answered:`` body the model sees on resume.

    Multi-question replies are rendered as one ``- <prompt>\n  → <answer>``
    line per question so the model has the original question text in
    context. Skipped or empty answers come through as ``(skipped)``.
    """
    if answers:
        prompts_by_id: dict[str, str] = {}
        for q in ask_user_payload.get("questions") or []:
            if isinstance(q, dict):
                qid = str(q.get("id") or "")
                prompts_by_id[qid] = str(q.get("prompt") or qid)
        lines = ["User answered:"]
        for entry in answers:
            qid = entry.get("questionId", "")
            prompt = prompts_by_id.get(qid) or qid or "(question)"
            value = (entry.get("text") or "").strip() or "(skipped)"
            lines.append(f"- {prompt}\n  → {value}")
        return "\n".join(lines)
    flat = (text or "").strip() or "(empty reply)"
    return f"User answered: {flat}"


def _flatten_ask_user_summary(ask_user_payload: dict[str, Any]) -> str:
    """One-line summary for fallback terminator emit when no waiter wired."""
    questions = ask_user_payload.get("questions") or []
    if isinstance(questions, list) and questions:
        prompts = [str(q.get("prompt") or "") for q in questions if isinstance(q, dict)]
        prompts = [p for p in prompts if p]
        if prompts:
            return " | ".join(prompts)
    # Legacy single-question payload shape (pre-v2).
    return str(ask_user_payload.get("question") or "")


def _read_int(cfg: Any, *, key: str, default: int) -> int:
    """Pull an integer from a nested YAML dict, falling back to ``default``."""
    if isinstance(cfg, dict):
        value = cfg.get(key, default)
    else:
        value = default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class AgenticChatPipeline:
    """Run chat as a single iterative LLM loop with native tool calling."""

    def __init__(self, language: str = "en") -> None:
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

        try:
            chat_cfg = get_chat_params()
        except Exception as exc:
            logger.warning("Failed to load chat params, using defaults: %s", exc)
            chat_cfg = {}
        try:
            self._chat_temperature = float(chat_cfg.get("temperature", 0.2))
        except (TypeError, ValueError):
            self._chat_temperature = 0.2
        # Token budgets for the two LLM call shapes used by this pipeline.
        # ``responding`` caps each loop iteration; ``answer_now`` caps the
        # single-shot fallback when the user clicks "Answer now" mid-stream.
        self._responding_max_tokens = _read_int(
            chat_cfg.get("responding"), key="max_tokens", default=8000
        )
        self._answer_now_max_tokens = _read_int(
            chat_cfg.get("answer_now"), key="max_tokens", default=8000
        )
        self._max_iterations = _read_int(
            chat_cfg, key="max_iterations", default=DEFAULT_MAX_ITERATIONS
        )

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

        self._client_config = LLMClientConfig(
            binding=self.binding,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            extra_headers=self.extra_headers or None,
            reasoning_effort=self.reasoning_effort,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        answer_now_context = self._extract_answer_now_context(context)
        if answer_now_context is not None:
            await self._run_answer_now(context, answer_now_context, stream)
            return

        enabled_tools = self._compose_enabled_tools(context)
        use_native_tools = bool(enabled_tools) and self._can_use_native_tool_calling()
        _is_reasoner = has_thinking_tags(self.binding, self.model)
        tool_schemas = (
            self._build_llm_tool_schemas(enabled_tools, context) if use_native_tools else None
        )

        system_prompt = self._build_system_prompt(enabled_tools, context)
        if _is_reasoner and use_native_tools:
            system_prompt = self._append_reasoner_protocol_note(system_prompt)
        user_content = self._t(
            "user_template",
            default=context.user_message,
            user_message=context.user_message,
        )
        messages = self._build_messages(
            context=context,
            system_prompt=system_prompt,
            user_content=user_content,
        )
        messages, images_stripped = self._prepare_messages_with_attachments(messages, context)

        if images_stripped:
            # ``images_stripped`` is a transient warning, not a sub-trace, so
            # it carries no call_id (frontend ``CallTracePanel`` groups by
            # call_id and would otherwise spawn an empty sub-trace row).
            await stream.thinking(
                self._t("notices.images_stripped", model=self.model or ""),
                source="chat",
                stage="responding",
                metadata={"trace_kind": "warning"},
            )

        # Build the per-turn OpenAI client via ``_build_openai_client`` so
        # tests can monkey-patch that method post-instantiation to inject a
        # scripted client.
        client = self._build_openai_client()
        host = _ChatLoopHost(
            pipeline=self,
            context=context,
            stream=stream,
            client=client,
        )
        # Outer ``stage("responding")`` only drives the frontend's
        # ``currentStage`` indicator ("DeepTutor responding…"). It carries no
        # call_id so it does NOT spawn its own sub-trace; each LLM iteration
        # and each tool call below allocate their own call_id and surface as
        # individual sub-traces in CallTracePanel.
        completion_kwargs = self._completion_kwargs(max_tokens=self._responding_max_tokens)

        # Reasoning models (e.g. Qwen3.6-Plus) need ``enable_thinking``
        # explicitly set so the API correctly handles thinking + tool_calls.
        # When the binding already has a ``thinking_style`` (e.g. dashscope),
        # ``build_provider_extra_kwargs`` handles this. But when the model is
        # accessed via a generic binding (e.g. custom / OpenAI-compatible)
        # that lacks ``thinking_style``, we must inject it here.
        if _is_reasoner and use_native_tools:
            _spec = find_by_name(self.binding)
            if not (_spec and _spec.thinking_style):
                completion_kwargs.setdefault("extra_body", {})["enable_thinking"] = True

        # When native tool calling is unavailable (no tool schemas), strip
        # the TOOL label from the protocol so the loop does not expect
        # ``tool_calls`` deltas and trigger ``tool_without_calls`` violations.
        protocol = _CHAT_PROTOCOL
        if not use_native_tools and protocol.tool_label is not None:
            protocol = LabelProtocol(
                allowed=tuple(l for l in protocol.allowed if l != LABEL_TOOL),
                terminal=protocol.terminal,
                intermediate=protocol.intermediate,
                final=protocol.final,
                tool_label=None,
            )

        async with stream.stage("responding", source="chat"):
            outcome = await run_agentic_loop(
                initial_messages=messages,
                protocol=protocol,
                client=client,
                model=self.model,
                completion_kwargs=completion_kwargs,
                binding=self.binding,
                tool_schemas=tool_schemas,
                stream=stream,
                source="chat",
                stage="responding",
                max_iterations=max(1, self._max_iterations),
                host=host,
                usage=self._usage,
                # Reasoning models with native tool-calling support emit
                # ``reasoning_content`` without parroting back
                # ````THINK```` labels.  When the model is a reasoner
                # AND native tool calling is active, use LABEL_FINISH so
                # that a reply containing ``reasoning_content`` + answer
                # text (but no explicit label) terminates the loop — the
                # answer lives in ``content``, reasoning in
                # ``reasoning_content``.  Non-reasoning models that emit
                # ``<think/>`` tags get LABEL_THINK so the loop continues.
                implicit_think_label=LABEL_FINISH if (_is_reasoner and use_native_tools) else LABEL_THINK,
            )

        if outcome.sources:
            await stream.sources(
                outcome.sources,
                source="chat",
                stage="responding",
                metadata={"trace_kind": "sources"},
            )

        result_payload: dict[str, Any] = {
            "response": outcome.final_text,
            "iterations": outcome.iterations,
            "completed": outcome.completed,
        }
        await emit_capability_result(stream, result_payload, source="chat", usage=self._usage)

    # ------------------------------------------------------------------
    # Iteration trace metadata
    # ------------------------------------------------------------------
    def _build_iteration_trace_metadata(
        self, iteration: int
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Allocate trace metadata for one model iteration.

        ``iter_meta`` scopes the reasoning sub-trace that THINK/TOOL/UNKNOWN
        paths open; FINISH never opens it so the row stays empty in those
        cases. ``final_meta`` is the per-iter id for body content events on
        the FINISH path.
        """
        iter_call_id = new_call_id(f"chat-iter-{iteration}")
        iter_meta = build_trace_metadata(
            call_id=iter_call_id,
            phase="responding",
            label=self._t("labels.reasoning", default="Reasoning"),
            call_kind="llm_reasoning",
            trace_id=iter_call_id,
            trace_role="thought",
            trace_group="stage",
        )
        final_call_id = new_call_id("chat-final-response")
        final_meta = build_trace_metadata(
            call_id=final_call_id,
            phase="responding",
            label=self._t("labels.final_response", default="Final response"),
            call_kind="llm_final_response",
            trace_id=final_call_id,
            trace_role="response",
            trace_group="stage",
        )
        return iter_meta, final_meta

    # ------------------------------------------------------------------
    # Protocol copy (delegated to YAML; loop host calls these)
    # ------------------------------------------------------------------
    def _protocol_retry_notice(self) -> str:
        return self._t(
            "notices.protocol_retry",
            default="The model violated the action-label protocol; retrying this iteration.",
        )

    def _protocol_repair_message(self, violation: str) -> str:
        if self.language == "zh":
            reason = {
                "missing_label": "你上一轮回复没有以必需的协议标签开头",
                "multiple_labels": "你上一轮回复在同一次输出里出现了多个协议标签",
                "tool_without_calls": "你上一轮选择了 ``TOOL``，但没有发起真实 tool_calls",
                "think_with_tools": "你上一轮选择了 ``THINK``，但同时发起了工具调用",
                "finish_with_tools": "你上一轮选择了 ``FINISH``，但同时发起了工具调用",
                "pause_with_tools": "你上一轮选择了 ``PAUSE``，但同时发起了工具调用",
            }.get(violation, "你上一轮回复不符合协议")
            default = (
                f"协议修正：{reason}，所以本轮还不能结束。下一次回复必须"
                "只选择一个动作标签，并且只在第一行写一次：``FINISH``、"
                "``TOOL``、``THINK`` 或 ``PAUSE``。标签正文里不要再出现"
                "第二个协议标签。如果内容本来就是最终答案，用 ``FINISH``；"
                "如果需要工具，用 ``TOOL`` 并在同一次回复里发起真实 "
                "tool_calls；如果只是中间思考、用户不需要看到，用 ``THINK``"
                " 且不要调用工具；如果这段思考让用户看到比藏着更有价值，"
                "用 ``PAUSE``（等于可见的 ``THINK``）且不要调用工具。"
            )
        else:
            reason = {
                "missing_label": "your previous reply did not begin with a protocol label",
                "multiple_labels": "your previous reply contained multiple protocol labels",
                "tool_without_calls": "you chose ``TOOL`` but emitted no real tool_calls",
                "think_with_tools": "you chose ``THINK`` while also emitting tool_calls",
                "finish_with_tools": "you chose ``FINISH`` while also emitting tool_calls",
                "pause_with_tools": "you chose ``PAUSE`` while also emitting tool_calls",
            }.get(violation, "your previous reply violated the protocol")
            default = (
                f"Protocol correction: {reason}, so the turn is not complete. "
                "Your next reply must choose exactly one action label, written "
                "once on the first line only: ``FINISH``, ``TOOL``, ``THINK``, "
                "or ``PAUSE``. Do not include a second protocol label anywhere "
                "in the body. If the draft was the final answer, use "
                "``FINISH``. If tools are needed, use ``TOOL`` and emit real "
                "tool_calls in that same reply. If this is private intermediate "
                "reasoning the user doesn't need to see, use ``THINK`` and "
                "do not call tools. If your reasoning is worth showing to the "
                "user, use ``PAUSE`` (same as ``THINK`` plus visibility) and "
                "do not call tools."
            )
        return self._t(f"protocol.{violation}", default=default)

    def _force_finish_message(self) -> str:
        if self.language == "zh":
            default = (
                "迭代预算已用完。现在必须给出面向用户的最终答复：第一行必须是 "
                "``FINISH``，不要再调用工具，也不要再用 ``THINK`` 或 ``PAUSE``。"
                "如果信息仍不完整，请简短说明不确定性，但仍给出当前最有用的答案。"
            )
        else:
            default = (
                "The iteration budget is exhausted. You must now produce the "
                "user-facing final answer: the first line must be ``FINISH``. "
                "Do not call tools and do not use ``THINK`` or ``PAUSE``. If "
                "information is still incomplete, state the uncertainty briefly "
                "while giving the most useful answer possible."
            )
        return self._t("protocol.force_finish", default=default)

    def _force_finish_repair_message(self, violation: str) -> str:
        if self.language == "zh":
            reason = "没有使用 ``FINISH``"
            if violation == "multiple_labels":
                reason = "在最终化回复里混用了多个标签"
            elif violation == "tool_without_calls":
                reason = "仍然选择了 ``TOOL``"
            elif violation == "think_with_tools":
                reason = "用 ``THINK`` 的同时调用了工具"
            elif violation == "finish_with_tools":
                reason = "用 ``FINISH`` 的同时调用了工具"
            elif violation == "pause_with_tools":
                reason = "用 ``PAUSE`` 的同时调用了工具"
            default = (
                f"最终化协议修正：上一轮{reason}。现在只能输出一个最终答案："
                "第一行写 ``FINISH``，后面直接给用户答案。不要写 ``THINK``、"
                "``PAUSE``，不要写 ``TOOL``，不要调用任何工具，也不要在正文里"
                "再次出现协议标签。"
            )
        else:
            reason = "did not use ``FINISH``"
            if violation == "multiple_labels":
                reason = "mixed multiple labels in the finalization reply"
            elif violation == "tool_without_calls":
                reason = "still chose ``TOOL``"
            elif violation == "think_with_tools":
                reason = "used ``THINK`` while calling tools"
            elif violation == "finish_with_tools":
                reason = "used ``FINISH`` while calling tools"
            elif violation == "pause_with_tools":
                reason = "used ``PAUSE`` while calling tools"
            default = (
                f"Finalization protocol correction: the previous reply {reason}. "
                "Now output only a final answer: first line ``FINISH``, then the "
                "user-facing answer. Do not write ``THINK``, ``PAUSE``, or "
                "``TOOL``, do not call tools, and do not include another "
                "protocol label in the body."
            )
        return self._t("protocol.force_finish_repair", default=default)

    def _protocol_fallback_final_text(self) -> str:
        if self.language == "zh":
            default = (
                "我已经达到本轮迭代上限，但模型没有按 ``FINISH`` 协议产出合格的"
                "最终回答。请重试一次，或把问题范围收窄；我会从已有上下文继续。"
            )
        else:
            default = (
                "I reached the iteration limit, but the model did not produce "
                "a valid ``FINISH`` response. Please retry or narrow the request; "
                "I can continue from the existing context."
            )
        return self._t("protocol.fallback_final", default=default)

    # ------------------------------------------------------------------
    # Forced finalization (host hook for max-iter exhaustion)
    # ------------------------------------------------------------------
    async def _run_forced_finish(
        self,
        *,
        client: Any,
        messages: list[dict[str, Any]],
        stream: StreamBus,
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        """Ask the model for one tool-less ``FINISH`` reply, retrying on
        protocol violations. Returns ``(final_text, completed, calls)``."""
        calls = 0
        messages.append({"role": "user", "content": self._force_finish_message()})
        await stream.progress(
            self._t("notices.max_iterations_reached"),
            source="chat",
            stage="responding",
            metadata={"trace_kind": "warning"},
        )
        for attempt in range(FINALIZATION_REPAIR_ATTEMPTS):
            await self._guard_context_window(messages, stream)
            iter_meta, final_meta = self._build_iteration_trace_metadata(start_iteration + attempt)
            step = await run_labeled_step(
                client=client,
                model=self.model,
                messages=messages,
                completion_kwargs=self._completion_kwargs(max_tokens=self._responding_max_tokens),
                tool_schemas=None,
                allowed_labels=(LABEL_FINISH,),
                final_labels=frozenset({LABEL_FINISH}),
                tool_label=None,
                stream=stream,
                source="chat",
                stage="responding",
                iter_meta=iter_meta,
                binding=self.binding,
                usage=self._usage,
            )
            calls += 1

            violation = _classify_forced_finish_violation(step)
            if step.label == LABEL_FINISH and not violation:
                await self._emit_final_text(stream, step.text, final_meta)
                return step.text, True, calls

            final_violation = violation or "final_missing_finish"
            await stream.progress(
                self._t(
                    "notices.final_protocol_failed",
                    default=(
                        "The model still did not produce a valid FINISH reply "
                        "after the finalization prompt."
                    ),
                ),
                source="chat",
                stage="responding",
                metadata={
                    "trace_kind": "warning",
                    "protocol_violation": final_violation,
                    "finalization_attempt": attempt + 1,
                },
            )
            self._append_assistant_context(messages, step.text)
            messages.append(
                {
                    "role": "user",
                    "content": self._force_finish_repair_message(final_violation),
                }
            )

        fallback = self._protocol_fallback_final_text()
        await self._emit_protocol_fallback_final_response(stream, fallback)
        return fallback, False, calls

    @staticmethod
    def _append_assistant_context(
        messages: list[dict[str, Any]],
        text: str,
    ) -> None:
        clipped = str(text or "").strip()
        if not clipped:
            return
        if len(clipped) > 500:
            clipped = clipped[:500].rstrip() + "\n...[truncated]"
        messages.append({"role": "assistant", "content": clipped})

    # ------------------------------------------------------------------
    # Emit helpers (host hooks)
    # ------------------------------------------------------------------
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

    async def _emit_terminator_final_response(
        self,
        stream: StreamBus,
        payload: dict[str, Any] | None,
    ) -> None:
        """Emit a ``content(call_kind=llm_final_response)`` event with the
        terminating tool's content + its UI metadata.

        Generic enough to support any future ``terminate_turn`` tool: the
        tool's own ``ToolResult.metadata`` rides along on the
        ``tool_metadata`` slot so the frontend can dispatch on it (e.g.
        render option chips for ``ask_user`` via ``tool_metadata.ask_user``).
        """
        if not payload:
            return
        content = str(payload.get("content") or "").strip()
        tool_metadata = payload.get("metadata") or {}
        if not content:
            return
        final_call_id = new_call_id("chat-final-response")
        final_meta = build_trace_metadata(
            call_id=final_call_id,
            phase="responding",
            label=self._t("labels.final_response", default="Final response"),
            call_kind="llm_final_response",
            trace_id=final_call_id,
            trace_role="response",
            trace_group="stage",
            terminator_tool=str(payload.get("tool_name") or ""),
        )
        merged_metadata: dict[str, Any] = {"trace_kind": "llm_output"}
        if isinstance(tool_metadata, dict) and tool_metadata:
            merged_metadata["tool_metadata"] = dict(tool_metadata)
        await stream.content(
            content,
            source="chat",
            stage="responding",
            metadata=merge_trace_metadata(final_meta, merged_metadata),
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
            protocol_fallback=True,
        )
        await stream.content(
            content,
            source="chat",
            stage="responding",
            metadata=merge_trace_metadata(final_meta, {"trace_kind": "llm_output"}),
        )

    @staticmethod
    def _assistant_message_with_tool_calls(
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc.get("arguments") or "{}",
                    },
                }
                for tc in tool_calls
            ],
        }

    # ------------------------------------------------------------------
    # Tool dispatch (thin wrappers around the primitives — preserved for tests)
    # ------------------------------------------------------------------
    async def _execute_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        stream: StreamBus | None = None,
        retrieve_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a single tool with chat-flavored retrieve-progress events.

        Direct callers (notably test code) use this to drive one tool
        without going through the parallel dispatcher.
        """
        from deeptutor.core.agentic import execute_tool_call

        if stream is None:
            # No stream means no retrieve trace either; fall through with a
            # dummy bus so the primitive's stream calls become no-ops.
            stream = StreamBus()
        return await execute_tool_call(
            registry=self.registry,
            tool_name=tool_name,
            tool_args=tool_args,
            stream=stream,
            source="chat",
            stage="acting",
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
    ) -> DispatchOutcome:
        """Dispatch this iteration's tool calls under chat-specific labels,
        kwarg-augmenter, and retrieve-trace metadata."""
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
            stage="acting",
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
            trace_id_prefix="chat-iter",
        )

    # ------------------------------------------------------------------
    # ``ask_user`` pause / resume
    # ------------------------------------------------------------------
    async def _await_user_reply_and_resolve(
        self,
        *,
        context: UnifiedContext,
        stream: StreamBus,
        dispatch: DispatchOutcome,
    ) -> bool:
        """Pause the loop on an ``ask_user`` call and wait for the reply.

        Returns ``True`` once the user's reply has been substituted into the
        matching ``role=tool`` message and the loop can resume. Returns
        ``False`` if the runtime did not wire a reply queue (in which case
        the pipeline falls back to emitting a terminator final-response,
        mirroring the legacy behaviour so direct unit tests of the pipeline
        still work).

        ``asyncio.CancelledError`` propagates up from ``waiter()`` when the
        runtime cancels the turn task — caught by the runtime's own
        cancellation handler which emits the right ERROR + DONE events. We
        intentionally do NOT catch it here.
        """
        ask_user = (dispatch.pause_payload or {}).get("ask_user") or {}
        waiter = context.metadata.get("wait_for_user_reply")
        if not callable(waiter):
            logger.warning(
                "ask_user paused the loop but no wait_for_user_reply "
                "callable is wired on the context; emitting terminator."
            )
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

        # Normalise: callers may pass either a plain string (older tests
        # / direct injections) or a structured dict (runtime / v2 path).
        reply_text, answers = _normalise_user_reply(raw_reply)
        body_text = _format_user_reply_body(reply_text, answers, ask_user)

        # Mutate the paused tool's matching ``role=tool`` message in place.
        # ``dispatch.tool_messages`` shares object identity with entries we
        # already extended onto ``messages``, so this change is visible to
        # the next LLM call without re-walking the list.
        #
        # The body is deliberately directive: a bare "User answered: X" was
        # being misread by some models as the end of the turn. Spelling out
        # "you must continue / do not stop after a one-liner ack" at the
        # exact point in the conversation where the model is deciding what
        # to do next keeps the loop alive across ask_user.
        resumption_directive = (
            f"{body_text}\n\n"
            "[ask_user resolved. The turn is NOT over. Use these answers "
            "to address the user's ORIGINAL request — call more tools "
            "if you need them, then close with a substantive ``FINISH`` "
            "reply. A short acknowledgment of the answer is NOT an "
            "acceptable final response.]"
        )
        for tm in dispatch.tool_messages:
            if tm.get("tool_call_id") == dispatch.pause_tool_call_id:
                tm["content"] = resumption_directive
                break

        progress_meta: dict[str, Any] = {
            "trace_kind": "user_reply",
            "ask_user_resolved": True,
            "ask_user_tool_call_id": dispatch.pause_tool_call_id,
            "reply_preview": (reply_text or "")[:200],
        }
        if answers:
            progress_meta["answers"] = list(answers)
        await stream.progress(
            "",
            source="chat",
            stage="responding",
            metadata=progress_meta,
        )
        return True

    # ------------------------------------------------------------------
    # Answer-now: cancel mid-stream and produce a final answer from what's
    # already been generated. Single LLM call, tools disabled, partial draft
    # injected as a fake assistant message so the model continues naturally.
    # ------------------------------------------------------------------
    async def _run_answer_now(
        self,
        context: UnifiedContext,
        answer_now_context: dict[str, Any],
        stream: StreamBus,
    ) -> None:
        partial_response = str(answer_now_context.get("partial_response") or "").strip()
        original_user_message = str(
            answer_now_context.get("original_user_message") or context.user_message
        ).strip()

        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-answer-now"),
            phase="responding",
            label=self._t("labels.answer_now", default="Answer now"),
            call_kind="llm_final_response",
            trace_id="chat-answer-now",
            trace_role="response",
            trace_group="stage",
        )
        async with stream.stage("responding", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta, {"trace_kind": "call_status", "call_state": "running"}
                ),
            )

            system_prompt = self._build_system_prompt(enabled_tools=[], context=context)
            messages = self._build_messages(
                context=context,
                system_prompt=system_prompt,
                user_content=original_user_message,
            )
            messages, _ = self._prepare_messages_with_attachments(messages, context)
            if partial_response:
                messages.append({"role": "assistant", "content": partial_response})
            messages.append(
                {"role": "user", "content": self._t("answer_now.user", default="Finalize now.")}
            )

            chunks: list[str] = []
            label_buf = ""
            label_resolved = False

            async def _emit_answer_chunk(text: str) -> None:
                if not text:
                    return
                chunks.append(text)
                await stream.content(
                    text,
                    source="chat",
                    stage="responding",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )

            async for chunk in self._stream_messages(
                messages, max_tokens=self._answer_now_max_tokens
            ):
                if not chunk:
                    continue
                if not label_resolved:
                    label_buf += chunk
                    parsed = _classify_answer_now_label(label_buf)
                    if parsed is not None:
                        # Answer-now reuses the normal chat system prompt, so
                        # many models correctly start with ``FINISH``. Strip
                        # that protocol label before it reaches the UI.
                        _label, after_label = parsed
                        label_resolved = True
                        label_buf = ""
                        await _emit_answer_chunk(after_label)
                    elif len(label_buf) > LABEL_PROBE_MAX_CHARS:
                        label_resolved = True
                        buffered = label_buf
                        label_buf = ""
                        await _emit_answer_chunk(buffered)
                    continue
                await _emit_answer_chunk(chunk)
            if not label_resolved and label_buf:
                parsed = _classify_answer_now_label(label_buf, final=True)
                if parsed is not None:
                    _label, after_label = parsed
                    await _emit_answer_chunk(after_label)
                else:
                    await _emit_answer_chunk(label_buf)
            await stream.progress(
                "",
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta, {"trace_kind": "call_status", "call_state": "complete"}
                ),
            )
            final_text = clean_thinking_tags("".join(chunks), self.binding, self.model)

        result_payload: dict[str, Any] = {
            "response": final_text,
            "answer_now": True,
            "source_trace": trace_meta.get("label", "Answer now"),
        }
        await emit_capability_result(stream, result_payload, source="chat", usage=self._usage)

    # ------------------------------------------------------------------
    # Per-iteration marker (tells the model where it is in the budget)
    # ------------------------------------------------------------------
    def _append_iteration_marker(
        self,
        *,
        messages: list[dict[str, Any]],
        iteration: int,
        max_iterations: int,
    ) -> None:
        """Append a ``role=user`` system-style note announcing the current
        iteration so the LLM can pace itself.

        Copy is YAML-driven (``iteration_marker``). Iteration is 0-indexed
        internally; the marker shows ``current = iteration + 1`` to match
        human counting. Markers from earlier iterations are kept in the
        history so the model can also see how it has been spending its
        budget across the turn.
        """
        current = iteration + 1
        marker = self._t(
            "iteration_marker",
            default=(
                f"[System note] You are at iteration {current}/{max_iterations} "
                "of this turn. Once the maximum is reached, the next reply is "
                "forced to be ``FINISH``."
            ),
            current=current,
            max=max_iterations,
        )
        marker = (marker or "").strip()
        if not marker:
            return
        messages.append({"role": "user", "content": marker})

    # ------------------------------------------------------------------
    # In-turn context-window guard
    # ------------------------------------------------------------------
    async def _guard_context_window(
        self,
        messages: list[dict[str, Any]],
        stream: StreamBus,
    ) -> None:
        """Replace oldest tool-result contents with a snip marker until the
        total token count fits under ``CONTEXT_WINDOW_GUARD_RATIO`` of the
        model's effective window. Never touches the system message or the
        original user message — only ``role == 'tool'`` payloads. Cross-turn
        history compression is handled separately by ``ContextBuilder``.
        """
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
            current_content = msg.get("content")
            if current_content == TOOL_RESULT_SNIP_MARKER:
                continue
            msg["content"] = TOOL_RESULT_SNIP_MARKER
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
        # Local import to break the agents.chat ↔ services.session import
        # cycle (context_builder pulls in agents.base_agent which re-enters
        # this module during package init).
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

    # ------------------------------------------------------------------
    # System prompt + message construction
    # ------------------------------------------------------------------
    def _build_system_prompt(
        self,
        enabled_tools: list[str],
        context: UnifiedContext,
    ) -> str:
        # ``list_with_usage`` renders one bullet per tool including the
        # tool's ``when_to_use`` and ``input_format`` — pulled from per-tool
        # YAML under ``deeptutor/tools/prompting/hints/{lang}/{tool}.yaml``.
        # This is the only place per-tool guidance enters the chat persona
        # prompt: disabled tools contribute nothing, so the model never sees
        # instructions for tools it cannot call.
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list_with_usage",
            language=self.language,
        )
        system = self._t(
            "system",
            tool_list=tool_list or self._fallback_empty_tool_list(),
            kb_note=self._kb_system_note(context),
        )
        return append_language_directive(system, self.language)

    def _append_reasoner_protocol_note(self, system_prompt: str) -> str:
        """Append a note for reasoning models that support native tool calling.

        Reasoning models (e.g. Qwen3.6-Plus) emit reasoning via
        ``reasoning_content`` and tool calls via native ``tool_calls``
        deltas. The label protocol (TOOL/THINK/FINISH/PAUSE) confuses
        them into writing tool-call JSON in ``content`` instead of using
        the native mechanism. This note tells them to ignore labels and
        use native tool calling directly.
        """
        if self.language == "zh":
            note = (
                "\n\n# 推理模型特别说明\n"
                "你是一个原生支持推理和工具调用的模型。"
                "请**忽略上面「输出协议」中关于 ``TOOL``/``THINK``/``FINISH``/``PAUSE`` 标签的指示**。"
                "你不需要在回复中输出任何标签。"
                "你的推理过程会自动在独立区域显示。"
                "当你需要调用工具时，直接通过原生 tool_calls 功能发起调用，不要在文本中写 JSON。"
                "当你准备好给出最终答案时，直接在回复正文中写出答案即可。"
            )
        else:
            note = (
                "\n\n# Reasoning Model Special Instructions\n"
                "You are a model with native reasoning and tool-calling support. "
                "Please **ignore the 'Output Protocol' instructions above about "
                "``TOOL``/``THINK``/``FINISH``/``PAUSE`` labels**. "
                "You do NOT need to output any labels in your replies. "
                "Your reasoning is automatically displayed in a separate area. "
                "When you need to call a tool, use native tool_calls directly — "
                "do NOT write JSON in your text output. "
                "When you are ready to give the final answer, just write it in your reply body."
            )
        return system_prompt + note

    def _build_messages(
        self,
        *,
        context: UnifiedContext,
        system_prompt: str,
        user_content: str,
    ) -> list[dict[str, Any]]:
        """Assemble ``[system] + history + user``.

        ``memory_context``, ``skills_context``, ``source_manifest``, and
        the notebook manifest are appended as separate ``---``-delimited
        sections after the main system prompt so prompt caching stays
        effective when only the manifest tail changes between turns.
        """
        system_parts = [system_prompt]
        if context.memory_context:
            system_parts.append(context.memory_context)
        if context.skills_context:
            system_parts.append(context.skills_context)
        if context.source_manifest:
            system_parts.append(context.source_manifest)
        notebook_manifest = self._build_notebook_manifest()
        if notebook_manifest:
            system_parts.append(notebook_manifest)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "\n\n---\n\n".join(system_parts)}
        ]
        for item in context.conversation_history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, (str, list)):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_content})
        return messages

    def _prepare_messages_with_attachments(
        self,
        messages: list[dict[str, Any]],
        context: UnifiedContext,
    ) -> tuple[list[dict[str, Any]], bool]:
        mm_result = prepare_multimodal_messages(
            messages,
            context.attachments,
            binding=self.binding,
            model=self.model,
        )
        return mm_result.messages, mm_result.images_stripped

    # ------------------------------------------------------------------
    # Tool selection + scheme construction
    # ------------------------------------------------------------------
    def _compose_enabled_tools(self, context: UnifiedContext) -> list[str]:
        """Resolve the tool set for this turn via the shared composition policy.

        Auto-mount flags are resolved against chat's own context:

        - ``has_kb`` — iff the user attached any KB.
        - ``has_sources`` — iff the turn has a non-empty source index
          (notebook / book / history / question / attachment).
        - ``has_memory`` — iff the active user has memory content.
        - ``has_notebooks`` — iff the active user has at least one notebook.
        """
        return compose_enabled_tools(
            registry=self.registry,
            requested_tools=context.enabled_tools,
            optional_whitelist=CHAT_OPTIONAL_TOOLS,
            mount_flags=ToolMountFlags(
                has_kb=bool(self._selected_kbs(context)),
                has_sources=bool(self._source_index(context)),
                has_memory=user_has_memory(),
                has_notebooks=user_has_notebooks(),
            ),
        )

    def _build_llm_tool_schemas(
        self,
        enabled_tools: list[str],
        context: UnifiedContext,
    ) -> list[dict[str, Any]]:
        """Return per-turn OpenAI tool schemas, with per-tool constraints.

        - ``rag.kb_name`` is restricted to the attached KBs as an enum.
        - ``read_source.source_id`` is restricted to the attached source
          ids as an enum (this makes the LLM less likely to hallucinate
          ids and lets the OpenAI SDK validate the call client-side).
        - ``save_to_notebook.notebook_id`` is restricted to the active
          user's actual notebook ids — mirrors the dropdown a human sees
          in the Save-to-Notebook dialog so the model literally cannot
          save into a notebook the user doesn't have.
        """
        schemas = self.registry.build_openai_schemas(enabled_tools)
        kb_choices = self._selected_kbs(context)
        source_ids = sorted((self._source_index(context) or {}).keys())
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
                query_schema = properties.get("query")
                if isinstance(query_schema, dict):
                    query_schema.setdefault("minLength", 1)
                kb_schema = properties.get("kb_name")
                if isinstance(kb_schema, dict):
                    kb_schema["enum"] = kb_choices
            if function.get("name") == "read_source" and isinstance(properties, dict):
                sid_schema = properties.get("source_id")
                if isinstance(sid_schema, dict) and source_ids:
                    sid_schema["enum"] = source_ids
            if function.get("name") == "geogebra_analysis" and isinstance(properties, dict):
                # ``image_base64`` is server-side injected from the turn's
                # image attachment; hide it from the LLM-visible schema so
                # the model doesn't try to fabricate a value.
                properties.pop("image_base64", None)
                required = parameters.get("required")
                if isinstance(required, list):
                    parameters["required"] = [name for name in required if name != "image_base64"]
            if (
                function.get("name") in {"list_notebook", "write_note"}
                and isinstance(properties, dict)
                and notebook_choices
            ):
                nb_schema = properties.get("notebook_id")
                if isinstance(nb_schema, dict):
                    nb_schema["enum"] = [choice["id"] for choice in notebook_choices]
                    nb_choices_render = "; ".join(
                        f"{c['id']} = {c['name']}" for c in notebook_choices
                    )
                    nb_schema["description"] = (
                        f"{nb_schema.get('description', '').rstrip(' .')}. "
                        f"Available: {nb_choices_render}."
                    )
            parameters["additionalProperties"] = False
        return schemas

    def _build_notebook_manifest(self) -> str:
        """Render the user's notebooks as a system-prompt index block.

        Always-on (when the user has notebooks): keeps the LLM grounded in
        the real notebook names + ids + record counts so it never invents
        notebook names when asking the user where to save. The block is
        tiny (one line per notebook), capped at ~30 entries to protect the
        context window. Heavy listing belongs to the ``list_notebook`` tool
        — this is the "always visible at a glance" affordance only.
        """
        choices = self._notebook_choices_full()
        if not choices:
            return ""
        capped = choices[:30]
        if self.language == "zh":
            lines = ["[用户的笔记本列表]"]
        else:
            lines = ["[User's notebooks]"]
        for entry in capped:
            nid = entry.get("id", "")
            name = entry.get("name", nid)
            count = entry.get("record_count", 0)
            lines.append(f"- `{nid}` — {name} ({count} records)")
        if len(choices) > len(capped):
            lines.append(
                f"… (+{len(choices) - len(capped)} more — call `list_notebook` to see the rest)"
            )
        if self.language == "zh":
            lines.append(
                "（要列出某笔记本里的具体记录，用 `list_notebook(notebook_id=...)`；要新增或编辑记录，用 `write_note`。）"
            )
        else:
            lines.append(
                "(Use `list_notebook(notebook_id=...)` to drill into one; use `write_note` to append / edit records.)"
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
            count = nb.get("record_count")
            if not isinstance(count, int):
                try:
                    count = int(count or 0)
                except (TypeError, ValueError):
                    count = 0
            rows.append({"id": nid, "name": name, "record_count": count})
        return rows

    @staticmethod
    def _notebook_choices() -> list[dict[str, str]]:
        """List the active user's notebooks as ``[{id, name}]`` rows."""
        try:
            from deeptutor.services.notebook import get_notebook_manager

            notebooks = get_notebook_manager().list_notebooks() or []
        except Exception:
            return []
        choices: list[dict[str, str]] = []
        for nb in notebooks:
            nid = str(nb.get("id") or "").strip()
            if not nid:
                continue
            name = str(nb.get("name") or nb.get("title") or nid).strip() or nid
            choices.append({"id": nid, "name": name})
        return choices

    @staticmethod
    def _extract_answer_now_context(context: UnifiedContext) -> dict[str, Any] | None:
        from deeptutor.capabilities._answer_now import extract_answer_now_context

        return extract_answer_now_context(context)

    # ------------------------------------------------------------------
    # Tool kwarg augmentation
    # ------------------------------------------------------------------
    def _augment_tool_kwargs(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        from deeptutor.services.path_service import get_path_service

        kwargs = dict(args)
        turn_id = str(context.metadata.get("turn_id", "") or "").strip()
        task_dir = None
        if turn_id:
            task_dir = get_path_service().get_task_workspace("chat", turn_id)
        if tool_name == "rag":
            kwargs.setdefault("mode", "hybrid")
        elif tool_name == "code_execution":
            kwargs.setdefault("intent", context.user_message)
            kwargs.setdefault("timeout", 30)
            kwargs.setdefault("feature", "chat")
            kwargs.setdefault("session_id", context.session_id)
            kwargs.setdefault("turn_id", turn_id)
            if task_dir is not None:
                kwargs.setdefault("workspace_dir", str(task_dir / "code_runs"))
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
        elif tool_name == "read_source":
            # ReadSourceTool reads from this per-turn map rather than from
            # any shared state, so each turn's sources stay isolated.
            kwargs["source_index"] = self._source_index(context)
        elif tool_name == "write_note":
            # The tool assembles the transcript body itself from the
            # conversation history (so the saved record is real Q&A, not
            # an LLM-authored summary). Inject the history snapshot +
            # current user message; the LLM never sees these as arguments
            # — they're stripped from the JSON schema and populated
            # server-side.
            kwargs["conversation_history"] = list(context.conversation_history or [])
            kwargs["current_user_message"] = context.user_message or ""
        elif tool_name == "geogebra_analysis":
            # The LLM never has access to the raw image bytes — we
            # unconditionally inject the first image attachment's base64
            # here (overwriting any value the LLM may have hallucinated
            # into the kwarg). Without this, the underlying
            # VisionSolverAgent would fail fast with "No image provided."
            first_image = next(
                (
                    att
                    for att in (context.attachments or [])
                    if getattr(att, "type", "") == "image" and getattr(att, "base64", "")
                ),
                None,
            )
            if first_image is not None:
                # Attachment.base64 is the raw base64 payload (no data-URI
                # prefix), but VisionSolverAgent feeds the value straight into
                # an OpenAI ``image_url.url`` field which requires the data
                # URI form. Wrap it here so the vision LLM accepts the image
                # instead of silently failing all four pipeline stages.
                raw_b64 = first_image.base64
                if raw_b64.startswith("data:"):
                    kwargs["image_base64"] = raw_b64
                else:
                    mime = getattr(first_image, "mime_type", "") or "image/png"
                    kwargs["image_base64"] = f"data:{mime};base64,{raw_b64}"
            # Force the session language; this tool does not expose ``language``
            # as an LLM-visible parameter, so an override here would only come
            # from a hallucinated kwarg.
            kwargs["language"] = context.language or "zh"
        return kwargs

    # ------------------------------------------------------------------
    # Tool / KB metadata helpers
    # ------------------------------------------------------------------
    def _retrieve_trace_metadata(
        self,
        tool_meta: dict[str, Any],
        *,
        context: UnifiedContext,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Retrieve-flavoured metadata for ``rag`` progress events.

        Each rag call already has its own ``tool_meta`` (with its own
        ``call_id``); we derive a "retrieve" variant of it so the in-tool
        progress events (provider selection, chunk retrieval, etc.) stay
        attached to the same sub-trace but show as
        ``trace_role=retrieve`` for the chevron icon. For non-rag tools
        we return ``None`` so the executor skips the retrieve-progress
        surface.
        """
        if tool_name != "rag":
            return None
        _ = context  # context unused for now; kept for parity with solve's variant
        return derive_trace_metadata(
            tool_meta,
            label=self._t("labels.retrieve", default="Retrieve"),
            call_kind="rag_retrieval",
            trace_role="retrieve",
            trace_group="retrieve",
            query=str(tool_args.get("query", "") or ""),
        )

    @staticmethod
    def _selected_kbs(context: UnifiedContext) -> list[str]:
        return [str(kb).strip() for kb in context.knowledge_bases if str(kb).strip()]

    @staticmethod
    def _source_index(context: UnifiedContext) -> dict[str, str]:
        idx = context.metadata.get("source_index")
        if isinstance(idx, dict) and idx:
            return idx
        return {}

    def _kb_system_note(self, context: UnifiedContext) -> str:
        kbs = self._selected_kbs(context)
        if not kbs:
            return ""
        joined = ", ".join(kbs)
        if self.language == "zh":
            return f"用户已挂载知识库：{joined}。调用 rag 时，kb_name 必须从其中选一个。"
        return (
            f"Attached knowledge bases: {joined}. When calling rag, kb_name must "
            "be one of these names."
        )

    def _fallback_empty_tool_list(self) -> str:
        return "- 无" if self.language == "zh" else "- none"

    # ------------------------------------------------------------------
    # LLM call helpers
    # ------------------------------------------------------------------
    async def _stream_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ):
        """Stream a single tool-less LLM call. Used by answer-now."""
        output_chars = 0
        async for chunk in llm_stream(
            prompt="",
            system_prompt="",
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            messages=messages,
            extra_headers=self.extra_headers or None,
            **self._completion_kwargs(max_tokens=max_tokens),
        ):
            output_chars += len(chunk)
            yield chunk
        input_chars = sum(len(str(m.get("content", ""))) for m in messages)
        self._usage.add_estimated(input_chars=input_chars, output_chars=output_chars)

    def _build_openai_client(self):
        """Build an OpenAI/Azure async client from the pipeline's LLM config.

        Kept as a method (rather than always reusing ``self._client``) so any
        downstream test or future caller that wants a fresh client per call
        can still get one without poking at module-level state.
        """
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

    # ------------------------------------------------------------------
    # YAML prompt lookup
    # ------------------------------------------------------------------
    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        """Look up a YAML-loaded prompt by dotted key.

        Returns ``default`` when missing. Renders via ``str.format`` when
        ``kwargs`` are provided; missing placeholders leave the template
        unrendered instead of crashing the pipeline.
        """
        value: Any = self._prompts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        if not isinstance(value, str):
            return default
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return value
        return value


# ---------------------------------------------------------------------------
# Loop host adapter
# ---------------------------------------------------------------------------


class _ChatLoopHost:
    """Bind the chat pipeline + current turn's context/stream into a single
    object the generic loop primitive can call back into.

    All chat-specific behavior — trace metadata, tool dispatch, pause/terminate,
    final emission, force-finalize — lives as methods on
    :class:`AgenticChatPipeline`; this adapter just routes the
    :class:`~deeptutor.core.agentic.LoopHost` protocol calls to them.
    """

    def __init__(
        self,
        *,
        pipeline: AgenticChatPipeline,
        context: UnifiedContext,
        stream: StreamBus,
        client: Any,
    ) -> None:
        self._pipeline = pipeline
        self._context = context
        self._stream = stream
        self._client = client

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        await self._pipeline._guard_context_window(messages, self._stream)

    async def before_iteration(
        self,
        *,
        messages: list[dict[str, Any]],
        iteration: int,
        max_iterations: int,
    ) -> None:
        """Inject the per-iteration counter so the model can pace itself."""
        self._pipeline._append_iteration_marker(
            messages=messages,
            iteration=iteration,
            max_iterations=max_iterations,
        )

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        return self._pipeline._build_iteration_trace_metadata(iteration)

    async def dispatch_tools(
        self,
        *,
        iteration: int,
        tool_calls: list[dict[str, Any]],
    ) -> DispatchOutcome:
        return await self._pipeline._dispatch_tool_calls(
            tool_calls=tool_calls,
            context=self._context,
            stream=self._stream,
            iteration_index=iteration,
        )

    async def resolve_pause(self, dispatch: DispatchOutcome) -> bool:
        return await self._pipeline._await_user_reply_and_resolve(
            context=self._context,
            stream=self._stream,
            dispatch=dispatch,
        )

    async def emit_terminator(self, payload: dict[str, Any] | None) -> None:
        await self._pipeline._emit_terminator_final_response(self._stream, payload)

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        await self._pipeline._emit_final_text(self._stream, text, final_meta)

    def assistant_message_with_tool_calls(
        self,
        *,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._pipeline._assistant_message_with_tool_calls(content, tool_calls)

    def protocol_retry_notice(self) -> str:
        return self._pipeline._protocol_retry_notice()

    def protocol_repair_message(self, violation: str) -> str:
        return self._pipeline._protocol_repair_message(violation)

    async def force_finalize(
        self,
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        return await self._pipeline._run_forced_finish(
            client=self._client,
            messages=messages,
            stream=self._stream,
            start_iteration=start_iteration,
        )


# ---------------------------------------------------------------------------
# Forced-finish protocol validation (chat-local because the violation key
# vocabulary mirrors chat's repair-copy keys).
# ---------------------------------------------------------------------------


def _classify_forced_finish_violation(step: LabeledStepResult) -> str | None:
    """Lightweight violation classifier for the FINISH-only finalization
    loop. With ``allowed_labels=(FINISH,)`` and ``tool_schemas=None``, the
    only possible violations are missing label / inline duplicate label.
    """
    if step.label == LABEL_UNKNOWN:
        return "missing_label"
    if find_inline_labels(
        step.text,
        allowed_labels=(LABEL_FINISH, LABEL_TOOL, LABEL_THINK, LABEL_PAUSE),
    ):
        return "multiple_labels"
    return None
