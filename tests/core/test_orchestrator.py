"""Tests for the ChatOrchestrator routing and lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.runtime.orchestrator import ChatOrchestrator
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.registry.tool_registry import ToolRegistry


# _EchoCapability moved to conftest.py as EchoCapability


class _ExplodingCapability(BaseCapability):
    """Deliberately raises an exception during run()."""

    manifest = CapabilityManifest(
        name="exploding",
        description="Always fails",
        stages=["boom"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        raise RuntimeError("kaboom")


class _ExplodingCapability(BaseCapability):
    """Deliberately raises an exception during run()."""

    manifest = CapabilityManifest(
        name="exploding",
        description="Always fails",
        stages=["boom"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        raise RuntimeError("kaboom")


@pytest.mark.asyncio
async def test_handle_unknown_capability_emits_error(
    build_orchestrator: Any,
    mock_event_bus: Any,
    collect_events: Any,
) -> None:
    """Requesting an unknown capability should emit an ERROR event (not crash)."""
    orchestrator = build_orchestrator([])
    context = UnifiedContext(user_message="hi", active_capability="nonexistent")

    events = await collect_events(orchestrator, context)

    error_events = [e for e in events if e.type == StreamEventType.ERROR]
    assert len(error_events) >= 1
    assert "nonexistent" in error_events[0].content


@pytest.mark.asyncio
async def test_handle_assigns_session_id_if_missing(
    build_orchestrator: Any,
    echo_capability: Any,
    mock_event_bus: Any,
    collect_events: Any,
) -> None:
    """If context.session_id is empty, the orchestrator assigns one."""
    orchestrator = build_orchestrator([echo_capability])
    context = UnifiedContext(user_message="hi", active_capability="echo", session_id="")

    events = await collect_events(orchestrator, context)

    assert context.session_id != ""
    # SESSION event should contain the assigned session_id
    session_events = [e for e in events if e.type == StreamEventType.SESSION]
    assert len(session_events) == 1
    assert session_events[0].metadata["session_id"] == context.session_id


@pytest.mark.asyncio
async def test_handle_routes_to_correct_capability(
    build_orchestrator: Any,
    echo_capability: Any,
    mock_event_bus: Any,
    collect_events: Any,
) -> None:
    """Events emitted by the capability are forwarded to the consumer."""
    orchestrator = build_orchestrator([echo_capability])
    context = UnifiedContext(user_message="ping", active_capability="echo")

    events = await collect_events(orchestrator, context)

    content_events = [e for e in events if e.type == StreamEventType.CONTENT]
    assert any("ping" in e.content for e in content_events)


@pytest.mark.asyncio
async def test_handle_emits_session_and_done_events(
    build_orchestrator: Any,
    echo_capability: Any,
    mock_event_bus: Any,
    collect_events: Any,
) -> None:
    """Every successful turn should include SESSION at the start and DONE at the end."""
    orchestrator = build_orchestrator([echo_capability])
    context = UnifiedContext(user_message="test", active_capability="echo")

    events = await collect_events(orchestrator, context)

    types = [e.type for e in events]
    assert types[0] == StreamEventType.SESSION
    assert types[-1] == StreamEventType.DONE


@pytest.mark.asyncio
async def test_capability_exception_is_caught_and_streamed(
    build_orchestrator: Any,
    mock_event_bus: Any,
    collect_events: Any,
) -> None:
    """If a capability raises, the error is streamed (not raised to the consumer)."""
    orchestrator = build_orchestrator([_ExplodingCapability()])
    context = UnifiedContext(user_message="test", active_capability="exploding")

    events = await collect_events(orchestrator, context)

    error_events = [e for e in events if e.type == StreamEventType.ERROR]
    assert len(error_events) >= 1
    assert "kaboom" in error_events[0].content

    # Must still emit DONE even after errors
    done_events = [e for e in events if e.type == StreamEventType.DONE]
    assert len(done_events) >= 1


@pytest.mark.asyncio
async def test_handle_preserves_existing_session_id(
    build_orchestrator: Any,
    echo_capability: Any,
    mock_event_bus: Any,
    collect_events: Any,
) -> None:
    """If context.session_id is already set, it should not be overwritten."""
    orchestrator = build_orchestrator([echo_capability])
    context = UnifiedContext(user_message="hi", active_capability="echo", session_id="known-id")

    events = await collect_events(orchestrator, context)

    assert context.session_id == "known-id"
    session_events = [e for e in events if e.type == StreamEventType.SESSION]
    assert session_events[0].metadata["session_id"] == "known-id"


@pytest.mark.asyncio
async def test_handle_defaults_to_chat_capability(
    build_orchestrator: Any,
    mock_event_bus: Any,
    collect_events: Any,
) -> None:
    """If active_capability is None, orchestrator should default to 'chat'."""
    class FakeChatCapability(BaseCapability):
        manifest = CapabilityManifest(name="chat", description="default")
        async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
            await stream.content("handled by chat")

    orchestrator = build_orchestrator([FakeChatCapability()])
    context = UnifiedContext(user_message="hi", active_capability=None)

    events = await collect_events(orchestrator, context)
    
    content_events = [e for e in events if e.type == StreamEventType.CONTENT]
    assert any("handled by chat" in e.content for e in content_events)


def test_list_tools_and_capabilities(build_orchestrator: Any, echo_capability: Any) -> None:
    """Verify registry list delegations."""
    orchestrator = build_orchestrator([echo_capability])
    caps = orchestrator.list_capabilities()
    assert "echo" in caps
    
    # tool registry is empty here since we mock it, but should not crash
    tools = orchestrator.list_tools()
    assert tools == []
    
    schemas = orchestrator.get_tool_schemas()
    assert schemas == []
    
    manifests = orchestrator.get_capability_manifests()
    assert len(manifests) == 1
    assert manifests[0]["name"] == "echo"

