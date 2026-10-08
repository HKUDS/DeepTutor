import json
from unittest.mock import AsyncMock

import pytest

from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.capabilities.mastery.tools import MasteryStatusTool
from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import ToolResult


@pytest.mark.asyncio
async def test_snapshot_is_fresh_scoped_and_includes_pending_answer(monkeypatch):
    calls = []

    async def read(**kwargs):
        calls.append(kwargs)
        return ToolResult(
            success=True,
            content=json.dumps(
                {
                    "path_id": kwargs["_mastery_path_id"],
                    "revision": len(calls),
                    "pending_interaction": {"status": "answered", "learner_answer": "B"},
                }
            ),
        )

    monkeypatch.setattr(MasteryStatusTool, "execute", staticmethod(read))
    cap = MasteryLoopCapability()
    context = UnifiedContext(
        session_id="s",
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "p1",
            "mastery_session_mode": "review",
        },
    )
    first = await cap.pre_loop(context, None)
    assert '"learner_answer": "B"' in first.content
    assert calls[0]["_mastery_session_mode"] == "review"
    context.metadata["mastery_path_id"] = "p2"
    second = await cap.pre_loop(context, None)
    assert '"path_id": "p2"' in second.content
    assert '"revision": 2' in second.content
    assert "p1" not in second.content


@pytest.mark.asyncio
async def test_no_snapshot_on_read_failure_or_inactive_path(monkeypatch):
    read = AsyncMock(return_value=ToolResult(success=False, content="unavailable"))
    monkeypatch.setattr(MasteryStatusTool, "execute", read)
    cap = MasteryLoopCapability()
    assert await cap.pre_loop(UnifiedContext(), None) is None
    read.assert_not_called()
    context = UnifiedContext(metadata={"mastery_mode": True, "mastery_path_id": "p"})
    assert await cap.pre_loop(context, None) is None
    assert "otherwise call this FIRST" in MasteryStatusTool().get_definition().description


@pytest.mark.asyncio
async def test_binding_change_during_read_discards_snapshot(monkeypatch):
    context = UnifiedContext(metadata={"mastery_mode": True, "mastery_path_id": "p1"})

    async def read(**kwargs):
        context.metadata["mastery_path_id"] = "p2"
        return ToolResult(success=True, content=json.dumps({"path_id": "p1"}))

    monkeypatch.setattr(MasteryStatusTool, "execute", staticmethod(read))
    assert await MasteryLoopCapability().pre_loop(context, None) is None


@pytest.mark.asyncio
async def test_prepass_failure_keeps_tool_fallback_and_grade_seed(monkeypatch):
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline

    async def read(**kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(MasteryStatusTool, "execute", staticmethod(read))
    context = UnifiedContext(
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "p1",
            "mastery_card_grade": {"is_correct": True, "result": {"learner_answer": "B"}},
        }
    )
    pipeline = AgenticChatPipeline(language="en")
    assert await pipeline._capability_pre_loop_briefings(context, None) == ""
    assert "already graded it: correct" in pipeline._capability_pre_loop_seed(context)
    assert "otherwise call this FIRST" in MasteryStatusTool().get_definition().description
