"""A clarification reply completes the explanation it was asked about (#2249)."""

from __future__ import annotations

import json

import pytest

from deeptutor.capabilities.mastery.mode import STUDY
from deeptutor.learning import semantic_assessment
from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import MasteryAssessTool, MasteryBuildTool

EXPLANATION = (
    "A noise schedule sets how much Gaussian noise is added at each forward step, "
    "so later steps destroy more of the signal."
)
CLARIFICATION = "The variance grows with t, so x_T is close to pure noise."


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        self._root = tmp_path / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return "clarify_path"


@pytest.fixture
def judged(monkeypatch):
    """Ask for clarification first, then accept; record what was graded."""
    answers: list[str] = []

    async def judge(_config, items):
        answers.extend(item["answer"] for item in items)
        verdict = (
            semantic_assessment.Verdict(
                result="ungraded", confidence=0.4, feedback="Say how the variance changes."
            )
            if len(answers) == 1
            else semantic_assessment.Verdict(
                result="correct", confidence=0.95, feedback="Complete explanation."
            )
        )
        return {item["question_id"]: verdict for item in items}

    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    return answers


async def _build(path_id):
    await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode="outline",
        path_name="Diffusion",
        modules=[
            {
                "name": "Forward process",
                "objective": "Explain how noise is added",
                "knowledge_points": [{"name": "Noise schedule", "type": "concept"}],
            }
        ],
    )
    return f"{path_id}_m0_kp0"


async def _assess(path_id, kp, message, *, session="s1", turn):
    result = await MasteryAssessTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=STUDY,
        _session_id=session,
        _turn_id=turn,
        knowledge_point_id=kp,
        _learner_message=message,
    )
    assert result.success, result.content
    return json.loads(result.content)


@pytest.mark.asyncio
async def test_clarification_is_graded_together_with_the_earlier_explanation(path_id, judged):
    kp = await _build(path_id)

    first = await _assess(path_id, kp, EXPLANATION, turn="t1")
    assert first["needs_clarification"] is True and first["final"] is False

    second = await _assess(path_id, kp, CLARIFICATION, turn="t2")
    assert second["result"] == "correct" and second["final"] is True
    assert judged[1] == f"{EXPLANATION}\n\n{CLARIFICATION}"

    evidence = LearningStore().load(path_id).learning_evidence
    assert [item.learner_answer for item in evidence] == [judged[1]]


@pytest.mark.asyncio
async def test_a_retried_clarification_turn_does_not_append_twice(path_id, monkeypatch):
    answers: list[str] = []

    async def judge(_config, items):
        answers.extend(item["answer"] for item in items)
        verdict = semantic_assessment.Verdict(
            result="ungraded", confidence=0.4, feedback="Still unclear."
        )
        return {item["question_id"]: verdict for item in items}

    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    kp = await _build(path_id)
    await _assess(path_id, kp, EXPLANATION, turn="t1")
    await _assess(path_id, kp, CLARIFICATION, turn="t2")
    await _assess(path_id, kp, CLARIFICATION, turn="t2")

    assert answers[1] == answers[2] == f"{EXPLANATION}\n\n{CLARIFICATION}"


@pytest.mark.asyncio
async def test_another_session_or_a_finished_assessment_starts_fresh(path_id, judged):
    kp = await _build(path_id)
    await _assess(path_id, kp, EXPLANATION, turn="t1")

    await _assess(path_id, kp, CLARIFICATION, session="s2", turn="t2")
    assert judged[1] == CLARIFICATION

    await _assess(path_id, kp, CLARIFICATION, turn="t3")
    assert judged[2] == CLARIFICATION
