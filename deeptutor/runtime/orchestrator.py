"""
Chat Orchestrator
=================

Unified entry point that routes user messages to the appropriate capability.
All consumers (CLI, WebSocket, SDK) call the orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator
import uuid

from deeptutor.capabilities.protocol import AGENT_OUTPUT, EVENT_METADATA
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus, register_bus, unregister_bus
from deeptutor.events.event_bus import Event, EventType, get_event_bus
from deeptutor.runtime.registry.capability_registry import get_capability_registry
from deeptutor.runtime.registry.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)


def completion_event_fields(context: UnifiedContext, cap_name: str) -> tuple[str, dict[str, Any]]:
    """Build CAPABILITY_COMPLETE ``agent_output`` + metadata.

    Capabilities may stash a body on ``context.metadata[AGENT_OUTPUT]`` and
    publishable extras under ``context.metadata[EVENT_METADATA]`` (both named in
    ``deeptutor.capabilities.protocol``).
    ``capability``, ``session_id`` and ``turn_id`` always win so consumers can
    rely on those keys.

    Only that explicit sub-dict is forwarded, never ``context.metadata`` whole.
    Turn metadata is a scratchpad, not a wire format: it holds live callables
    (``wait_for_user_reply``), the user's ask_user answers, and whatever else a
    capability parked there mid-turn. Publishing it to the global EventBus —
    whose subscribers include the Partner channels — would leak turn internals
    to every listener and hand JSON-serialising consumers objects they cannot
    encode. A capability that wants a value on the bus says so.
    """
    meta = context.metadata or {}
    agent_output = str(meta.get(AGENT_OUTPUT) or "")
    published = meta.get(EVENT_METADATA)
    extras = dict(published) if isinstance(published, dict) else {}
    return agent_output, {
        **extras,
        "capability": cap_name,
        "session_id": context.session_id,
        "turn_id": str(meta.get("turn_id") or ""),
    }


class ChatOrchestrator:
    """
    Routes a ``UnifiedContext`` to the correct capability, manages
    the ``StreamBus`` lifecycle, and publishes completion events.
    """

    def __init__(self) -> None:
        self._cap_registry = get_capability_registry()
        self._tool_registry = get_tool_registry()

    async def handle(self, context: UnifiedContext) -> AsyncIterator[StreamEvent]:
        """
        Execute a single user turn and yield streaming events.

        If ``context.active_capability`` is set, the corresponding capability
        handles the turn. Otherwise, the default ``chat`` capability is used.
        """
        if not context.session_id:
            context.session_id = str(uuid.uuid4())

        try:
            from deeptutor.services.rag.pipelines.pageindex import (
                validate_pageindex_oss_selection,
            )

            validate_pageindex_oss_selection(context.knowledge_bases)
        except ValueError as exc:
            bus = StreamBus()
            await bus.error(
                str(exc),
                source="orchestrator",
                metadata={"turn_terminal": True, "status": "failed"},
            )
            await bus.emit(
                StreamEvent(
                    type=StreamEventType.DONE,
                    source="orchestrator",
                    metadata={"status": "failed"},
                )
            )
            await bus.close()
            async for event in bus.subscribe():
                yield event
            return

        cap_name = context.active_capability or "chat"
        capability = self._cap_registry.get(cap_name)

        if capability is None:
            bus = StreamBus()
            await bus.error(
                f"Unknown capability: {cap_name}. "
                f"Available: {self._cap_registry.list_capabilities()}",
                source="orchestrator",
                metadata={"turn_terminal": True, "status": "failed"},
            )
            await bus.emit(
                StreamEvent(
                    type=StreamEventType.DONE,
                    source="orchestrator",
                    metadata={"status": "failed"},
                )
            )
            await bus.close()
            async for event in bus.subscribe():
                yield event
            return

        yield StreamEvent(
            type=StreamEventType.SESSION,
            source="orchestrator",
            metadata={
                "session_id": context.session_id,
                "turn_id": str(context.metadata.get("turn_id", "")),
            },
        )

        bus = StreamBus()
        _turn_id = str(context.metadata.get("turn_id") or "")
        if _turn_id:
            register_bus(_turn_id, bus)

        async def _run() -> None:
            status = "completed"
            try:
                await capability.run(context, bus)
            except Exception as exc:
                status = "failed"
                logger.error("Capability %s failed: %s", cap_name, exc, exc_info=True)
                error_metadata: dict[str, Any] = {
                    "turn_terminal": True,
                    "status": status,
                }
                error_code = getattr(exc, "error_code", None)
                if isinstance(error_code, str) and error_code:
                    error_metadata["error_code"] = error_code
                retryable = getattr(exc, "retryable", None)
                if isinstance(retryable, bool):
                    error_metadata["retryable"] = retryable
                partial_response = getattr(exc, "partial_response", None)
                if isinstance(partial_response, bool):
                    error_metadata["partial_response"] = partial_response
                await bus.error(
                    str(exc),
                    source=cap_name,
                    metadata=error_metadata,
                )
            finally:
                await bus.emit(
                    StreamEvent(
                        type=StreamEventType.DONE,
                        source=cap_name,
                        metadata={"status": status},
                    )
                )
                await bus.close()
                if _turn_id:
                    unregister_bus(_turn_id)

        stream = bus.subscribe()
        task = asyncio.create_task(_run())

        async for event in stream:
            yield event

        await task
        await self._publish_completion(context, cap_name)

    async def _publish_completion(self, context: UnifiedContext, cap_name: str) -> None:
        """Publish CAPABILITY_COMPLETE to the global EventBus."""
        try:
            bus = get_event_bus()
            agent_output, metadata = completion_event_fields(context, cap_name)
            await bus.publish(
                Event(
                    type=EventType.CAPABILITY_COMPLETE,
                    task_id=str(context.metadata.get("turn_id") or context.session_id),
                    user_input=context.user_message,
                    agent_output=agent_output,
                    metadata=metadata,
                )
            )
        except Exception:
            logger.debug("EventBus publish failed (may not be running)", exc_info=True)

    def list_tools(self) -> list[str]:
        return self._tool_registry.list_tools()

    def list_capabilities(self) -> list[str]:
        return self._cap_registry.list_capabilities()

    def get_capability_manifests(self) -> list[dict[str, Any]]:
        return self._cap_registry.get_manifests()

    def get_tool_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return self._tool_registry.build_openai_schemas(names)
