"""GuruAI Sinhala-first tutoring capabilities.

These capabilities intentionally reuse DeepTutor's existing chat loop, tools,
attachments, streaming, and knowledge-base context. They only add the
Sri Lankan syllabus tutoring rules and practice grading modes.
"""

from __future__ import annotations

from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.guruai.prompts import GRADING_SYSTEM_PROMPT, GURUAI_SYSTEM_PROMPT


def _active(context: UnifiedContext, mode: str) -> bool:
    return str(context.metadata.get("guruai_mode", "")).strip().lower() == mode


class GuruExplainLoopCapability:
    """Ground normal chat turns in an uploaded syllabus or past-paper KB."""

    name = "guruai_explain"
    owned_tools: tuple[str, ...] = ()

    def is_active(self, context: UnifiedContext) -> bool:
        return _active(context, "explain")

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        return PromptBlock("guruai_explain", GURUAI_SYSTEM_PROMPT)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        _ = tool_name, context
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        if not self.is_active(context):
            return ""
        return (
            "GuruAI mode is active. Prefer the user's attached syllabus or past-paper "
            "sources. Preserve page-level evidence and answer in the requested language."
        )


class GuruPracticeLoopCapability:
    """Grade a learner's answer against an attached official marking scheme."""

    name = "guruai_practice_grade"
    owned_tools: tuple[str, ...] = ()

    def is_active(self, context: UnifiedContext) -> bool:
        return _active(context, "practice_grade")

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        return PromptBlock("guruai_practice_grade", GRADING_SYSTEM_PROMPT)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        _ = tool_name, context
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        if not self.is_active(context):
            return ""
        return (
            "GuruAI Practice Mode is active. Find the official marking scheme in the "
            "attached knowledge sources. Award method marks and explain every mark point."
        )


__all__ = ["GuruExplainLoopCapability", "GuruPracticeLoopCapability"]
