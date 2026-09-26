"""Regression coverage for Mastery Path state integrity (#1527).

Learning evidence must stay attached only to the objective and question it
was created for. These tests lock the three repairs: outline identity,
invalid-assessment rollback, and non-mastery deferral.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    InteractionStatus,
    KnowledgePoint,
    KnowledgeType,
    LearnerMasteryOverride,
    LearningModule,
    LearningProgress,
    MasteryInteraction,
    PendingQuestion,
    QuizAttempt,
    RepetitionState,
    ReviewTask,
)
from deeptutor.learning.policy import is_assessed_mastered, is_mastered, next_objective
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import (
    MasteryBuildTool,
    MasteryDeferObjectiveTool,
    MasteryGradeTool,
    MasteryQuizTool,
    MasteryRepairQuestionTool,
    MasteryReviseTool,
    MasterySkipQuestionTool,
    MasteryStatusTool,
)


def tool_payload(result):
    payload = (result.metadata or {}).get("mastery_quiz")
    return payload if isinstance(payload, dict) else json.loads(result.content)


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(tmp_path) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return "test_path"


def _kp(
    kp_id: str, name: str, module_id: str = "m1", kp_type: KnowledgeType = KnowledgeType.MEMORY
):
    return KnowledgePoint(id=kp_id, name=name, type=kp_type, module_id=module_id)


def _module(mod_id: str, points: list[KnowledgePoint], order: int = 0) -> LearningModule:
    return LearningModule(id=mod_id, name=f"Module {mod_id}", order=order, knowledge_points=points)


def _seed_objective_evidence(tx, kp_id: str, module_id: str, *, mastery: float = 1.0) -> None:
    tx.progress.mastery_levels[kp_id] = mastery
    tx.progress.qualitative_mastery[kp_id] = True
    tx.progress.quiz_attempts.append(
        QuizAttempt(
            question_id=f"q-{kp_id}",
            knowledge_point_id=kp_id,
            module_id=module_id,
            is_correct=True,
        )
    )
    tx.progress.error_records.append(
        ErrorRecord(
            id=f"err-{kp_id}",
            question_id=f"q-{kp_id}",
            knowledge_point_id=kp_id,
            module_id=module_id,
            error_type=ErrorType.APPLICATION_ERROR,
            status="graduated",
        )
    )
    tx.progress.repetition_states[kp_id] = RepetitionState(
        interval_index=2,
        consecutive_correct=2,
        consecutive_wrong=0,
        next_review_at=99.0,
    )
    tx.progress.review_queue.append(
        ReviewTask(
            id=f"rv-{kp_id}",
            knowledge_point_id=kp_id,
            knowledge_type=KnowledgeType.MEMORY,
            due_at=99.0,
            priority=1,
            state=tx.progress.repetition_states[kp_id],
        )
    )
    tx.progress.learner_mastery_overrides[kp_id] = LearnerMasteryOverride(
        knowledge_point_id=kp_id,
        note="prior claim",
    )
    tx.progress.feynman_retries[kp_id] = 1
    tx.progress.feynman_explanations[kp_id] = "old explanation"
    tx.touch()


def _evidence_ids(progress: LearningProgress) -> set[str]:
    ids = set(progress.mastery_levels)
    ids.update(progress.qualitative_mastery)
    ids.update(progress.repetition_states)
    ids.update(progress.learner_mastery_overrides)
    ids.update(progress.feynman_retries)
    ids.update(progress.feynman_explanations)
    ids.update(attempt.knowledge_point_id for attempt in progress.quiz_attempts)
    ids.update(record.knowledge_point_id for record in progress.error_records)
    ids.update(task.knowledge_point_id for task in progress.review_queue)
    ids.update(getattr(progress, "deferred_objectives", {}) or {})
    return ids


async def _build(path_id: str, modules: list[dict]) -> dict:
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=modules,
    )
    assert result.success, result.content
    return json.loads(result.content)


# ── 1. unrelated replace must not inherit positional state ─────────────────


@pytest.mark.asyncio
async def test_replace_unrelated_objective_does_not_inherit_positional_state(path_id):
    first = await _build(
        path_id,
        [{"name": "Logic", "knowledge_points": [{"name": "Truth tables", "type": "memory"}]}],
    )
    old_id = first["map"]["modules"][0]["knowledge_points"][0]["id"]
    store = LearningStore()
    service = LearningService(store)
    store.mutate(
        path_id, lambda tx: _seed_objective_evidence(tx, old_id, first["map"]["modules"][0]["id"])
    )

    rebuilt = await _build(
        path_id,
        [{"name": "Logic", "knowledge_points": [{"name": "Karnaugh maps", "type": "memory"}]}],
    )
    new_kp = rebuilt["map"]["modules"][0]["knowledge_points"][0]
    progress = store.load(path_id)
    assert progress is not None

    assert new_kp["id"] != old_id
    assert new_kp["status"] == "new"
    assert new_kp["mastery"] == 0.0
    assert new_kp["mastery_source"] == ""
    assert old_id not in _evidence_ids(progress)
    assert new_kp["id"] not in progress.mastery_levels
    assert new_kp["id"] not in {a.knowledge_point_id for a in progress.quiz_attempts}
    assert progress.pending_question is None
    assert store.get_active_interaction(path_id) is None

    events = store.list_events(path_id)
    identity = next(
        event.payload.get("identity_map")
        for event in reversed(events)
        if event.payload.get("identity_map")
    )
    assert old_id in identity["dropped"]
    assert new_kp["id"] in identity["minted"]
    assert old_id not in identity["preserved"]


# ── 2. reorder of unchanged objectives keeps evidence ──────────────────────


@pytest.mark.asyncio
async def test_replace_reorder_keeps_evidence_with_the_objective(path_id):
    built = await _build(
        path_id,
        [
            {
                "name": "Logic",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "De Morgan", "type": "memory"},
                ],
            }
        ],
    )
    first_id = built["map"]["modules"][0]["knowledge_points"][0]["id"]
    second_id = built["map"]["modules"][0]["knowledge_points"][1]["id"]
    store = LearningStore()
    store.mutate(
        path_id,
        lambda tx: _seed_objective_evidence(
            tx, first_id, built["map"]["modules"][0]["id"], mastery=0.8
        ),
    )
    store.mutate(
        path_id,
        lambda tx: _seed_objective_evidence(
            tx, second_id, built["map"]["modules"][0]["id"], mastery=0.4
        ),
    )

    rebuilt = await _build(
        path_id,
        [
            {
                "name": "Logic",
                "knowledge_points": [
                    {"name": "De Morgan", "type": "memory"},
                    {"name": "Truth tables", "type": "memory"},
                ],
            }
        ],
    )
    points = rebuilt["map"]["modules"][0]["knowledge_points"]
    progress = store.load(path_id)
    assert progress is not None

    assert [kp["name"] for kp in points] == ["De Morgan", "Truth tables"]
    assert points[0]["id"] == second_id
    assert points[1]["id"] == first_id
    assert progress.mastery_levels[first_id] == 0.8
    assert progress.mastery_levels[second_id] == 0.4
    assert {a.knowledge_point_id for a in progress.quiz_attempts} == {first_id, second_id}


# ── 3. deleting a pending objective abandons the interaction ───────────────


def test_deleting_pending_objective_abandons_question_and_interaction(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    first = _kp("kp1", "Keep me")
    doomed = _kp("kp2", "Drop me")
    service.replace_modules_for_path(
        "test", [_module("m1", [first, doomed])], identity_mode="explicit"
    )

    def prepare(tx):
        tx.progress.current_module_id = "m1"
        tx.progress.current_kp_index = 1
        pending = PendingQuestion(
            question_id="q-drop",
            knowledge_point_id="kp2",
            module_id="m1",
            prompt="Explain it",
            expected_answer="Clearly",
        )
        tx.progress.pending_question = pending
        tx.put_interaction(
            MasteryInteraction(
                interaction_id="q-drop",
                path_id="test",
                question=pending,
                session_id="session-1",
            )
        )
        tx.touch()

    store.mutate("test", prepare)
    progress = service.replace_modules_for_path(
        "test",
        [_module("m1", [first])],
        identity_mode="explicit",
        event_type="topic.map_edited",
    )

    assert progress.pending_question is None
    assert store.get_active_interaction("test") is None
    abandoned = store.get_interaction("test", "q-drop")
    assert abandoned is not None
    assert abandoned.status == InteractionStatus.ABANDONED


# ── 4. full replace vs targeted revise ─────────────────────────────────────


@pytest.mark.asyncio
async def test_full_replace_mints_new_id_for_rewritten_content(path_id):
    built = await _build(
        path_id,
        [
            {
                "name": "Logic",
                "objective": "Read a truth table",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "XOR meaning", "type": "concept"},
                ],
            }
        ],
    )
    module = built["map"]["modules"][0]
    tables_id = module["knowledge_points"][0]["id"]
    xor_id = module["knowledge_points"][1]["id"]
    store = LearningStore()
    store.mutate(
        path_id, lambda tx: _seed_objective_evidence(tx, tables_id, module["id"], mastery=0.8)
    )
    store.mutate(
        path_id, lambda tx: _seed_objective_evidence(tx, xor_id, module["id"], mastery=1.0)
    )

    rebuilt = await _build(
        path_id,
        [
            {
                "name": "Logic",
                "objective": "Read a truth table",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "Karnaugh maps", "type": "concept"},
                ],
            }
        ],
    )
    points = rebuilt["map"]["modules"][0]["knowledge_points"]
    progress = store.load(path_id)
    assert progress is not None

    assert points[0]["id"] == tables_id
    assert progress.mastery_levels[tables_id] == 0.8
    assert points[1]["id"] != xor_id
    assert points[1]["name"] == "Karnaugh maps"
    assert points[1]["status"] == "new"
    assert xor_id not in _evidence_ids(progress)


@pytest.mark.asyncio
async def test_targeted_revise_resets_only_the_rewritten_waypoint(path_id):
    built = await _build(
        path_id,
        [
            {
                "name": "Logic",
                "objective": "Read a truth table",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "XOR meaning", "type": "concept"},
                ],
            }
        ],
    )
    module = built["map"]["modules"][0]
    tables_id = module["knowledge_points"][0]["id"]
    xor_id = module["knowledge_points"][1]["id"]
    store = LearningStore()
    store.mutate(
        path_id, lambda tx: _seed_objective_evidence(tx, tables_id, module["id"], mastery=0.8)
    )

    revised = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        module_id=module["id"],
        rewrite=[{"knowledge_point_id": xor_id, "name": "Karnaugh maps", "type": "concept"}],
    )
    payload = json.loads(revised.content)
    progress = store.load(path_id)
    assert progress is not None

    assert payload["knowledge_points"][0]["id"] == tables_id
    assert payload["knowledge_points"][1]["id"] != xor_id
    assert progress.mastery_levels[tables_id] == 0.8
    assert xor_id not in _evidence_ids(progress)
    events = store.list_events(path_id)
    last_replace = next(
        event for event in reversed(events) if event.event_type == "path.module_revised"
    )
    assert last_replace.payload["identity_map"]["mode"] == "explicit"


# ── 5. invalid question void / correct ─────────────────────────────────────


def test_void_invalid_question_recomputes_mastery_and_review(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    kp = _kp("kp1", "Truth tables")
    service.replace_modules_for_path("book1", [_module("m1", [kp])])
    scheduler = SpacedRepetitionScheduler()
    service.grade_and_record(
        store.load("book1"),
        question_id="q-bad",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="C",
        expected_answer="B",
        question_type="choice",
        scheduler=scheduler,
    )
    before = store.load("book1")
    assert before is not None
    assert before.quiz_attempts[0].is_correct is False
    assert before.mastery_levels["kp1"] == 0.0
    assert before.error_records

    progress, details = service.repair_question(
        "book1",
        "q-bad",
        action="void",
        reason="answer key pointed at the wrong option",
        scheduler=scheduler,
    )
    assert details["action"] == "void"
    assert progress.quiz_attempts[0].voided is True
    assert progress.mastery_levels.get("kp1", 0.0) == 0.0
    assert all(record.question_id != "q-bad" for record in progress.error_records)
    assert "kp1" not in progress.repetition_states
    assert progress.review_queue == []
    assert next_objective(progress).knowledge_point_id == "kp1"
    assert next_objective(progress).status != "mastered"


def test_void_removes_only_evidence_for_that_question(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    service.replace_modules_for_path("book1", [_module("m1", [_kp("kp1", "Truth tables")])])
    scheduler = SpacedRepetitionScheduler()
    for question_id in ("q-keep", "q-void"):
        service.grade_and_record(
            store.load("book1"),
            question_id=question_id,
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="A",
            expected_answer="B",
            question_type="choice",
            scheduler=scheduler,
        )

    progress, _ = service.repair_question(
        "book1",
        "q-void",
        action="void",
        reason="invalid second question",
        scheduler=scheduler,
    )

    assert [event.question_id for event in progress.learning_evidence] == ["q-keep"]
    assert progress.repetition_states["kp1"].review_count == 1


def test_correct_answer_key_regrades_and_restores_mastery(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    kp = _kp("kp1", "Truth tables")
    service.replace_modules_for_path("book1", [_module("m1", [kp])])
    scheduler = SpacedRepetitionScheduler()
    for question_id, answer, expected in (
        ("q1", "C", "B"),
        ("q2", "C", "C"),
        ("q3", "C", "C"),
    ):
        service.grade_and_record(
            store.load("book1"),
            question_id=question_id,
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer=answer,
            expected_answer=expected,
            question_type="choice",
            scheduler=scheduler,
        )
    before = store.load("book1")
    assert before is not None
    assert before.quiz_attempts[0].is_correct is False

    progress, details = service.repair_question(
        "book1",
        "q1",
        action="correct",
        expected_answer="C",
        reason="C was the factually correct option",
        scheduler=scheduler,
    )
    assert details["is_correct"] is True
    assert progress.quiz_attempts[0].is_correct is True
    assert progress.quiz_attempts[0].voided is False
    assert progress.mastery_levels["kp1"] == 1.0
    assert all(
        record.status == "graduated"
        for record in progress.error_records
        if record.question_id == "q1"
    )


@pytest.mark.asyncio
async def test_repair_question_tool_voids_wrong_key_from_question_bank(
    path_id, tmp_path, monkeypatch
):
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    session_store = SQLiteSessionStore(db_path=tmp_path / "chat.db")
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store", lambda: session_store
    )
    session = await session_store.create_session(title="Mastery Session")
    await _build(
        path_id,
        [{"name": "Logic", "knowledge_points": [{"name": "Truth tables", "type": "memory"}]}],
    )
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]
    quiz = tool_payload(
        await MasteryQuizTool().execute(
            _mastery_path_id=path_id,
            knowledge_point_id=kp_id,
            question="Which statement is true?",
            expected_answer="B",
            question_type="choice",
            options=[
                {"label": "A", "body": "false claim"},
                {"label": "B", "body": "also false"},
                {"label": "C", "body": "the true statement"},
            ],
        )
    )
    graded = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id=session["id"],
                _turn_id="turn_void_1",
                answer="C",
            )
        ).content
    )
    assert graded["is_correct"] is False
    assert (await session_store.list_notebook_entries(is_correct=False))["total"] == 1

    repaired = json.loads(
        (
            await MasteryRepairQuestionTool().execute(
                _mastery_path_id=path_id,
                _session_id=session["id"],
                _turn_id="turn_void_1",
                question_id=quiz["question_id"],
                action="void",
                reason="expected_answer pointed at an incorrect option",
            )
        ).content
    )
    assert repaired["action"] == "void"
    assert repaired["mastered"] is False
    wrong_after = await session_store.list_notebook_entries(is_correct=False)
    assert wrong_after["total"] == 0
    kept = await session_store.list_notebook_entries()
    assert kept["total"] == 1
    assert kept["items"][0]["is_correct"] is False
    assert kept["items"][0]["result"] == "voided"
    attempts = await session_store.list_assessment_attempts(
        session["id"], question_id=quiz["question_id"]
    )
    assert [attempt["result"] for attempt in attempts] == ["incorrect", "voided"]


# ── 6. defer advances without faking mastery ───────────────────────────────


@pytest.mark.asyncio
async def test_defer_advances_route_without_marking_mastered(path_id):
    await _build(
        path_id,
        [
            {
                "name": "Logic",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "De Morgan", "type": "memory"},
                ],
            }
        ],
    )
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    first_id = status["next"]["knowledge_point_id"]
    await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=first_id,
        question="2+2?",
        expected_answer="4",
    )

    deferred = json.loads(
        (await MasteryDeferObjectiveTool().execute(_mastery_path_id=path_id)).content
    )
    progress = LearningStore().load(path_id)
    assert progress is not None
    first = progress.modules[0].knowledge_points[0]
    second = progress.modules[0].knowledge_points[1]

    assert deferred["knowledge_point_id"] == first.id
    assert deferred["next"]["knowledge_point_id"] == second.id
    assert first.id in progress.deferred_objectives
    assert is_mastered(progress, first) is False
    assert is_assessed_mastered(progress, first) is False
    assert first.id not in progress.learner_mastery_overrides
    assert progress.pending_question is None
    assert LearningStore().get_active_interaction(path_id) is None
    summary = deferred["map"]["modules"][0]["knowledge_points"][0]
    assert summary["status"] != "mastered"
    assert summary["deferred"] is True


@pytest.mark.asyncio
async def test_skip_question_stays_on_the_same_objective(path_id):
    await _build(
        path_id,
        [
            {
                "name": "Logic",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "De Morgan", "type": "memory"},
                ],
            }
        ],
    )
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    first_id = status["next"]["knowledge_point_id"]
    await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=first_id,
        question="2+2?",
        expected_answer="4",
    )
    skipped = json.loads(
        (await MasterySkipQuestionTool().execute(_mastery_path_id=path_id)).content
    )
    progress = LearningStore().load(path_id)
    assert progress is not None
    assert skipped["next"]["knowledge_point_id"] == first_id
    assert skipped["instruction"].startswith("The question was abandoned")
    assert "different question" in skipped["instruction"]
    assert is_mastered(progress, progress.modules[0].knowledge_points[0]) is False
    assert not getattr(progress, "deferred_objectives", {})


def test_legacy_quiz_attempt_without_voided_stays_counted():
    attempt = QuizAttempt.model_validate(
        {"question_id": "q1", "knowledge_point_id": "kp1", "is_correct": True}
    )
    assert attempt.voided is False
    progress = LearningProgress(book_id="old")
    progress.modules = [_module("m1", [_kp("kp1", "Legacy")])]
    assert progress.deferred_objectives == {}
