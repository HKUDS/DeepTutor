"""After a final partial grade, the missing part completes the explanation (#2249)."""

from __future__ import annotations

import json

import pytest

from deeptutor.capabilities.mastery.mode import STUDY
from deeptutor.learning import semantic_assessment
from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import (
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryDeferObjectiveTool,
)

FIRST_HALF = "A noise schedule sets how much Gaussian noise is added at each forward step."
SECOND_HALF = "The variance grows with t, so x_T is close to pure noise."
UNRELATED = "Sampling runs the learned reverse process from noise."


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        self._root = tmp_path / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return "partial_path"


@pytest.fixture
def judged(monkeypatch):
    """Grade an explanation correct only when it covers both halves."""
    answers: list[str] = []

    async def judge(_config, items):
        verdicts = {}
        for item in items:
            answers.append(item["answer"])
            complete = FIRST_HALF in item["answer"] and SECOND_HALF in item["answer"]
            verdicts[item["question_id"]] = semantic_assessment.Verdict(
                result="correct" if complete else "partial",
                confidence=0.95,
                feedback="Complete." if complete else "One part is missing.",
            )
        return verdicts

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
                "knowledge_points": [
                    {"name": "Noise schedule", "type": "concept"},
                    {"name": "Reverse process", "type": "concept"},
                ],
            }
        ],
    )
    return f"{path_id}_m0_kp0", f"{path_id}_m0_kp1"


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
async def test_missing_part_is_graded_together_with_the_partial_explanation(path_id, judged):
    kp, _ = await _build(path_id)

    first = await _assess(path_id, kp, FIRST_HALF, turn="t1")
    assert first["result"] == "partial" and first["final"] is True

    second = await _assess(path_id, kp, SECOND_HALF, turn="t2")
    assert second["result"] == "correct" and second["mastered"] is True
    assert judged[1] == f"{FIRST_HALF}\n\n{SECOND_HALF}"

    evidence = LearningStore().load(path_id).learning_evidence
    assert [item.learner_answer for item in evidence] == [FIRST_HALF, judged[1]]

    # A pass ends it: the next explanation is graded on its own.
    await _assess(path_id, kp, UNRELATED, turn="t3")
    assert judged[2] == UNRELATED


@pytest.mark.asyncio
async def test_repeated_partials_accumulate_without_grading_a_message_twice(path_id, judged):
    kp, _ = await _build(path_id)
    await _assess(path_id, kp, UNRELATED, turn="t1")
    await _assess(path_id, kp, FIRST_HALF, turn="t2")
    # A retried turn replays its saved verdict instead of judging again.
    await _assess(path_id, kp, FIRST_HALF, turn="t2")
    third = await _assess(path_id, kp, SECOND_HALF, turn="t3")

    assert third["result"] == "correct"
    assert judged == [
        UNRELATED,
        f"{UNRELATED}\n\n{FIRST_HALF}",
        f"{UNRELATED}\n\n{FIRST_HALF}\n\n{SECOND_HALF}",
    ]


@pytest.mark.asyncio
async def test_another_session_starts_fresh(path_id, judged):
    kp, _ = await _build(path_id)
    await _assess(path_id, kp, FIRST_HALF, turn="t1")
    await _assess(path_id, kp, SECOND_HALF, session="s2", turn="t2")
    assert judged[1] == SECOND_HALF


@pytest.mark.asyncio
async def test_moving_to_another_objective_drops_the_partial(path_id, judged):
    kp, other = await _build(path_id)
    await _assess(path_id, kp, FIRST_HALF, turn="t1")
    await _assess(path_id, other, UNRELATED, turn="t2")
    await _assess(path_id, kp, SECOND_HALF, turn="t3")
    assert judged[2] == SECOND_HALF


@pytest.mark.asyncio
async def test_deferring_the_objective_drops_the_partial(path_id, judged):
    kp, _ = await _build(path_id)
    await _assess(path_id, kp, FIRST_HALF, turn="t1")
    deferred = await MasteryDeferObjectiveTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=STUDY,
        _session_id="s1",
        _turn_id="t2",
        knowledge_point_id=kp,
    )
    assert deferred.success, deferred.content
    await _assess(path_id, kp, SECOND_HALF, turn="t3")
    assert judged[1] == SECOND_HALF


@pytest.mark.asyncio
async def test_an_incorrect_grade_is_not_kept(path_id, monkeypatch):
    answers: list[str] = []

    async def judge(_config, items):
        answers.extend(item["answer"] for item in items)
        verdict = semantic_assessment.Verdict(
            result="incorrect", confidence=0.95, feedback="This is not what the schedule does."
        )
        return {item["question_id"]: verdict for item in items}

    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    kp, _ = await _build(path_id)
    await _assess(path_id, kp, UNRELATED, turn="t1")
    await _assess(path_id, kp, FIRST_HALF, turn="t2")
    assert answers[1] == FIRST_HALF


@pytest.mark.asyncio
async def test_an_expired_partial_is_dropped(path_id, judged, monkeypatch):
    from deeptutor.learning import storage

    kp, _ = await _build(path_id)
    await _assess(path_id, kp, FIRST_HALF, turn="t1")
    monkeypatch.setattr(storage, "PENDING_EXPLANATION_TTL_SECONDS", -1)
    await _assess(path_id, kp, SECOND_HALF, turn="t2")
    assert judged[1] == SECOND_HALF
