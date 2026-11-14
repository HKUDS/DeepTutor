import json
from unittest.mock import AsyncMock

import pytest

from deeptutor.capabilities.mastery import tools
from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.learning import lesson_evidence, semantic_assessment
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.policy import is_assessed_mastered
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.llm.config import LLMConfig


@pytest.fixture
def service(tmp_path, monkeypatch):
    instance = LearningService(LearningStore(tmp_path / "learning"))
    instance.save(
        LearningProgress(
            book_id="p",
            modules=[
                LearningModule(
                    id="m",
                    name="Module",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(
                            id="kp",
                            name="Explain both relationships",
                            type=KnowledgeType.CONCEPT,
                            module_id="m",
                        )
                    ],
                )
            ],
            lesson_evidence={
                "kp": {"id": "focus", "coverage": {"scope": "focus", "complete": False}}
            },
        )
    )
    monkeypatch.setattr(tools, "_new_service", lambda: instance)
    monkeypatch.setattr(tools, "_sync_qualitative_to_question_bank", AsyncMock())
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config",
        lambda: LLMConfig(model="test", api_key="test"),
    )

    def validate(store, progress, kp_id, evidence, **kwargs):
        coverage = evidence.get("coverage", {})
        if coverage.get("scope") != "objective" or coverage.get("complete") is not True:
            raise lesson_evidence.LessonUnavailable(
                "This packet supports a teaching slice, not an arbitrary assessment."
            )

    monkeypatch.setattr(lesson_evidence, "validate_evidence", validate)
    return instance


def context(answer, turn="t1", session="s"):
    return UnifiedContext(
        user_message=answer,
        session_id=session,
        language="zh",
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "p",
            "turn_id": turn,
            "mastery_session_mode": "study",
        },
    )


async def assess(ctx):
    kwargs = MasteryLoopCapability().augment_kwargs(
        "mastery_assess", {"knowledge_point_id": "kp"}, ctx
    )
    return await tools.MasteryAssessTool().execute(**kwargs)


def make_complete(instance):
    progress = instance.store.load("p")
    progress.assessment_evidence["kp"] = {
        "id": "assessment",
        "coverage": {"scope": "objective", "complete": True},
    }
    instance.save(progress)


def judged_correct(monkeypatch):
    answers = []

    async def judge(config, items):
        answers.append(items[0]["answer"])
        return {
            "kp": semantic_assessment.Verdict(
                result="correct", confidence=0.95, feedback="Both relationships demonstrated."
            )
        }

    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    return answers


@pytest.mark.asyncio
async def test_focus_packet_is_repaired_once_for_the_whole_objective(service, monkeypatch):
    answers = judged_correct(monkeypatch)

    async def prepare(store, path, kp, config, **kwargs):
        assert (path, kp) == ("p", "kp")
        assert kwargs["focus"] == "" and kwargs["language"] == "zh"
        make_complete(service)

    preparation = AsyncMock(side_effect=prepare)
    monkeypatch.setattr(lesson_evidence, "prepare_lesson", preparation)
    ctx = context("My explanation covers both relationships.")
    result = await assess(ctx)
    assert result.success and json.loads(result.content)["mastered"] is True
    preparation.assert_awaited_once()
    assert answers == [ctx.user_message]
    assert len(service.store.load("p").learning_evidence) == 1
    assert "assessment_blocked" not in ctx.extension("mastery")


@pytest.mark.asyncio
async def test_unresolved_sources_end_the_tool_loop_without_grading_or_reasking(
    service, monkeypatch
):
    preparation = AsyncMock(return_value={"coverage": {"complete": False}})
    judge = AsyncMock()
    monkeypatch.setattr(lesson_evidence, "prepare_lesson", preparation)
    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    ctx = context("The first relationship is explained.")
    result = await assess(ctx)
    assert result.success is False
    preparation.assert_awaited_once()
    judge.assert_not_awaited()
    progress = service.store.load("p")
    assert not progress.learning_evidence and not progress.qualitative_mastery
    assert not is_assessed_mastered(progress, progress.modules[0].knowledge_points[0])
    _, retained = service.store.mutate(
        "p", lambda tx: tx.pending_explanation("kp", session_id="s", turn_id="t2")
    )
    assert retained == ctx.user_message
    # The native loop checks this hook immediately after a tool batch.
    notice = MasteryLoopCapability().final_text_override(ctx, "")
    assert notice and "不需要" in notice and "回答已保留" in notice


@pytest.mark.asyncio
async def test_reply_after_source_repair_completes_the_retained_answer(service, monkeypatch):
    monkeypatch.setattr(lesson_evidence, "prepare_lesson", AsyncMock(return_value={}))
    await assess(context("First relationship."))
    make_complete(service)
    answers = judged_correct(monkeypatch)
    result = await assess(context("Second relationship.", turn="t2"))
    assert result.success and json.loads(result.content)["mastered"] is True
    assert answers == ["First relationship.\n\nSecond relationship."]


@pytest.mark.asyncio
async def test_provider_failure_preserves_answer_without_paid_source_retry(service, monkeypatch):
    make_complete(service)
    judge = AsyncMock(side_effect=semantic_assessment.AssessmentUnavailable("Provider unavailable"))
    preparation = AsyncMock()
    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    monkeypatch.setattr(lesson_evidence, "prepare_lesson", preparation)
    ctx = context("An actual learner explanation.")
    result = await assess(ctx)
    assert result.success is False
    judge.assert_awaited_once()
    preparation.assert_not_awaited()
    assert ctx.extension("mastery")["assessment_blocked"]["reason"] == "service"
    assert not service.store.load("p").learning_evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["", " \n ", "x" * 10001], ids=["empty", "blank", "too-long"])
async def test_invalid_input_does_not_claim_that_an_answer_was_retained(
    service, monkeypatch, answer
):
    preparation = AsyncMock()
    judge = AsyncMock()
    monkeypatch.setattr(lesson_evidence, "prepare_lesson", preparation)
    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    ctx = context(answer)
    result = await assess(ctx)
    assert not result.success
    assert "actual learner explanation" in result.content
    assert "assessment_blocked" not in ctx.extension("mastery")
    preparation.assert_not_awaited()
    judge.assert_not_awaited()
    progress = service.store.load("p")
    assert not progress.learning_evidence and not progress.qualitative_mastery


def test_old_callback_cannot_block_a_rebound_path():
    ctx = context("answer")
    capability = MasteryLoopCapability()
    kwargs = capability.augment_kwargs(
        "mastery_assess", {"_assessment_blocked": lambda _: None}, ctx
    )
    ctx.metadata["mastery_path_id"] = "another-path"
    kwargs["_assessment_blocked"]("sources")
    assert "assessment_blocked" not in ctx.extension("mastery")
    assert capability.final_text_override(ctx, "") is None


def test_partial_feedback_requests_only_the_gap():
    instruction = tools._assess_next_move(False, {})
    assert "mastery_assess" in instruction
    assert "targeted follow-up" in instruction
    assert "retained explanation" in instruction
    assert "not a full restatement" in instruction


def test_assessment_notice_preserves_an_optional_profile_storage_warning():
    ctx = context("answer")
    ctx.extension("mastery").update(
        assessment_blocked={"path_id": "p", "reason": "sources"},
        profile_write_pending=True,
    )
    notice = MasteryLoopCapability().final_text_override(ctx, "")
    assert "未能保存" in notice and "回答已保留" in notice
    assert ctx.extension("mastery")["profile_receipt"] == {"status": "not_saved"}
