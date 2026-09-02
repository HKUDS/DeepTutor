"""Ask Questions capability — an explicit user-selected interview mode."""

from __future__ import annotations

from typing import cast

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import (
    CapabilityManifest,
    StreamBusProtocol,
    TurnCapability,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.request_contracts import get_capability_request_schema
from deeptutor.runtime.stream_bus import StreamBus


class AskQuestionsCapability(TurnCapability):
    """Start the selected turn with a context-aware question card."""

    manifest = CapabilityManifest(
        name="ask_questions",
        description=(
            "Ask the user high-value questions to fill in missing context, "
            "then complete the original request with their answers."
        ),
        stages=["responding"],
        tools_used=["ask_user"],
        cli_aliases=["ask"],
        request_schema=get_capability_request_schema("chat"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        context.metadata["ask_questions_mode"] = True
        # This is the first *agent-loop round of the selected turn*, not the
        # first turn in the conversation.  The prompt still receives the full
        # history, so a turn selected much later asks a new, contextual question.
        pipeline = AgenticChatPipeline(
            language=context.language,
            initial_tool_choice="ask_user",
        )
        await pipeline.run(context, cast(StreamBus, stream))


__all__ = ["AskQuestionsCapability"]
