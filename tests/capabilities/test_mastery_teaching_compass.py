"""Durable teaching feedback without altering learning evidence or mastery."""

import json

import pytest

from deeptutor.capabilities.mastery.tools import MasteryProfileTool, MasteryStatusTool
from deeptutor.learning.models import KnowledgePoint, LearningModule
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningConflictError, LearningStore


@pytest.fixture
def system(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    service.replace_modules_for_path(
        "path",
        [
            LearningModule(
                id="m",
                name="Basics",
                order=0,
                knowledge_points=[
                    KnowledgePoint(id="p1", name="Boundary", module_id="m", type="concept"),
                    KnowledgePoint(id="p2", name="Transport", module_id="m", type="concept"),
                ],
            )
        ],
    )
    return store, service


def preference(key="pace", text="Explain one useful step at a time"):
    return {
        "kind": "preference",
        "op": "upsert",
        "key": key,
        "text": text,
        "basis": "learner_report",
        "evidence": "Please explain in short steps.",
    }


def observation(**overrides):
    return {
        "kind": "observation",
        "op": "upsert",
        "key": "boundary-definition",
        "knowledge_point_id": "p1",
        "text": "Outside the layer confused the learner",
        "basis": "learner_report",
        "strategy": "Spatial example",
        "outcome": "unknown",
        "evidence": "Outside of what?",
        **overrides,
    }


def record(store, service, updates, **kwargs):
    learner_message = (
        " ".join(item.get("evidence", "") for item in updates if isinstance(item, dict))
        if isinstance(updates, list)
        else ""
    )
    return service.record_learner_profile(
        "path",
        fields={},
        teaching_updates=updates,
        expected_revision=store.load("path").version,
        session_id="session",
        turn_id="turn",
        learner_message=learner_message,
        **kwargs,
    )


def test_keyed_preferences_survive_reload_and_independent_edit_remove(system, tmp_path):
    store, service = system
    before = store.load("path")
    record(store, service, [preference(), preference("examples", "Use concrete examples")])
    record(store, service, [preference(text="Keep the explanation connected")])
    record(store, service, [{"kind": "preference", "op": "remove", "key": "examples"}])
    loaded = LearningStore(root=tmp_path).load("path")
    assert (
        loaded.learner_profile.teaching_preferences["pace"].text == "Keep the explanation connected"
    )
    assert "examples" not in loaded.learner_profile.teaching_preferences
    for field in (
        "modules",
        "mastery_levels",
        "quiz_attempts",
        "learning_evidence",
        "pending_question",
    ):
        assert getattr(loaded, field) == getattr(before, field)
    assert loaded.learner_profile.teaching_preferences["pace"].turn_id == "turn"


def test_duplicate_retry_is_noop_but_stale_replay_cannot_overwrite_new_feedback(system):
    store, service = system
    revision = store.load("path").version
    first, _ = service.record_learner_profile(
        "path",
        fields={},
        teaching_updates=[preference()],
        expected_revision=revision,
        learner_message=preference()["evidence"],
    )
    retry, changed = service.record_learner_profile(
        "path",
        fields={},
        teaching_updates=[preference()],
        expected_revision=revision,
        learner_message=preference()["evidence"],
    )
    assert changed == [] and retry.version == first.version
    record(store, service, [preference(text="Prefer a worked example")])
    with pytest.raises(LearningConflictError):
        service.record_learner_profile(
            "path",
            fields={},
            teaching_updates=[preference()],
            expected_revision=revision,
            learner_message=preference()["evidence"],
        )
    assert (
        store.load("path").learner_profile.teaching_preferences["pace"].text
        == "Prefer a worked example"
    )


@pytest.mark.parametrize(
    "update",
    [
        {**preference(), "unexpected": "no"},
        {**preference(), "basis": "tentative"},
        observation(knowledge_point_id="other-path-objective"),
        observation(outcome="helped", evidence=""),
        observation(outcome="helped", basis="tentative"),
        observation(outcome="helped", strategy=""),
        observation(text="x" * 401),
        {"kind": "observation", "op": "remove", "key": "not valid spaces"},
    ],
)
def test_invalid_feedback_is_rejected_atomically(system, update):
    store, service = system
    before = store.load("path").model_dump()
    with pytest.raises(ValueError):
        record(store, service, [preference(), update])
    assert store.load("path").model_dump() == before


def test_strategy_result_needs_learner_evidence_and_does_not_award_mastery(system):
    store, service = system
    record(store, service, [observation()])
    record(
        store,
        service,
        [observation(outcome="helped", evidence="I can now explain the boundary myself")],
    )
    profile = store.load("path").learner_profile
    assert profile.teaching_observations["boundary-definition"].outcome == "helped"
    assert store.load("path").learning_evidence == []
    assert store.load("path").mastery_levels == {}


def test_bounds_and_revision_are_required_without_silent_eviction(system):
    store, service = system
    with pytest.raises(ValueError, match="revision"):
        service.record_learner_profile(
            "path",
            fields={},
            teaching_updates=[preference()],
            learner_message=preference()["evidence"],
        )
    record(store, service, [preference(str(i)) for i in range(6)])
    with pytest.raises(ValueError, match="limit"):
        record(store, service, [preference("overflow")])
    assert len(store.load("path").learner_profile.teaching_preferences) == 6


@pytest.mark.parametrize("updates", [[], {}, [preference()] * 7, [preference(), preference()]])
def test_operation_batch_shape_and_duplicate_keys(system, updates):
    store, service = system
    with pytest.raises(ValueError):
        record(store, service, updates)


def test_legacy_profile_and_other_observations_survive_correction_and_removal(system):
    store, service = system
    service.record_learner_profile(
        "path", fields={"preferences": "Use ordinary language", "target_level": "Foundations"}
    )
    record(store, service, [observation(), observation(key="second", knowledge_point_id="p2")])
    record(
        store,
        service,
        [observation(outcome="not_helped", evidence="The spatial example still confuses me")],
    )
    record(store, service, [{"kind": "observation", "op": "remove", "key": "second"}])
    profile = store.load("path").learner_profile
    assert profile.preferences == "Use ordinary language"
    assert profile.target_level == "Foundations"
    assert profile.teaching_observations["boundary-definition"].outcome == "not_helped"
    assert "second" not in profile.teaching_observations


def test_mixed_legacy_and_structured_stale_update_rolls_back(system):
    store, service = system
    revision = store.load("path").version
    record(store, service, [preference()])
    before = store.load("path").model_dump()
    with pytest.raises(LearningConflictError):
        service.record_learner_profile(
            "path",
            fields={"target_level": "Unrelated stale change"},
            teaching_updates=[preference("new")],
            expected_revision=revision,
            learner_message=preference()["evidence"],
        )
    assert store.load("path").model_dump() == before


@pytest.mark.asyncio
async def test_native_snapshot_delivers_preferences_and_only_current_concept(monkeypatch, system):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    store, service = system
    record(
        store,
        service,
        [
            preference(),
            observation(),
            observation(
                key="transport",
                knowledge_point_id="p2",
                text="Tentative transport difficulty",
                basis="tentative",
            ),
        ],
    )
    monkeypatch.setattr("deeptutor.capabilities.mastery.tools._new_service", lambda: service)
    context = UnifiedContext(
        session_id="resumed", metadata={"mastery_mode": True, "mastery_path_id": "path"}
    )
    result = await MasteryLoopCapability().pre_loop(context, None)
    assert "Explain one useful step" in result.content
    assert "Outside the layer" in result.content
    assert "Tentative transport difficulty" not in result.content
    assert "unknown" in result.content
    assert "change" in result.content.lower()


@pytest.mark.asyncio
async def test_tool_uses_bound_path_and_reports_stale_revision(monkeypatch, system):
    store, service = system
    monkeypatch.setattr("deeptutor.capabilities.mastery.tools._new_service", lambda: service)
    tool = MasteryProfileTool()
    assert not (await tool.execute(teaching_updates=[preference()], expected_revision=0)).success
    result = await tool.execute(
        _mastery_path_id="path",
        _session_id="s",
        _turn_id="t",
        _learner_message=preference()["evidence"],
        teaching_updates=[preference()],
        expected_revision=store.load("path").version,
    )
    assert result.success
    assert json.loads(result.content)["learner_profile"]["teaching_preferences"]["pace"]["text"]
    record(store, service, [preference(text="Another approach")])
    stale = await tool.execute(
        _mastery_path_id="path",
        teaching_updates=[preference()],
        expected_revision=0,
        _learner_message=preference()["evidence"],
    )
    assert not stale.success and "changed" in stale.content.lower()
    missing = await tool.execute(
        _mastery_path_id="missing",
        teaching_updates=[preference()],
        expected_revision=0,
        _learner_message=preference()["evidence"],
    )
    assert not missing.success and "no longer exists" in missing.content


@pytest.mark.parametrize(
    "update", [preference(), observation(outcome="helped"), observation(basis="tentative")]
)
def test_fabricated_learner_quote_cannot_be_recorded(system, update):
    store, service = system
    before = store.load("path").model_dump()
    with pytest.raises(ValueError, match="quote"):
        service.record_learner_profile(
            "path",
            fields={},
            teaching_updates=[update],
            expected_revision=store.load("path").version,
            learner_message="Continue, please.",
        )
    assert store.load("path").model_dump() == before


def test_runtime_overwrites_spoofed_path_and_learner_message():
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    context = UnifiedContext(
        session_id="actual-session",
        user_message="Use a concrete example.",
        metadata={"mastery_mode": True, "mastery_path_id": "actual-path", "turn_id": "actual-turn"},
    )
    args = MasteryLoopCapability().augment_kwargs(
        "mastery_profile",
        {"_mastery_path_id": "spoofed", "_learner_message": "Invented evidence"},
        context,
    )
    assert args["_mastery_path_id"] == "actual-path"
    assert args["_learner_message"] == "Use a concrete example."
    assert args["_session_id"] == "actual-session" and args["_turn_id"] == "actual-turn"


def test_stale_retry_cannot_resurrect_removed_preference(system):
    store, service = system
    revision = store.load("path").version
    record(store, service, [preference()])
    record(store, service, [{"kind": "preference", "op": "remove", "key": "pace"}])
    with pytest.raises(LearningConflictError):
        service.record_learner_profile(
            "path",
            fields={},
            teaching_updates=[preference()],
            expected_revision=revision,
            learner_message=preference()["evidence"],
        )
    assert "pace" not in store.load("path").learner_profile.teaching_preferences


@pytest.mark.asyncio
async def test_explicit_inspection_returns_all_bounded_path_notes_without_mastery_changes(
    monkeypatch, system
):
    store, service = system
    record(
        store,
        service,
        [
            preference(),
            observation(),
            observation(key="transport", knowledge_point_id="p2", text="Transport confusion"),
        ],
    )
    monkeypatch.setattr("deeptutor.capabilities.mastery.tools._new_service", lambda: service)
    before = store.load("path").model_dump()
    normal = await MasteryStatusTool().execute(_mastery_path_id="path")
    full = await MasteryStatusTool().execute(_mastery_path_id="path", include_teaching_history=True)
    assert "Transport confusion" not in normal.content
    assert "Transport confusion" in full.content
    assert store.load("path").model_dump() == before
    invalid = await MasteryStatusTool().execute(
        _mastery_path_id="path", include_teaching_history="false"
    )
    assert not invalid.success and "boolean" in invalid.content


@pytest.mark.asyncio
async def test_tentative_teaching_note_does_not_complete_learner_intake(monkeypatch, system):
    store, service = system
    record(store, service, [observation(basis="tentative", evidence="")])
    monkeypatch.setattr("deeptutor.capabilities.mastery.tools._new_service", lambda: service)
    result = await MasteryStatusTool().execute(_mastery_path_id="path")
    status = json.loads(result.content)
    assert status["intake_needed"] is True
    assert (
        status["learner_profile"]["teaching_observations"]["boundary-definition"]["basis"]
        == "tentative"
    )
