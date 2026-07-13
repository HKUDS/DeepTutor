"""Agentic context investigator.

The investigator is a read-only pre-pass that runs *before* the answer loop's
first LLM call. Given the user's request and the manifest of the turn's
attached sources, it freely interleaves the ``read_source`` tool to load the
sources it actually needs, follows leads across them, and produces one
objective, third-person investigation the answer loop consumes as grounding.

``read_source`` lives **only** here: the answer loop no longer mounts it, so
loading attached-source full text is wholly owned by this pre-pass. The
investigation it returns is the answer loop's window into the sources — it
never streams CONTENT events, so it can never be mistaken for the turn's
user-facing answer.

Two execution paths:

* **Native tool calling** (:meth:`_run_loop`) — the agentic investigation: a
  bounded loop of LLM call → ``read_source`` dispatch → repeat, until the model
  stops calling tools and writes its investigation.
* **Fallback** (:meth:`_single_pass`) — for providers without native tool
  calling (or when the loop fails): the original dump-the-source-text-and-brief
  single pass, modelled on :class:`~deeptutor.agents.notebook.analysis_agent`.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
import logging
from typing import Any, Callable

from deeptutor.core.agentic import (
    LLMClientConfig,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
    dispatch_tool_calls,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata, new_call_id
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.llm import clean_thinking_tags, get_llm_config, get_token_limit_kwargs
from deeptutor.services.llm import stream as llm_stream

logger = logging.getLogger(__name__)

# Trace identity. ``source="chat"`` keeps the pre-pass in the turn's existing
# activity lane; the dedicated stage gives it its own labelled group. The
# frontend keys its "Exploring your context…" status and "Context exploration"
# row header off ``call_kind="context_exploration"`` / ``stage`` — see
# ``web/components/chat/home/TracePanels.tsx``.
EXPLORE_STAGE = "context_exploration"
EXPLORE_SOURCE = "chat"

# Agentic-loop budget: at most this many LLM rounds; the model normally
# finishes earlier by writing its investigation without a tool call. The last
# round runs with tools disabled so it is always forced to finish.
MAX_LOOP_ROUNDS = 5
LOOP_MAX_TOKENS = 2000

# Single-pass fallback budgets. The same sources remain reachable via
# ``read_source`` in the loop path, so clipping here only bounds the fallback.
MAX_SOURCES = 12
CHARS_PER_SOURCE = 8000
TOTAL_CHARS = 48000
BRIEFING_MAX_TOKENS = 1400

# Maps a manifest source-id prefix to a human kind label (en, zh).
_KIND_BY_PREFIX: dict[str, tuple[str, str]] = {
    "hs-": ("Conversation transcript", "对话记录"),
    "nb-": ("Notebook record", "笔记本记录"),
    "bk-": ("Book excerpt", "书籍节选"),
    "qb-": ("Question-bank entry", "题库条目"),
    "at-": ("Document", "文档"),
}


@dataclass(slots=True)
class _CallResult:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    output_chars: int = 0


class ContextExplorer:
    """Investigate the turn's attached sources and return an objective briefing."""

    def __init__(self, *, language: str, prompts: dict[str, Any]) -> None:
        self.language = "zh" if str(language or "en").lower().startswith("zh") else "en"
        self._prompts = prompts or {}
        cfg = get_llm_config()
        self.model = getattr(cfg, "model", None)
        self.api_key = getattr(cfg, "api_key", None)
        self.base_url = getattr(cfg, "base_url", None)
        self.api_version = getattr(cfg, "api_version", None)
        self.binding = getattr(cfg, "binding", None) or "openai"
        self.extra_headers = getattr(cfg, "extra_headers", None) or {}
        self.reasoning_effort = getattr(cfg, "reasoning_effort", None)
        self.registry = get_tool_registry()
        self._client_config = LLMClientConfig(
            binding=self.binding,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            extra_headers=self.extra_headers or None,
            reasoning_effort=self.reasoning_effort,
        )

    async def investigate(
        self,
        *,
        context: UnifiedContext,
        stream: StreamBus,
        usage: Any | None = None,
    ) -> str:
        """Run the pre-pass and return the investigation wrapped in its header.

        Returns ``""`` when there is nothing to investigate or every path
        fails, so the caller can simply skip injection.
        """
        source_index = self._source_index(context)
        if not source_index:
            return ""

        investigation = ""
        if can_use_native_tool_calling(binding=self.binding, model=self.model):
            try:
                investigation = await self._run_loop(context, stream, source_index, usage)
            except Exception:
                logger.warning(
                    "context exploration loop failed; falling back to single pass",
                    exc_info=True,
                )
                investigation = ""
        # Non-native providers, or a failed/empty loop, degrade to the robust
        # dump-and-brief single pass so the answer loop is never left without
        # grounding (it can no longer read sources itself).
        if not investigation.strip():
            investigation = await self._single_pass(context, stream, source_index, usage)

        investigation = clean_thinking_tags(investigation, self.binding, self.model).strip()
        if not investigation:
            return ""
        return f"{self._briefing_header()}\n\n{investigation}".strip()

    # ---- agentic loop ----------------------------------------------------

    async def _run_loop(
        self,
        context: UnifiedContext,
        stream: StreamBus,
        source_index: dict[str, str],
        usage: Any | None,
    ) -> str:
        system_prompt = self._t("loop.system")
        user_template = self._t("loop.user_template")
        if not system_prompt or not user_template:
            logger.warning("explore_context loop prompts missing; using single pass")
            return ""

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_template.format(
                    question=(context.user_message or "").strip() or "(empty)",
                    mode=str(context.active_capability or "chat"),
                    manifest=(context.source_manifest or "").strip() or "(none)",
                ),
            },
        ]
        tool_schemas = self._read_source_schemas(source_index)
        augmenter = self._augmenter(source_index)
        client = build_openai_client(self._client_config)

        call_id = new_call_id("explore-context")
        stage_meta = build_trace_metadata(
            call_id=call_id,
            phase=EXPLORE_STAGE,
            label=self._status_exploring(),
            call_kind="context_exploration",
            trace_id=call_id,
            trace_role="explore",
            trace_group="stage",
        )
        chunk_meta = merge_trace_metadata(stage_meta, {"trace_kind": "llm_chunk"})

        investigation = ""
        total_in = 0
        total_out = 0
        async with stream.stage(EXPLORE_STAGE, source=EXPLORE_SOURCE, metadata=stage_meta):
            await stream.progress(
                self._status_exploring(),
                source=EXPLORE_SOURCE,
                stage=EXPLORE_STAGE,
                metadata=merge_trace_metadata(
                    stage_meta, {"trace_kind": "call_status", "call_state": "running"}
                ),
            )
            for round_idx in range(MAX_LOOP_ROUNDS):
                is_last = round_idx == MAX_LOOP_ROUNDS - 1
                if is_last:
                    # Budget exhausted while still calling tools — force a
                    # tool-less finish from what has been gathered.
                    messages.append({"role": "user", "content": self._forced_finish_instruction()})
                total_in += sum(_content_chars(m) for m in messages)
                result = await self._call_llm(
                    client, messages, tool_schemas if not is_last else None, chunk_meta, stream
                )
                total_out += result.output_chars
                if not result.tool_calls:
                    investigation = result.text
                    break
                messages.append(_assistant_with_tool_calls(result.text, result.tool_calls))
                dispatch = await dispatch_tool_calls(
                    tool_calls=result.tool_calls,
                    context=context,
                    stream=stream,
                    source=EXPLORE_SOURCE,
                    stage=EXPLORE_STAGE,
                    iteration_index=round_idx,
                    registry=self.registry,
                    kwarg_augmenter=augmenter,
                    tool_call_label=self._t("labels.tool_call", default="Tool call"),
                    trace_id_prefix="explore-context",
                )
                messages.extend(dispatch.tool_messages)
            await stream.progress(
                "",
                source=EXPLORE_SOURCE,
                stage=EXPLORE_STAGE,
                metadata=merge_trace_metadata(
                    stage_meta, {"trace_kind": "call_status", "call_state": "complete"}
                ),
            )

        self._account_usage(usage, total_in, total_out, investigation)
        return investigation

    async def _call_llm(
        self,
        client: Any,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]] | None,
        chunk_meta: dict[str, Any],
        stream: StreamBus,
    ) -> _CallResult:
        """One streamed LLM call. All output streams to the *thinking* channel
        (never CONTENT — that is the answer loop's channel); the returned text
        is the round's investigation when it carries no tool calls."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            **build_completion_kwargs(
                temperature=0.2,
                model=self.model,
                max_tokens=LOOP_MAX_TOKENS,
                binding=self.binding,
                reasoning_effort=self.reasoning_effort,
            ),
        }
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"

        text_parts: list[str] = []
        tool_acc: dict[int, dict[str, str]] = {}
        output_chars = 0
        response_stream = await client.chat.completions.create(**kwargs)
        try:
            async for chunk in response_stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                reasoning = getattr(delta, "reasoning_content", None) or getattr(
                    delta, "reasoning", None
                )
                if reasoning:
                    output_chars += len(reasoning)
                    await stream.thinking(
                        reasoning, source=EXPLORE_SOURCE, stage=EXPLORE_STAGE, metadata=chunk_meta
                    )
                content = getattr(delta, "content", None)
                if content:
                    output_chars += len(content)
                    text_parts.append(content)
                    await stream.thinking(
                        content, source=EXPLORE_SOURCE, stage=EXPLORE_STAGE, metadata=chunk_meta
                    )
                for tc in getattr(delta, "tool_calls", None) or []:
                    index = int(getattr(tc, "index", 0) or 0)
                    acc = tool_acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    tcid = getattr(tc, "id", None)
                    if tcid:
                        acc["id"] += str(tcid)
                    fn = getattr(tc, "function", None)
                    if fn is None:
                        continue
                    name = getattr(fn, "name", None)
                    arguments = getattr(fn, "arguments", None)
                    if name:
                        acc["name"] += str(name)
                        output_chars += len(str(name))
                    if arguments:
                        acc["arguments"] += str(arguments)
                        output_chars += len(str(arguments))
        finally:
            close = getattr(response_stream, "close", None)
            if callable(close):
                with suppress(Exception):
                    await close()

        tool_calls = [
            {
                "id": data.get("id") or f"call_{idx}",
                "name": data.get("name", ""),
                "arguments": data.get("arguments") or "{}",
            }
            for idx, data in sorted(tool_acc.items())
            if data.get("name")
        ]
        return _CallResult(
            text="".join(text_parts), tool_calls=tool_calls, output_chars=output_chars
        )

    def _read_source_schemas(self, source_index: dict[str, str]) -> list[dict[str, Any]]:
        schemas = self.registry.build_openai_schemas(["read_source"])
        source_ids = sorted(source_index.keys())
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            if not isinstance(function, dict):
                continue
            parameters = function.get("parameters")
            if not isinstance(parameters, dict):
                continue
            properties = parameters.get("properties") or {}
            if (
                function.get("name") == "read_source"
                and isinstance(properties.get("source_id"), dict)
                and source_ids
            ):
                properties["source_id"]["enum"] = source_ids
            parameters["additionalProperties"] = False
        return schemas

    @staticmethod
    def _augmenter(source_index: dict[str, str]) -> Callable[..., dict[str, Any]]:
        def _augment(tool_name: str, args: dict[str, Any], _ctx: UnifiedContext) -> dict[str, Any]:
            kwargs = dict(args)
            if tool_name == "read_source":
                kwargs["source_index"] = source_index
            return kwargs

        return _augment

    # ---- single-pass fallback -------------------------------------------

    async def _single_pass(
        self,
        context: UnifiedContext,
        stream: StreamBus,
        source_index: dict[str, str],
        usage: Any | None,
    ) -> str:
        sources_text = self._render_source_blocks(source_index)
        if not sources_text:
            return ""
        system_prompt = self._t("system")
        user_template = self._t("user_template")
        if not system_prompt or not user_template:
            logger.warning("explore_context single-pass prompts missing; skipping pre-pass")
            return ""
        user_prompt = user_template.format(
            question=(context.user_message or "").strip() or "(empty)",
            mode=str(context.active_capability or "chat"),
            manifest=(context.source_manifest or "").strip() or "(none)",
            sources=sources_text,
        )

        call_id = new_call_id("explore-context")
        stage_meta = build_trace_metadata(
            call_id=call_id,
            phase=EXPLORE_STAGE,
            label=self._status_exploring(),
            call_kind="context_exploration",
            trace_id=call_id,
            trace_role="explore",
            trace_group="stage",
        )
        chunk_meta = merge_trace_metadata(stage_meta, {"trace_kind": "llm_chunk"})
        chunks: list[str] = []
        async with stream.stage(EXPLORE_STAGE, source=EXPLORE_SOURCE, metadata=stage_meta):
            await stream.progress(
                self._status_exploring(),
                source=EXPLORE_SOURCE,
                stage=EXPLORE_STAGE,
                metadata=merge_trace_metadata(
                    stage_meta, {"trace_kind": "call_status", "call_state": "running"}
                ),
            )
            try:
                async for chunk in llm_stream(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    model=self.model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    api_version=self.api_version,
                    binding=self.binding,
                    temperature=0.2,
                    **self._token_kwargs(BRIEFING_MAX_TOKENS),
                ):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    await stream.thinking(
                        chunk, source=EXPLORE_SOURCE, stage=EXPLORE_STAGE, metadata=chunk_meta
                    )
            except Exception:
                logger.warning("context exploration single pass failed", exc_info=True)
            await stream.progress(
                "",
                source=EXPLORE_SOURCE,
                stage=EXPLORE_STAGE,
                metadata=merge_trace_metadata(
                    stage_meta, {"trace_kind": "call_status", "call_state": "complete"}
                ),
            )

        briefing = clean_thinking_tags("".join(chunks), self.binding, self.model).strip()
        self._account_usage(usage, len(system_prompt) + len(user_prompt), len(briefing), briefing)
        return briefing

    def _render_source_blocks(self, source_index: dict[str, str]) -> str:
        blocks: list[str] = []
        total = 0
        for sid, text in source_index.items():
            body = str(text or "").strip()
            if not body:
                continue
            if len(blocks) >= MAX_SOURCES or total >= TOTAL_CHARS:
                break
            remaining = TOTAL_CHARS - total
            clipped = self._clip(body, min(CHARS_PER_SOURCE, remaining))
            blocks.append(f"### [{sid}] ({self._kind_label(sid)})\n{clipped}")
            total += len(clipped)
        return "\n\n".join(blocks)

    def _kind_label(self, sid: str) -> str:
        for prefix, (en, zh) in _KIND_BY_PREFIX.items():
            if sid.startswith(prefix):
                return zh if self.language == "zh" else en
        return "来源" if self.language == "zh" else "Source"

    def _clip(self, text: str, limit: int) -> str:
        text = (text or "").strip()
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        note = "\n…（已截断）" if self.language == "zh" else "\n…(truncated)"
        return text[:limit].rstrip() + note

    # ---- shared helpers --------------------------------------------------

    def _account_usage(
        self, usage: Any | None, input_chars: int, output_chars: int, produced: str
    ) -> None:
        if usage is None or not produced.strip():
            return
        try:
            usage.add_estimated(input_chars=input_chars, output_chars=output_chars)
        except Exception:  # pragma: no cover - usage accounting is best-effort
            logger.debug("explore_context usage accounting failed", exc_info=True)

    @staticmethod
    def _source_index(context: UnifiedContext) -> dict[str, str]:
        idx = context.metadata.get("source_index")
        if isinstance(idx, dict) and idx:
            return {str(k): str(v) for k, v in idx.items()}
        return {}

    def _token_kwargs(self, max_tokens: int) -> dict[str, Any]:
        if not self.model:
            return {}
        return get_token_limit_kwargs(self.model, max_tokens)

    def _t(self, key: str, default: str = "") -> str:
        value: Any = self._prompts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value.strip() if isinstance(value, str) else default

    def _forced_finish_instruction(self) -> str:
        return self._t(
            "loop.forced_finish",
            default=(
                "Investigation budget reached. Stop calling tools and write your "
                "objective, detailed investigation now from what you have gathered."
            ),
        )

    def _status_exploring(self) -> str:
        return self._t(
            "status.exploring",
            default="上下文调查" if self.language == "zh" else "Context exploration",
        )

    def _briefing_header(self) -> str:
        return self._t("briefing_header", default="[Context Investigation]")


def _content_chars(message: dict[str, Any]) -> int:
    content = message.get("content")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(str(part.get("text") or "")) for part in content if isinstance(part, dict))
    return 0


def _assistant_with_tool_calls(content: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc.get("arguments") or "{}"},
            }
            for tc in tool_calls
        ],
    }


__all__ = ["ContextExplorer", "EXPLORE_STAGE"]
