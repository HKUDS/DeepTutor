"""mastery_observe: the flat strategy-observation recorder.

The nested ``teaching_updates`` array on ``mastery_profile`` is where a weaker
model drops the write. This tool is the flat alternative: one strategy, one
outcome, one quote — and it must land in the evidence the tutor reads back.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.storage import LearningStore
from deeptutor.learning.teaching import strategy_outcomes
from deeptutor.tools.mastery_tool import MasteryBuildTool, MasteryObserveTool


@pytest.fixture
def store(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(tmp_path) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return LearningStore()


async def _build(path_id: str) -> str:
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        path_name="观察路径",
        modules=[
            {
                "name": "模块",
                "objective": "能说出这一节在讲什么",
                "knowledge_points": [{"name": "概念甲", "type": "concept"}],
            }
        ],
    )
    assert result.success, result.content
    progress = LearningStore().load(path_id)
    return progress.modules[0].knowledge_points[0].id


@pytest.mark.asyncio
async def test_records_a_helped_observation_with_evidence(store):
    kp = await _build("observe_path")
    message = "这个顺序一过我就知道该不该去了"

    result = await MasteryObserveTool().execute(
        _mastery_path_id="observe_path",
        _learner_message=message,
        knowledge_point_id=kp,
        strategy="framework_first",
        outcome="helped",
        evidence=message,
    )
    assert result.success, result.content
    payload = json.loads(result.content)
    assert payload["status"] == "recorded"
    assert payload["strategy"] == "framework_first"
    assert payload["outcome"] == "helped"

    profile = store.load("observe_path").learner_profile
    observations = list(profile.teaching_observations.values())
    assert len(observations) == 1
    assert observations[0].strategy == "framework_first"
    assert observations[0].outcome == "helped"
    assert observations[0].evidence == message

    outcomes = strategy_outcomes(profile)
    assert outcomes["total"] == 1
    assert outcomes["strategies"][0]["helped"] == 1


@pytest.mark.asyncio
async def test_unknown_outcome_needs_no_evidence(store):
    kp = await _build("observe_unknown")
    result = await MasteryObserveTool().execute(
        _mastery_path_id="observe_unknown",
        _learner_message="你先讲吧",
        knowledge_point_id=kp,
        strategy="detail_first",
    )
    assert result.success, result.content
    profile = store.load("observe_unknown").learner_profile
    observation = next(iter(profile.teaching_observations.values()))
    assert observation.outcome == "unknown"
    assert observation.basis == "tentative"
    # An unattributed attempt is not a recorded result.
    assert strategy_outcomes(profile)["total"] == 0


@pytest.mark.asyncio
async def test_rejects_helped_without_a_real_quote(store):
    kp = await _build("observe_bad_evidence")
    result = await MasteryObserveTool().execute(
        _mastery_path_id="observe_bad_evidence",
        _learner_message="你先讲吧",
        knowledge_point_id=kp,
        strategy="framework_first",
        outcome="helped",
        evidence="the learner understood",  # not in the current message
    )
    assert not result.success
    assert "evidence" in result.content


@pytest.mark.asyncio
async def test_requires_a_strategy(store):
    kp = await _build("observe_no_strategy")
    result = await MasteryObserveTool().execute(
        _mastery_path_id="observe_no_strategy",
        _learner_message="你先讲吧",
        knowledge_point_id=kp,
        outcome="unknown",
    )
    assert not result.success
    assert "strategy" in result.content


@pytest.mark.asyncio
async def test_derives_revision_and_key_when_omitted(store):
    kp = await _build("observe_derived")
    result = await MasteryObserveTool().execute(
        _mastery_path_id="observe_derived",
        _learner_message="你先讲吧",
        knowledge_point_id=kp,
        strategy="term_trio",
    )
    assert result.success, result.content
    profile = store.load("observe_derived").learner_profile
    keys = list(profile.teaching_observations.keys())
    assert len(keys) == 1
    assert keys[0].startswith("term_trio_")


@pytest.mark.asyncio
async def test_evicts_the_oldest_when_the_cap_is_reached(store):
    import asyncio

    kp = await _build("observe_cap")
    for index in range(12):
        result = await MasteryObserveTool().execute(
            _mastery_path_id="observe_cap",
            _learner_message="你先讲吧",
            knowledge_point_id=kp,
            strategy=f"strategy_{index:02d}",
            key=f"strategy_{index:02d}",
        )
        assert result.success, result.content
        await asyncio.sleep(0.01)  # distinct updated_at ordering

    profile = store.load("observe_cap").learner_profile
    assert len(profile.teaching_observations) == 12
    assert "strategy_00" in profile.teaching_observations

    # The thirteenth must land: the oldest makes room instead of the write failing.
    result = await MasteryObserveTool().execute(
        _mastery_path_id="observe_cap",
        _learner_message="你先讲吧",
        knowledge_point_id=kp,
        strategy="strategy_new",
        key="strategy_new",
    )
    assert result.success, result.content
    profile = store.load("observe_cap").learner_profile
    assert len(profile.teaching_observations) == 12
    assert "strategy_new" in profile.teaching_observations
    assert "strategy_00" not in profile.teaching_observations
