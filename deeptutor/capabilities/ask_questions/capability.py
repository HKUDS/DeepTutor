"""Ask Questions capability — an explicit user-selected interview mode."""

from __future__ import annotations

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.runtime.request_contracts import get_capability_request_schema


class AskQuestionsCapability(BaseCapability):
    """Let the model ask context-aware questions whenever they become useful."""

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

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        context.metadata["ask_questions_mode"] = True
        # Tool selection stays model-directed.  The capability's system block
        # changes *when* ask_user is appropriate; it must not force a question
        # at the beginning of every user turn.
        pipeline = AgenticChatPipeline(language=context.language)
        await pipeline.run(context, stream)


__all__ = ["AskQuestionsCapability"]
