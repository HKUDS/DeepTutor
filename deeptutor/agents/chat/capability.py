"""Agentic chat capability."""

from __future__ import annotations

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.bootstrap.builtin_capabilities import builtin_capability_manifest
from deeptutor.runtime.stream_bus import StreamBus


class ChatCapability(TurnCapability):
    manifest = builtin_capability_manifest("chat")

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        pipeline = AgenticChatPipeline(language=context.language)
        await pipeline.run(context, stream)
