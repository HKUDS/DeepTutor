"""Remaining Python ports for a native TypeScript chat/partner turn.

No model client, model streaming, context window loop, or tool-batch dispatcher
lives here. Unmigrated domain tools retain the existing scoped registry and
server-owned argument injection; native tools never enter this port.
"""

from __future__ import annotations

from typing import Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.runtime.ts_engine import get_engine_client

from .native_seed import native_seed, tool_specs


class NativeAdapter:
    def __init__(self, pipeline: Any, context: Any, stream: Any, schemas: list[dict[str, Any]]):
        self.pipeline, self.context, self.stream, self.schemas = pipeline, context, stream, schemas

    async def invoke(self, operation: str, args: dict[str, Any], state: dict[str, Any]) -> Any:
        if operation == "read_user_inputs":
            drain = self.context.runtime.drain_user_inputs
            return drain() if drain is not None else []
        if operation == "event":
            event = args["event"]
            kind = StreamEventType(event["type"])
            if kind not in {
                StreamEventType.CONTENT,
                StreamEventType.THINKING,
                StreamEventType.PROGRESS,
                StreamEventType.TOOL_CALL,
                StreamEventType.TOOL_RESULT,
            }:
                raise ValueError("Native engine attempted an application-owned event")
            await self.stream.emit(
                StreamEvent(
                    type=kind,
                    source=self.pipeline.event_source,
                    stage=self.pipeline.event_stage,
                    content=event["content"],
                    metadata=event["metadata"],
                )
            )
            return None
        if operation == "checkpoint":
            from deeptutor.services.session.model_history import normalize_model_turn

            self.context.runtime.model_turn = normalize_model_turn(args["modelTurn"])
            if self.context.runtime.model_turn:
                for message in reversed(self.context.runtime.model_turn["messages"]):
                    if message.get("_provider_response_state"):
                        self.context.runtime.provider_response_state = message[
                            "_provider_response_state"
                        ]
                        break
            return None
        if operation == "legacy_tool":
            return await self.legacy_tool(args)
        if operation == "policy":
            text, tools = str(args.get("text") or ""), tuple(args.get("tools") or [])
            return {
                "redirect": self.pipeline._capability_finish_instruction(self.context, text)
                if not tools
                else "",
                "override": self.pipeline._capability_final_text_override(self.context, text),
                "toolPolicy": self.pipeline._capability_tool_round_output_policy(
                    self.context, text, tools
                )
                if tools
                else "",
            }
        if operation == "after_tools":
            from .native_tools import tool_runtime

            checkpoint = ""
            for metadata in args.get("metadataById", {}).values():
                value = metadata.get("_context_checkpoint")
                if isinstance(value, dict) and value.get("summary"):
                    checkpoint = str(value["summary"])
            specs = tool_specs(self.pipeline, self.schemas)
            runtime = tool_runtime(self.pipeline, self.context, specs)
            return {
                "tools": specs,
                "toolRuntime": runtime,
                "override": self.pipeline._capability_final_text_override(self.context, ""),
                "checkpoint": checkpoint,
            }
        if operation == "wait_for_reply":
            raw = args["dispatch"]
            pause = raw["pause"]
            dispatch = DispatchOutcome(
                tool_messages=raw["messages"],
                tool_metadata_by_id=raw["metadataById"],
                pause=True,
                pause_payload={"tool_name": pause["name"], "ask_user": pause["payload"]},
                pause_tool_call_id=pause["callId"],
            )
            resumed = await self.pipeline._await_user_reply_and_resolve(
                context=self.context, stream=self.stream, dispatch=dispatch
            )
            content = next(
                (
                    m["content"]
                    for m in dispatch.tool_messages
                    if m.get("tool_call_id") == pause["callId"]
                ),
                "",
            )
            return {"resumed": resumed, "content": content}
        if operation == "publish_override":
            if not self.context.capability_output.answer_published:
                await self.pipeline._emit_protocol_fallback_final_response(
                    self.stream, args["text"]
                )
                self.context.capability_output.answer_published = True
            return None
        if operation == "publish_terminator":
            value = args["value"]
            await self.pipeline._emit_terminator_final_response(
                self.stream,
                {
                    "tool_name": value["name"],
                    "content": value["content"],
                    "metadata": value["metadata"],
                },
            )
            return None
        raise ValueError("Unknown native compatibility operation")

    async def legacy_tool(self, request: dict[str, Any]) -> dict[str, Any]:
        name = request["name"]
        if name not in {s["function"]["name"] for s in self.schemas}:
            raise ValueError("Tool is not admitted for this turn")
        registry = self.pipeline.tool_lookup
        raw = {k: v for k, v in request["args"].items() if not k.startswith("_")}
        resolver = getattr(registry, "resolve_request", None)
        canonical, resolved = resolver(name, raw) if callable(resolver) else (name, raw)
        kwargs = self.pipeline._augment_tool_kwargs(canonical, resolved, self.context)

        async def sink(event_type: str, message: str = "", metadata: dict[str, Any] | None = None):
            await self.stream.progress(
                message,
                source=self.pipeline.event_source,
                stage=self.pipeline.event_stage,
                metadata={**request["trace"], **(metadata or {}), "trace_kind": event_type},
            )

        result = await registry.execute(name, event_sink=sink, **kwargs)
        return {
            "content": result.content or "",
            "success": result.success,
            "sources": result.sources,
            "metadata": result.metadata,
            "pause": result.pause_for_user,
            "terminate": result.terminate_turn,
            "modelMessage": result.model_message,
        }


async def run_native_turn(
    pipeline: Any, context: Any, stream: Any, enabled: list[str], schemas: list[dict[str, Any]]
) -> dict[str, Any]:
    adapter = NativeAdapter(pipeline, context, stream, schemas)
    async with stream.stage(pipeline.event_stage, source=pipeline.event_source):
        seed = await native_seed(pipeline, context, stream, enabled, schemas)
        result = await get_engine_client().run_native(adapter, seed)
    for usage in result["usage"]:
        pipeline.usage.add_from_response(usage)
    if result["sources"]:
        await stream.sources(
            result["sources"],
            source=pipeline.event_source,
            stage=pipeline.event_stage,
            metadata={"trace_kind": "sources"},
        )
    payload = {
        "response": result["response"],
        "completed": result["completed"],
        "engine": "agent_loop",
        "scheduler": "typescript",
        "execution_runtime": "typescript-native",
        "rounds": result["state"]["rounds"],
        "settlement_rounds": result["state"]["settlement_rounds"],
        "tool_steps": result["state"]["tool_steps"],
        "native_tool_calls": result["nativeToolCalls"],
        "legacy_tool_calls": result["legacyToolCalls"],
        "metadata": {"context_budget": result["contextBudget"]},
    }
    if pipeline.emit_result:
        await emit_capability_result(
            stream, payload, source=pipeline.event_source, usage=pipeline.usage
        )
    return payload
