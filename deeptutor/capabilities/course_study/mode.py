"""Course Study mode — the standard chat loop acting as a course orchestrator.

There is no bespoke pipeline: as with immersive reading, the selected composer
mode only normalizes turn metadata and starts :class:`AgenticChatPipeline`.
Course-specific tools, prompt policy, and the bounded pre-loop state summary are
contributed by
:class:`~deeptutor.capabilities.course_study.capability.CourseStudyLoopCapability`.

The split is especially important here. The mode must keep ordinary chat tools
available so it can investigate a concrete learner request, while its prompt
enforces the narrower product role: recommend the next learning action and hand
off; never teach the course material itself.

With no course bound the loop capability remains strictly inactive, so its
tools cannot leak. The mode places the dedicated ``no_course`` variant in the
ordinary prompt context before starting the loop; that variant forbids invented
course state and asks the learner to attach a course.
"""

from __future__ import annotations

from typing import cast

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.course_study.capability import (
    COURSE_STUDY_NAME,
    CourseStudyLoopCapability,
    resolve_course_id,
)
from deeptutor.capabilities.course_study.tools import (
    COURSE_STUDY_TOOL_NAMES,
    COURSE_STUDY_TOOL_TYPES,
)
from deeptutor.core.capability_protocol import (
    CapabilityManifest,
    StreamBusProtocol,
    TurnCapability,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus


def _register_course_tools() -> None:
    """Register locally owned tools lazily without closing bootstrap cycles."""
    from deeptutor.runtime.registry.tool_registry import get_tool_registry

    registry = get_tool_registry()
    for tool_type in COURSE_STUDY_TOOL_TYPES:
        tool = tool_type()
        if registry.get(tool.name) is None:
            registry.register(tool)


class CourseStudyCapability(TurnCapability):
    manifest = CapabilityManifest(
        name=COURSE_STUDY_NAME,
        description=(
            "Sense a course's learning state, recommend the best next action, "
            "and hand the learner to the right teaching surface."
        ),
        stages=["responding"],
        tools_used=[
            *COURSE_STUDY_TOOL_NAMES,
            "rag",
            "web_search",
            "exec",
            "reason",
        ],
        cli_aliases=["course"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        context.active_capability = COURSE_STUDY_NAME
        _register_course_tools()
        if not resolve_course_id(context):
            block = CourseStudyLoopCapability().system_block(
                context,
                language=context.language,
                prompts={},
            )
            if block is not None:
                existing = str(context.sidebar_context or "").strip()
                context.sidebar_context = (
                    f"{existing}\n\n{block.content}" if existing else block.content
                )
        await AgenticChatPipeline(language=context.language).run(context, cast(StreamBus, stream))


__all__ = ["CourseStudyCapability"]
