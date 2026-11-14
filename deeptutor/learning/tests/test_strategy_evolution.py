"""Evidence-gated, independently-reviewed strategy evolution.

The proposer and reviewer are the only model calls; every gate and hard rule is
deterministic, so most of this is exercised with a canned model.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.storage import LearningStore
from deeptutor.learning.strategy_evolution import (
    MAX_STRATEGY_NOTES,
    evolve_strategy,
    strategy_evidence,
)
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
        path_name="演化路径",
        modules=[
            {
                "name": "模块",
                "objective": "能说出这一节在讲什么",
                "knowledge_points": [{"name": "概念甲", "type": "concept"}],
            }
        ],
    )
    assert result.success, result.content
    return LearningStore().load(path_id).modules[0].knowledge_points[0].id


async def _observe(path_id: str, kp: str, key: str, strategy: str, outcome: str, evidence: str = "") -> None:
    result = await MasteryObserveTool().execute(
        _mastery_path_id=path_id,
        _learner_message=evidence or "你先讲吧",
        knowledge_point_id=kp,
        strategy=strategy,
        key=key,
        outcome=outcome,
        evidence=evidence,
    )
    assert result.success, result.content


def _fake_llm(proposer: dict, reviewer: dict, calls: list[str] | None = None):
    async def _llm(prompt: str, system_prompt: str) -> str:
        if calls is not None:
            calls.append("reviewer" if "independent reviewer" in system_prompt else "proposer")
        return json.dumps(reviewer if "independent reviewer" in system_prompt else proposer)

    return _llm


def test_gate_needs_two_decisive_results_or_one_plus_a_like(store):
    from deeptutor.learning.models import LearnerProfile, TeachingObservation

    def profile(*outcomes):
        return LearnerProfile(
            teaching_observations={
                f"k{i}": TeachingObservation(
                    knowledge_point_id="kp", text="t", strategy=f"s{i}", outcome=o, basis="learner_report", evidence="e"
                )
                for i, o in enumerate(outcomes)
            }
        )

    assert strategy_evidence(profile("unknown"), None, [])["gate"]["met"] is False
    assert strategy_evidence(profile("not_helped"), None, [])["gate"]["met"] is False
    assert strategy_evidence(profile("not_helped", "helped"), None, [])["gate"]["met"] is True
    one = strategy_evidence(profile("not_helped"), {"count": 1}, [])["gate"]["met"]
    assert one is True


@pytest.mark.asyncio
async def test_gated_without_enough_evidence(store):
    kp = await _build("evolve_gated")
    await _observe("evolve_gated", kp, "k1", "micro_check_probe", "unknown")
    calls: list[str] = []
    result = await evolve_strategy(
        "evolve_gated",
        store=store,
        llm=_fake_llm({"action": "none"}, {"decision": "reject"}, calls),
    )
    assert result["status"] == "gated"
    assert calls == []  # the gate is deterministic; no model call happens


@pytest.mark.asyncio
async def test_applies_a_reviewed_proposal(store):
    kp = await _build("evolve_apply")
    await _observe("evolve_apply", kp, "k1", "micro_check_probe", "not_helped", "还是没懂")
    await _observe("evolve_apply", kp, "k2", "micro_check_probe", "not_helped", "越看越迷糊了")

    proposal = {
        "action": "create",
        "body": "先补前置再拆；少用微检测式提问",
        "strategies": ["micro_check_probe"],
        "reason": "two not_helped",
    }
    result = await evolve_strategy(
        "evolve_apply",
        store=store,
        llm=_fake_llm(proposal, {"decision": "accept", "reason": "supported"}),
    )
    assert result["status"] == "applied", result
    note = result["note"]
    assert note["created_by"] == "agent"
    assert note["body"] == "先补前置再拆；少用微检测式提问"
    assert note["evidence"] == [{"kind": "strategy", "name": "micro_check_probe"}]
    notes = store.list_strategy_notes("evolve_apply")
    assert [n["note_id"] for n in notes] == [note["note_id"]]


@pytest.mark.asyncio
async def test_reviewer_rejection_writes_nothing(store):
    kp = await _build("evolve_reject")
    await _observe("evolve_reject", kp, "k1", "term_trio", "helped", "懂了")
    await _observe("evolve_reject", kp, "k2", "term_trio", "helped", "明白了")

    proposal = {"action": "create", "body": "术语三件套", "strategies": ["term_trio"]}
    result = await evolve_strategy(
        "evolve_reject",
        store=store,
        llm=_fake_llm(proposal, {"decision": "reject", "reason": "thin evidence"}),
    )
    assert result["status"] == "rejected"
    assert result["review"]["reason"] == "thin evidence"
    assert store.list_strategy_notes("evolve_reject") == []


@pytest.mark.asyncio
async def test_citing_evidence_that_does_not_exist_is_rejected_without_review(store):
    kp = await _build("evolve_fake_evidence")
    await _observe("evolve_fake_evidence", kp, "k1", "term_trio", "helped", "懂了")
    await _observe("evolve_fake_evidence", kp, "k2", "term_trio", "helped", "明白了")

    calls: list[str] = []
    proposal = {"action": "create", "body": "编的", "strategies": ["invented_strategy"]}
    result = await evolve_strategy(
        "evolve_fake_evidence",
        store=store,
        llm=_fake_llm(proposal, {"decision": "accept"}, calls),
    )
    assert result["status"] == "rejected"
    assert "not in the bundle" in result["review"]["reason"]
    assert calls == ["proposer"]  # the reviewer never ran


@pytest.mark.asyncio
async def test_never_updates_a_learner_authored_note(store):
    kp = await _build("evolve_learner_note")
    await _observe("evolve_learner_note", kp, "k1", "term_trio", "helped", "懂了")
    await _observe("evolve_learner_note", kp, "k2", "term_trio", "helped", "明白了")
    learner_note = store.save_strategy_note(
        "evolve_learner_note", "mine", "我自己的笔记", created_by="learner"
    )

    proposal = {
        "action": "update",
        "note_id": learner_note["note_id"],
        "body": "被自动化改写了",
        "strategies": ["term_trio"],
    }
    result = await evolve_strategy(
        "evolve_learner_note",
        store=store,
        llm=_fake_llm(proposal, {"decision": "accept"}),
    )
    assert result["status"] == "rejected"
    assert "learner-authored" in result["review"]["reason"]
    unchanged = store.get_strategy_note("evolve_learner_note", learner_note["note_id"])
    assert unchanged["body"] == "我自己的笔记"
    assert unchanged["created_by"] == "learner"


@pytest.mark.asyncio
async def test_capped_when_the_note_limit_is_reached(store):
    kp = await _build("evolve_capped")
    await _observe("evolve_capped", kp, "k1", "term_trio", "helped", "懂了")
    await _observe("evolve_capped", kp, "k2", "term_trio", "helped", "明白了")
    for index in range(MAX_STRATEGY_NOTES):
        store.save_strategy_note("evolve_capped", f"note-{index}", f"笔记 {index}", created_by="agent")

    result = await evolve_strategy(
        "evolve_capped",
        store=store,
        llm=_fake_llm({"action": "create", "body": "新", "strategies": ["term_trio"]}, {"decision": "accept"}),
    )
    assert result["status"] == "capped"
