"""Shared fixtures for core tests."""

from __future__ import annotations

from typing import Any, Callable
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent
from deeptutor.core.stream_bus import StreamBus
from deeptutor.runtime.orchestrator import ChatOrchestrator
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.registry.tool_registry import ToolRegistry


@pytest.fixture
def stream_bus() -> StreamBus:
    """Provide a fresh StreamBus instance for testing."""
    return StreamBus()


class EchoCapability(BaseCapability):
    """Reusable minimal capability for orchestrator tests."""
    
    manifest = CapabilityManifest(
        name="echo",
        description="Echoes input",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        await stream.content(context.user_message, source=self.name)


@pytest.fixture
def echo_capability() -> EchoCapability:
    """Return an instance of EchoCapability."""
    return EchoCapability()


@pytest.fixture
def mock_event_bus():
    """Patch the global EventBus to avoid background task leakage."""
    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock()
    with patch("deeptutor.runtime.orchestrator.get_event_bus", return_value=mock_bus) as mock_eb:
        yield mock_eb


@pytest.fixture
def build_orchestrator() -> Callable[[list[BaseCapability]], ChatOrchestrator]:
    """Factory fixture to build an orchestrator with specific capabilities."""
    def _build(capabilities: list[BaseCapability]) -> ChatOrchestrator:
        cap_reg = CapabilityRegistry()
        for cap in capabilities:
            cap_reg.register(cap)
        tool_reg = ToolRegistry()
        
        # Instantiate normally and inject patched registries
        orchestrator = ChatOrchestrator.__new__(ChatOrchestrator)
        orchestrator._cap_registry = cap_reg
        orchestrator._tool_registry = tool_reg
        return orchestrator
    
    return _build


@pytest.fixture
def collect_events() -> Callable[[ChatOrchestrator, UnifiedContext], Any]:
    """Helper to collect events from an orchestrator."""
    async def _collect(orchestrator: ChatOrchestrator, context: UnifiedContext) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        async for event in orchestrator.handle(context):
            events.append(event)
        return events
    return _collect
