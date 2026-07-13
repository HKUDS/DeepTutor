"""Parallel tool-call dispatch with per-tool sub-traces.

Lifted from chat's pipeline. Capability-agnostic: the caller supplies:

* a ``KwargAugmenter`` — how to enrich the LLM-supplied tool args with
  server-side context (e.g. chat injects ``source_index`` for ``read_source``;
  solve will do the same for its own tools).
* a ``RetrieveMetaFactory`` — how to derive a "retrieve" trace variant for
  rag-flavored tools (so their internal progress events stay grouped under
  the same sub-trace icon).
* labels for the trace UI rows (``tool_call``, ``retrieve``) plus the
  capability-specific copy for empty results / over-quota / unknown errors.

The dispatcher executes all tool calls in parallel, emits one sub-trace per
tool call, and returns a :class:`DispatchOutcome` carrying the role=tool
messages, accumulated sources, and pause/terminate signals for the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import logging
from typing import Any

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)
from deeptutor.runtime.registry.tool_registry import ToolRegistry, get_tool_registry
from deeptutor.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

MAX_PARALLEL_TOOL_CALLS = 8


KwargAugmenter = Callable[[str, dict[str, Any], UnifiedContext], dict[str, Any]]
RetrieveMetaFactory = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any] | None]
UnknownErrorMessageFactory = Callable[[str], str]


@dataclass(frozen=True)
class DispatchOutcome:
    """Aggregated result of one iteration's tool dispatch.

    * ``terminate`` — a tool requested the loop end after this iteration; its
      content becomes the terminal assistant artefact. No built-in chat tool
      currently uses this; ``ask_user`` switched to ``pause`` instead.
    * ``pause`` (e.g. ``ask_user``) — the turn stays alive; the caller awaits
      a user reply, substitutes it into the matching ``role=tool`` message,
      and resumes iterating. The first tool to request pause wins; other
      parallel tools still execute and their results ride along.
    """

    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_messages: list[dict[str, Any]] = field(default_factory=list)
    tool_metadata_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    terminate: bool = False
    terminate_payload: dict[str, Any] | None = None
    pause: bool = False
    pause_payload: dict[str, Any] | None = None
    pause_tool_call_id: str | None = None


async def dispatch_tool_calls(
    *,
    tool_calls: list[dict[str, Any]],
    context: UnifiedContext,
    stream: StreamBus,
    source: str,
    stage: str,
    iteration_index: int,
    registry: ToolRegistry | None = None,
    kwarg_augmenter: KwargAugmenter | None = None,
    retrieve_meta_factory: RetrieveMetaFactory | None = None,
    tool_call_label: str = "Tool call",
    retrieve_label: str = "Retrieve",
    empty_tool_result_message: str = "",
    start_retrieval_message: str = "Starting retrieval",
    too_many_tool_calls_message: str | None = None,
    unknown_error_message_factory: UnknownErrorMessageFactory | None = None,
    trace_id_prefix: str = "iter",
) -> DispatchOutcome:
    """Execute tool calls in parallel and assemble a :class:`DispatchOutcome`."""
    registry = registry or get_tool_registry()

    if len(tool_calls) > MAX_PARALLEL_TOOL_CALLS:
        if too_many_tool_calls_message:
            await stream.progress(
                too_many_tool_calls_message,
                source=source,
                stage=stage,
                metadata={"trace_kind": "warning"},
            )
        tool_calls = tool_calls[:MAX_PARALLEL_TOOL_CALLS]

    prepared = _prepare_tool_args(tool_calls, context, kwarg_augmenter)
    # Collapse duplicates within this parallel batch. Models occasionally
    # emit repeated tool_calls in one assistant message. For most tools,
    # "duplicate" means same tool + same JSON-normalised args. For
    # ``ask_user``, any second call in the same batch is a duplicate even
    # when args differ: multiple ask_user calls would render multiple
    # cards while the runtime can only pause on one reply.
    #
    # The first occurrence runs as normal; later duplicates short-circuit
    # to a stub role=tool result so OpenAI's tool-call/tool-message pairing
    # stays intact for the next API call. Duplicate ``ask_user`` calls are
    # also hidden from the user-facing trace stream to avoid duplicate Ask
    # Me rows/cards during the live turn.
    duplicate_of = _detect_duplicate_calls(prepared)
    suppress_ui_indices = {idx for idx in duplicate_of if prepared[idx][1] == "ask_user"}
    per_tool_trace_meta = _build_per_tool_trace_meta(
        prepared,
        context=context,
        iteration_index=iteration_index,
        stage=stage,
        tool_call_label=tool_call_label,
        trace_id_prefix=trace_id_prefix,
    )

    for tool_index, (_tcid, tool_name, exec_args) in enumerate(prepared):
        if tool_index in suppress_ui_indices:
            continue
        # Strip server-injected private kwargs (``_sandbox_mounts`` & co.)
        # from the event payload: they are execution plumbing, not display
        # args, and may not be JSON-serializable (a Mount dataclass in the
        # event killed both the WS push and turn persistence).
        display_args = {k: v for k, v in exec_args.items() if not k.startswith("_")}
        await stream.tool_call(
            tool_name=tool_name,
            args=display_args,
            source=source,
            stage=stage,
            metadata=merge_trace_metadata(
                per_tool_trace_meta[tool_index],
                {"trace_kind": "tool_call"},
            ),
        )

    async def _run_one(tool_index: int) -> dict[str, Any]:
        primary_idx = duplicate_of.get(tool_index)
        if primary_idx is not None:
            primary_call_id = prepared[primary_idx][0]
            return _duplicate_stub_result(
                primary_call_id=primary_call_id,
                tool_name=prepared[tool_index][1],
            )
        _tcid, tool_name, exec_args = prepared[tool_index]
        return await execute_tool_call(
            registry=registry,
            tool_name=tool_name,
            tool_args=exec_args,
            stream=stream,
            source=source,
            stage=stage,
            retrieve_meta=(
                retrieve_meta_factory(
                    per_tool_trace_meta[tool_index],
                    tool_name,
                    exec_args,
                )
                if retrieve_meta_factory
                else None
            ),
            empty_tool_result_message=empty_tool_result_message,
            start_retrieval_message=start_retrieval_message,
            unknown_error_message_factory=unknown_error_message_factory,
            retrieve_label=retrieve_label,
        )

    results = await asyncio.gather(*[_run_one(i) for i in range(len(prepared))])

    return await _collect_outcome(
        prepared=prepared,
        results=results,
        per_tool_trace_meta=per_tool_trace_meta,
        suppress_ui_indices=suppress_ui_indices,
        stream=stream,
        source=source,
        stage=stage,
    )


def _detect_duplicate_calls(
    prepared: list[tuple[str, str, dict[str, Any]]],
) -> dict[int, int]:
    """Map duplicate-call indices to their primary occurrence.

    Two calls are duplicates when their (tool_name, JSON-normalised
    args) keys are identical. ``ask_user`` is stricter: the first
    ``ask_user`` call is the primary and every later ``ask_user`` in the
    same parallel batch maps to it, regardless of args, because the UI and
    pause/resume runtime only support one pending Ask Me card per model
    tool batch. Non-serialisable args fall through to ``str()`` so unusual
    values still produce a deterministic key.
    """
    duplicate_of: dict[int, int] = {}
    seen: dict[tuple[str, str], int] = {}
    first_ask_user_idx: int | None = None
    for idx, (_tcid, tool_name, exec_args) in enumerate(prepared):
        if tool_name == "ask_user":
            if first_ask_user_idx is not None:
                duplicate_of[idx] = first_ask_user_idx
                continue
            first_ask_user_idx = idx
        try:
            args_key = json.dumps(exec_args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args_key = str(exec_args)
        key = (tool_name, args_key)
        primary = seen.get(key)
        if primary is None:
            seen[key] = idx
        else:
            duplicate_of[idx] = primary
    return duplicate_of


def _duplicate_stub_result(
    *,
    primary_call_id: str,
    tool_name: str,
) -> dict[str, Any]:
    """Synthetic result for a duplicate parallel tool_call.

    Carries no ``pause_for_user`` / ``terminate_turn`` / ``metadata`` so
    only the primary call drives pause/terminate decisions and the
    frontend renders a single card. The ``result_text`` is a directive
    aimed at the model: a one-line explanation it can read in the next
    iteration so it learns not to emit identical parallel tool_calls.
    """
    if tool_name == "ask_user":
        result_text = (
            "(duplicate parallel ask_user tool_call — skipped. The earlier "
            f"ask_user call with id={primary_call_id!r} is the only one that "
            "will pause for the user's reply. Ask all clarifying questions in "
            "one ask_user call's `questions` list; never emit multiple "
            "ask_user tool_calls in one assistant message.)"
        )
    else:
        result_text = (
            "(duplicate parallel tool_call — skipped. The identical call "
            f"with id={primary_call_id!r} already ran in this batch; "
            "see its result. Do NOT emit two identical tool_calls in one "
            "assistant message — parallel calls must differ in arguments.)"
        )
    return {
        "result_text": result_text,
        "sources": [],
    }


def _prepare_tool_args(
    tool_calls: list[dict[str, Any]],
    context: UnifiedContext,
    kwarg_augmenter: KwargAugmenter | None,
) -> list[tuple[str, str, dict[str, Any]]]:
    prepared: list[tuple[str, str, dict[str, Any]]] = []
    for tc in tool_calls:
        tool_name = str(tc.get("name") or "").strip()
        tool_call_id = str(tc.get("id") or "").strip()
        tool_args = parse_json_response(
            tc.get("arguments") or "{}",
            logger_instance=logger,
            fallback={},
        )
        if not isinstance(tool_args, dict):
            tool_args = {}
        exec_args = (
            kwarg_augmenter(tool_name, tool_args, context)
            if kwarg_augmenter is not None
            else dict(tool_args)
        )
        prepared.append((tool_call_id, tool_name, exec_args))
    return prepared


def _build_per_tool_trace_meta(
    prepared: list[tuple[str, str, dict[str, Any]]],
    *,
    context: UnifiedContext,
    iteration_index: int,
    stage: str,
    tool_call_label: str,
    trace_id_prefix: str,
) -> list[dict[str, Any]]:
    """Allocate a fresh trace ``call_id`` for each tool so each appears as its
    own sub-trace row in the frontend's CallTracePanel."""
    metas: list[dict[str, Any]] = []
    for tool_index, (tool_call_id, tool_name, _exec_args) in enumerate(prepared):
        trace_call_id = new_call_id(f"{trace_id_prefix}-{iteration_index}-tool-{tool_index}")
        base_meta = build_trace_metadata(
            call_id=trace_call_id,
            phase=stage,
            label=tool_call_label,
            call_kind="tool_planning",
            trace_id=trace_call_id,
            trace_role="tool",
            trace_group="tool_call",
        )
        metas.append(
            merge_trace_metadata(
                base_meta,
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "tool_index": tool_index,
                    "iteration_index": iteration_index,
                    "session_id": context.session_id,
                    "turn_id": str(context.metadata.get("turn_id", "")),
                },
            )
        )
    return metas


