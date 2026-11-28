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
    seed = pipeline._capability_pre_loop_seed(context)
    assert "engine reports: correct" in seed
    assert 'they answered "B"' in seed
    assert "otherwise call this FIRST" in MasteryStatusTool().get_definition().description


def _full_status() -> dict:
    from deeptutor.capabilities.mastery.tools import (
        OPEN_QUESTION_INSTRUCTION,
        WORKING_BRIEF_INSTRUCTION,
    )
    from deeptutor.learning.teaching import TEACHING_FOCUS_INSTRUCTION, TEACHING_GUIDANCE

    untouched = {
        "id": "kp0",
        "name": "Function notation",
        "type": "procedure",
        "prerequisite_ids": [],
        "topic_source_ids": [],
        "status": "new",
        "mastery": 0.0,
        "mastery_source": "",
        "override_note": "",
        "deferred": False,
    }
    started = {
        **untouched,
        "id": "kp1",
        "prerequisite_ids": ["kp0"],
        "status": "learning",
        "mastery": 0.4,
    }
    return {
        "status": "active",
        "path_revision": 5,
        "path_id": "p",
        "path_name": "Derivatives",
        "goal": "",
        "sources": [],
        "mode": "study",
        "next": {
            "action": "answer_pending",
            "knowledge_point_id": "kp0",
            "pending_prompt": "What is f(-2)?",
            "pending_question": {"question_id": "q", "prompt": "What is f(-2)?"},
            "session_id": "",
        },
        "map": {
            "counts": {"total": 2},
            "modules": [{"id": "m", "knowledge_points": [untouched, started]}],
        },
        "learner_profile": {
            "prior_knowledge": "Starting from zero",
            "time_budget": "",
            "preferences": "",
            "teaching_preferences": {},
            "teaching_observations": {},
            "teaching_focus": {
                "knowledge_point_id": "kp0",
                "observations": [],
                "instruction": TEACHING_FOCUS_INSTRUCTION,
            },
            "teaching_guidance": TEACHING_GUIDANCE,
        },
        "intake_needed": False,
        "learning_stages": {"kp0": "not_yet_covered", "kp1": "explained"},
        "visual_requirements": {
            "kp0": {"required": [], "demonstrated": []},
            "kp1": {"required": ["graph"], "demonstrated": []},
        },
        "pending_interaction": {
            "question_id": "q",
            "status": "awaiting_input",
            "instruction": OPEN_QUESTION_INSTRUCTION,
            "session_id": "s",
        },
        "due_review_ids": [],
        "state_scope": "working_brief",
        "inspection_instruction": WORKING_BRIEF_INSTRUCTION,
    }


def test_snapshot_keeps_this_turns_state_and_drops_fixed_text_and_defaults():
    """Issue #2922: each kept snapshot is paid for once, so it carries only state."""
    from deeptutor.capabilities.mastery.snapshot import compact_status

    full = _full_status()
    brief = compact_status(full)
    text = json.dumps(brief)
    for fixed in (
        full["inspection_instruction"],
        full["pending_interaction"]["instruction"],
        full["learner_profile"]["teaching_guidance"],
        full["learner_profile"]["teaching_focus"]["instruction"],
    ):
        assert fixed not in text
    points = brief["map"]["modules"][0]["knowledge_points"]
    assert points[0] == {"id": "kp0", "name": "Function notation", "type": "procedure"}
    assert points[1]["prerequisite_ids"] == ["kp0"]
    assert points[1]["status"] == "learning" and points[1]["mastery"] == 0.4
    assert brief["learning_stages"] == {"kp1": "explained"}
    assert brief["visual_requirements"] == {"kp1": {"required": ["graph"], "demonstrated": []}}
    assert brief["learner_profile"] == {"prior_knowledge": "Starting from zero"}
    assert brief["next"]["pending_question"] == {"question_id": "q", "prompt": "What is f(-2)?"}
    assert "pending_prompt" not in brief["next"]
    assert brief["pending_interaction"] == {"question_id": "q", "status": "awaiting_input"}
    for key in ("goal", "sources", "due_review_ids", "intake_needed", "inspection_instruction"):
        assert key not in brief
    assert brief["state_scope"] == "working_brief"
    assert len(text) < len(json.dumps(full)) * 0.4


def test_snapshot_keeps_guidance_that_is_specific_to_this_card():
    from deeptutor.capabilities.mastery.snapshot import compact_status

    full = _full_status()
    full["pending_interaction"]["instruction"] = "This pending card belongs to an earlier one."
    full["learner_profile"]["teaching_focus"]["observations"] = [{"key": "k", "text": "Lost"}]
    brief = compact_status(full)
    assert brief["pending_interaction"]["instruction"] == full["pending_interaction"]["instruction"]
    assert brief["learner_profile"]["teaching_focus"] == {
        "knowledge_point_id": "kp0",
        "observations": [{"key": "k", "text": "Lost"}],
    }


@pytest.mark.parametrize("language", ["en", "zh"])
def test_the_system_prompt_states_the_fixed_snapshot_guidance_once(language):
    from deeptutor.capabilities.mastery.pipeline import MasteryPromptAssembler
    from deeptutor.capabilities.mastery.tools import (
        GROUP_REPLY_INSTRUCTION,
        INTAKE_INSTRUCTION,
        OPEN_QUESTION_INSTRUCTION,
        WORKING_BRIEF_INSTRUCTION,
    )
    from deeptutor.learning.teaching import TEACHING_FOCUS_INSTRUCTION, TEACHING_GUIDANCE
    from deeptutor.services.prompt import get_prompt_manager

    prompts = get_prompt_manager().load_prompts("mastery", "mastery_loop", language)
    assembler = MasteryPromptAssembler(prompts=prompts, language=language)
    blocks = assembler.foundation_blocks(UnifiedContext(metadata={"mastery_mode": True}))
    system = "\n".join(block.content for block in blocks)
    for fixed in (
        WORKING_BRIEF_INSTRUCTION,
        INTAKE_INSTRUCTION,
        OPEN_QUESTION_INSTRUCTION,
        GROUP_REPLY_INSTRUCTION,
        TEACHING_GUIDANCE,
        TEACHING_FOCUS_INSTRUCTION,
    ):
        assert system.count(fixed) == 1
    assert "[Current-turn mastery_status snapshot]" in system
    assert "{" + "working_brief}" not in system


@pytest.mark.asyncio
async def test_pre_loop_sends_the_short_header_and_the_compact_payload(monkeypatch):
    from deeptutor.capabilities.mastery.history import SNAPSHOT_HEADER
    from deeptutor.capabilities.mastery.snapshot import compact_status

    full = _full_status()

    async def read(**kwargs):
        return ToolResult(success=True, content=json.dumps(full))

    monkeypatch.setattr(MasteryStatusTool, "execute", staticmethod(read))
    context = UnifiedContext(metadata={"mastery_mode": True, "mastery_path_id": "p"})
    block = await MasteryLoopCapability().pre_loop(context, None)
    assert block.content.startswith(SNAPSHOT_HEADER)
    assert json.loads(block.content[len(SNAPSHOT_HEADER) :]) == compact_status(full)
    assert "already read mastery_status" not in block.content
