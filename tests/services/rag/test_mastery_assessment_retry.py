"""Focused teaching evidence cannot trap an assessment in repeated tool rounds."""

import json
from unittest.mock import AsyncMock

import pytest

from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.capabilities.mastery.tools import MasteryAssessTool
from deeptutor.core.context import UnifiedContext
from deeptutor.learning import lesson_evidence, semantic_assessment
from deeptutor.learning.service import LearningService
from tests.agents.chat.test_agent_loop import _isolated_runtime
from tests.services.rag.test_mastery_source_pages import _install_preparation, material


@pytest.mark.asyncio
@pytest.mark.usefixtures("_isolated_runtime")
@pytest.mark.parametrize("recover", [False, True], ids=["unchanged", "prepared-objective"])
async def test_mastery_assessment_retry_with_focused_evidence(material, monkeypatch, recover):  # noqa: F811 - imported pytest fixture
    progress = material.store.load("path")
    progress.modules[0].knowledge_points[0].type = "concept"
    material.store.save(progress)
    prepare_calls = _install_preparation(material, monkeypatch)
    packet = await lesson_evidence.prepare_lesson(
        material.store, "path", "kp", material.config, focus="Explain bilayer structure"
    )
    assert packet["coverage"]["scope"] == "focus"
    assert not material.store.load("path").assessment_evidence
    judge = AsyncMock(
        return_value={
            "kp": semantic_assessment.Verdict(
                result="correct", confidence=0.99, feedback="Clear explanation."
            )
        }
    )
    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    monkeypatch.setattr(
        "deeptutor.capabilities.mastery.tools._new_service", lambda: LearningService(material.store)
    )
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda: material.store)
    monkeypatch.setattr(
        "deeptutor.capabilities.mastery.tools._sync_qualitative_to_question_bank", AsyncMock()
    )
    capability = MasteryLoopCapability()
    context = UnifiedContext(
        user_message="Lipids form the bilayer.",
        session_id="session",
        metadata={"mastery_mode": True, "mastery_path_id": "path", "turn_id": "turn"},
    )

    if not recover:
        from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
        from deeptutor.runtime.registry.tool_registry import ToolRegistry
        from tests.agents.chat.test_agent_loop import _llm_chunk, _result, _run, _ScriptedChatClient

        rounds = [
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": f"assess-{i}",
                            "name": "mastery_assess",
                            "arguments": json.dumps(
                                {"knowledge_point_id": "kp", "feedback": str(i)}
                            ),
                        }
                    ],
                    finish_reason="tool_calls",
                )
            ]
            for i in range(2)
        ]
        client = _ScriptedChatClient(
            [*rounds, [_llm_chunk(content="Unexpected extra round.", finish_reason="stop")]]
        )
        pipeline = MasteryLoopPipeline(language="en")
        pipeline.registry = ToolRegistry()
        pipeline.registry.register(MasteryAssessTool())
        monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["mastery_assess"])
        monkeypatch.setattr(pipeline, "_pageindex_sdk_tool_bundles", AsyncMock(return_value=[]))
        monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
        before_retry = len(prepare_calls)
        result = _result(await _run(pipeline, context))

        assert client.call_count == 2
        assert "couldn’t grade" in result.metadata["response"]
        assert result.metadata["completed"] is True
        judge.assert_not_awaited()
        assert len(prepare_calls) == before_retry
        assert not material.store.load("path").qualitative_mastery
        return

    async def assess(feedback):
        return await MasteryAssessTool().execute(
            **capability.augment_kwargs(
                "mastery_assess", {"knowledge_point_id": "kp", "feedback": feedback}, context
            )
        )

    first = await assess("First attempt")
    assert not first.success
    assert "teaching slice" in first.content
    assert capability.final_text_override(context, "") is None

    retry = await assess("Changed model feedback, same learner explanation")
    assert not retry.success
    # Preparation can complete in the same tool batch as the failed retry.
    await lesson_evidence.prepare_lesson(material.store, "path", "kp", material.config)
    assert capability.final_text_override(context, "") is None
    assert (await assess("Objective evidence prepared")).success
    assert capability.final_text_override(context, "") is None
    judge.assert_awaited_once()
    assert material.store.load("path").qualitative_mastery["kp"] is True