async def execute_tool_call(
    *,
    registry: ToolRegistry,
    tool_name: str,
    tool_args: dict[str, Any],
    stream: StreamBus,
    source: str,
    stage: str,
    retrieve_meta: dict[str, Any] | None,
    empty_tool_result_message: str = "",
    start_retrieval_message: str = "Starting retrieval",
    retrieve_label: str = "Retrieve",
    unknown_error_message_factory: UnknownErrorMessageFactory | None = None,
) -> dict[str, Any]:
    """Run one tool, emitting retrieve-flavored progress events when relevant.

    Returns a structured ``{result_text, success, sources, metadata,
    terminate_turn, pause_for_user}`` dict (same shape the dispatcher uses
    internally). Capabilities that want to invoke a single tool outside the
    parallel-dispatch path call this directly.
    """

    async def _event_sink(
        event_type: str,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if retrieve_meta is None or not message:
            return
        await stream.progress(
            message,
            source=source,
            stage=stage,
            metadata=derive_trace_metadata(
                retrieve_meta,
                trace_kind=str(event_type or "tool_log"),
                **(metadata or {}),
            ),
        )

    if retrieve_meta is not None:
        query = str(retrieve_meta.get("query") or tool_args.get("query") or "").strip()
        await stream.progress(
            f"Query: {query}" if query else start_retrieval_message,
            source=source,
            stage=stage,
            metadata=derive_trace_metadata(
                retrieve_meta,
                trace_kind="call_status",
                call_state="running",
            ),
        )
    try:
        result = await registry.execute(
            tool_name,
            event_sink=_event_sink if retrieve_meta is not None else None,
            **tool_args,
        )
        if retrieve_meta is not None:
            await stream.progress(
                f"Retrieve complete ({len(result.content)} chars)",
                source=source,
                stage=stage,
                metadata=derive_trace_metadata(
                    retrieve_meta,
                    trace_kind="call_status",
                    call_state="complete",
                ),
            )
        return {
            "result_text": result.content or empty_tool_result_message,
            "success": result.success,
            "sources": result.sources,
            "metadata": result.metadata,
            "terminate_turn": getattr(result, "terminate_turn", False),
            "pause_for_user": getattr(result, "pause_for_user", None),
        }
    except Exception as exc:
        logger.error("Tool %s failed", tool_name, exc_info=True)
        if retrieve_meta is not None:
            await stream.error(
                f"Retrieve failed: {exc}",
                source=source,
                stage=stage,
                metadata=derive_trace_metadata(
                    retrieve_meta,
                    trace_kind="call_status",
                    call_state="error",
                    error=str(exc),
                ),
            )
        unknown_msg = (
            unknown_error_message_factory(tool_name)
            if unknown_error_message_factory is not None
            else f"Error executing {tool_name}: {exc}"
        )
        return {
            "result_text": unknown_msg,
            "success": False,
            "sources": [],
            "metadata": {"error": str(exc)},
            "terminate_turn": False,
            "pause_for_user": None,
        }


async def _collect_outcome(
    *,
    prepared: list[tuple[str, str, dict[str, Any]]],
    results: list[dict[str, Any]],
    per_tool_trace_meta: list[dict[str, Any]],
    suppress_ui_indices: set[int] | None = None,
    stream: StreamBus,
    source: str,
    stage: str,
) -> DispatchOutcome:
    """Walk tool results: emit ``tool_result`` events and assemble the outcome.

    First terminating tool wins; first paused tool wins independently. Pause
    and terminate are mutually exclusive at the loop level — pause skips
    terminator emission because the loop will produce a real final answer
    after the user reply resumes.
    """
    aggregated_sources: list[dict[str, Any]] = []
    tool_messages: list[dict[str, Any]] = []
    tool_metadata_by_id: dict[str, dict[str, Any]] = {}
    terminate = False
    terminate_payload: dict[str, Any] | None = None
    pause = False
    pause_payload: dict[str, Any] | None = None
    pause_tool_call_id: str | None = None
    suppress_ui_indices = suppress_ui_indices or set()
    for tool_index, ((tool_call_id, tool_name, _exec_args), result) in enumerate(
        zip(prepared, results, strict=False)
    ):
        result_text = str(result["result_text"])
        tool_meta = per_tool_trace_meta[tool_index]
        tool_extra_meta = result.get("metadata") if isinstance(result, dict) else None
        result_event_meta = merge_trace_metadata(tool_meta, {"trace_kind": "tool_result"})
        if isinstance(tool_extra_meta, dict) and tool_extra_meta:
            result_event_meta = merge_trace_metadata(
                result_event_meta,
                {"tool_metadata": dict(tool_extra_meta)},
            )
        if tool_index not in suppress_ui_indices:
            await stream.tool_result(
                tool_name=tool_name,
                result=result_text,
                source=source,
                stage=stage,
                metadata=result_event_meta,
            )
        aggregated_sources.extend(result.get("sources") or [])
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result_text,
            }
        )
        if isinstance(tool_extra_meta, dict) and tool_extra_meta:
            tool_metadata_by_id[tool_call_id] = dict(tool_extra_meta)
        if result.get("terminate_turn") and not terminate:
            terminate = True
            terminate_payload = {
                "tool_name": tool_name,
                "content": result_text,
                "metadata": dict(tool_extra_meta) if isinstance(tool_extra_meta, dict) else {},
            }
        pause_request = result.get("pause_for_user")
        if pause_request and not pause:
            pause = True
            pause_payload = {
                "tool_name": tool_name,
                "ask_user": pause_request,
            }
            pause_tool_call_id = tool_call_id

    return DispatchOutcome(
        sources=aggregated_sources,
        tool_messages=tool_messages,
        tool_metadata_by_id=tool_metadata_by_id,
        terminate=terminate,
        terminate_payload=terminate_payload,
        pause=pause,
        pause_payload=pause_payload,
        pause_tool_call_id=pause_tool_call_id,
    )
