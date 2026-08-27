"""Tests for the Mastery Path tools — the seam between the chat-loop tutor and
the engine. They drive the full loop the tutor uses: build a path, read the
gate, pose + grade questions, assess qualitative objectives, with the active
path id injected server-side (never by the model)."""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.models import InteractionStatus, PendingQuestion
from deeptutor.learning.storage import LearningStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.tools.mastery_tool import (
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryGradeTool,
    MasteryLeaveTool,
    MasteryPathsTool,
    MasteryQuizTool,
    MasteryStatusTool,
    MasterySwitchTool,
)


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    """Point the LearningStore at a temp workspace and yield a stable path id."""
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    return "test_path"


@pytest.fixture
def session_store(tmp_path, monkeypatch):
    store = SQLiteSessionStore(db_path=tmp_path / "chat.db")
    monkeypatch.setattr("deeptutor.services.session.get_sqlite_session_store", lambda: store)
    return store


def _store_init_factory(root):
    def _init(self, root_arg=None):  # mirrors LearningStore.__init__ signature
        from pathlib import Path

        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


async def _build_basic(path_id):
    build = MasteryBuildTool()
    return await build.execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=[
            {
                "name": "Module 1",
                "knowledge_points": [
                    {"name": "Truth tables", "type": "memory"},
                    {"name": "Why XOR matters", "type": "concept"},
                ],
            }
        ],
    )


# ── naming ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_names_the_path_and_a_rebuild_keeps_that_name(path_id):
    """A rebuild replaces the map, never the identity.

    Before paths had names, the display name was the first module's — so
    rebuilding renamed the course out from under the learner, and the tutor
    could no longer find "the quadratics path" they asked to switch back to.
    """
    build = MasteryBuildTool()
    first = await build.execute(
        _mastery_path_id=path_id,
        path_name="一元二次方程基础",
        modules=[{"name": "模块一：定义", "knowledge_points": [{"name": "标准形式"}]}],
    )
    assert json.loads(first.content)["path_name"] == "一元二次方程基础"

    rebuilt = await build.execute(
        _mastery_path_id=path_id,
        mode="replace",
        path_name="配方法",
        modules=[{"name": "模块一：配方法", "knowledge_points": [{"name": "配方法解方程"}]}],
    )
    payload = json.loads(rebuilt.content)
    assert payload["path_name"] == "一元二次方程基础"
    assert payload["map"]["modules"][0]["name"] == "模块一：配方法"
    assert LearningStore().load(path_id).name == "一元二次方程基础"


@pytest.mark.asyncio
async def test_build_without_a_name_still_reports_the_derived_one(path_id):
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        modules=[{"name": "Module 1", "knowledge_points": [{"name": "Truth tables"}]}],
    )
    assert json.loads(result.content)["path_name"] == "Module 1"
    assert LearningStore().load(path_id).name == ""


@pytest.mark.asyncio
async def test_paths_listing_shows_the_stable_name(path_id):
    """What the tutor matches against when the learner names a path."""
    await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        path_name="Quadratics",
        modules=[{"name": "Module 1", "knowledge_points": [{"name": "Standard form"}]}],
    )
    await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=[{"name": "Completing the square", "knowledge_points": [{"name": "Method"}]}],
    )

    payload = json.loads((await MasteryPathsTool().execute(_mastery_path_id=path_id)).content)
    assert [p["name"] for p in payload["paths"]] == ["Quadratics"]


# ── build ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_creates_path(path_id):
    result = await _build_basic(path_id)
    assert result.success
    payload = json.loads(result.content)
    assert payload["knowledge_points_added"] == 2
    assert payload["map"]["counts"]["total"] == 2


@pytest.mark.asyncio
async def test_build_rejects_empty_modules(path_id):
    result = await MasteryBuildTool().execute(_mastery_path_id=path_id, modules=[])
    assert result.success is False


@pytest.mark.asyncio
async def test_build_append_keeps_existing(path_id):
    await _build_basic(path_id)
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="append",
        modules=[
            {"name": "Module 2", "knowledge_points": [{"name": "Adders", "type": "procedure"}]}
        ],
    )
    payload = json.loads(result.content)
    assert payload["map"]["counts"]["total"] == 3  # 2 existing + 1 appended


@pytest.mark.asyncio
async def test_build_unknown_type_defaults_to_concept(path_id):
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        modules=[{"name": "M", "knowledge_points": [{"name": "Thing", "type": "nonsense"}]}],
    )
    kp = json.loads(result.content)["map"]["modules"][0]["knowledge_points"][0]
    assert kp["type"] == "concept"


# ── status ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_empty_path_asks_for_build(path_id):
    payload = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    assert payload["status"] == "empty"


@pytest.mark.asyncio
async def test_status_points_at_first_objective(path_id):
    await _build_basic(path_id)
    payload = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    assert payload["status"] == "active"
    assert payload["next"]["action"] == "probe"
    assert payload["next"]["knowledge_point_type"] == "memory"


@pytest.mark.asyncio
async def test_no_path_id_fails_closed():
    result = await MasteryStatusTool().execute(_mastery_path_id="")
    assert result.success is False


# ── quiz + grade: the deterministic objective gate ───────────────────────────


@pytest.mark.asyncio
async def test_quiz_then_grade_drives_memory_gate(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    quiz, grade = MasteryQuizTool(), MasteryGradeTool()
    mastered = False
    for _ in range(3):
        await quiz.execute(
            _mastery_path_id=path_id,
            knowledge_point_id=kp_id,
            question="2+2?",
            expected_answer="4",
            question_type="short",
        )
        result = json.loads((await grade.execute(_mastery_path_id=path_id, answer="4")).content)
        assert result["is_correct"] is True
        mastered = result["mastered"]
    # 0.5 -> 0.8 -> 1.0 ≥ 0.9: mastered only after the third correct answer.
    assert mastered is True


@pytest.mark.asyncio
async def test_grade_without_pending_fails(path_id):
    await _build_basic(path_id)
    result = await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="x")
    assert result.success is False


@pytest.mark.asyncio
async def test_quiz_unknown_kp_fails(path_id):
    await _build_basic(path_id)
    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id="nope",
        question="?",
        expected_answer="x",
    )
    assert result.success is False


@pytest.mark.asyncio
async def test_wrong_answer_does_not_master(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]
    await MasteryQuizTool().execute(
        _mastery_path_id=path_id, knowledge_point_id=kp_id, question="2+2?", expected_answer="4"
    )
    result = json.loads(
        (await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="5")).content
    )
    assert result["is_correct"] is False
    assert result["mastered"] is False


@pytest.mark.asyncio
async def test_grade_syncs_mastery_attempt_to_question_bank(path_id, session_store):
    session = await session_store.create_session(title="Mastery Session")
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]
    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
                question_type="short",
            )
        ).content
    )

    result = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id=session["id"],
                _turn_id="turn_mastery_1",
                answer="5",
            )
        ).content
    )

    assert result["is_correct"] is False
    wrong_entries = await session_store.list_notebook_entries(is_correct=False)
    assert wrong_entries["total"] == 1
    entry = wrong_entries["items"][0]
    assert entry["session_title"] == "Mastery Session"
    assert entry["turn_id"] == "turn_mastery_1"
    assert entry["question"] == "2+2?"
    assert entry["question_type"] == "short_answer"
    assert entry["user_answer"] == "5"
    assert entry["correct_answer"] == "4"
    assert entry["is_correct"] is False

    # An idempotent retry with a changed model argument must not overwrite the
    # committed learner answer in the auxiliary question bank.
    replay = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id=session["id"],
                _turn_id="turn_mastery_2",
                question_id=quiz["question_id"],
                answer="4",
            )
        ).content
    )
    assert replay["replayed"] is True
    entries_after_replay = await session_store.list_notebook_entries()
    assert entries_after_replay["total"] == 1
    assert entries_after_replay["items"][0]["user_answer"] == "5"
    assert entries_after_replay["items"][0]["is_correct"] is False


@pytest.mark.asyncio
async def test_choice_quiz_rejects_bare_option_labels(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Which order is correct?",
        expected_answer="A",
        question_type="choice",
        options=["A", "B", "C", "D"],
    )

    assert result.success is False
    assert "full option bodies" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("type_kwargs", "expected_answer"),
    [
        ({}, "B"),
        ({"question_type": ""}, "blue"),
    ],
)
async def test_quiz_infers_choice_and_normalizes_expected_answer(
    path_id, type_kwargs, expected_answer
):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Pick a colour",
        expected_answer=expected_answer,
        options=["A: red", "B: blue"],
        **type_kwargs,
    )

    assert result.success is True
    pending = LearningStore().load(path_id).pending_question
    assert pending is not None
    assert pending.question_type == "choice"
    assert pending.expected_answer == "B"
    assert pending.options == ["A: red", "B: blue"]


@pytest.mark.asyncio
@pytest.mark.parametrize("question_type", ["short", "open"])
async def test_explicit_non_choice_without_options_is_unchanged(path_id, question_type):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Explain it",
        expected_answer="stored as written",
        question_type=question_type,
        options=[],
    )

    assert result.success is True
    pending = LearningStore().load(path_id).pending_question
    assert pending is not None
    assert pending.question_type == question_type
    assert pending.expected_answer == "stored as written"
    assert pending.options == []


@pytest.mark.asyncio
@pytest.mark.parametrize("question_type", ["short", "open"])
async def test_explicit_non_choice_rejects_options(path_id, question_type):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Explain it",
        expected_answer="answer",
        question_type=question_type,
        options=["A: first", "B: second"],
    )

    assert result.success is False
    assert "cannot be used" in result.content
    assert LearningStore().load(path_id).pending_question is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "error"),
    [
        ("A: first, B: second", "must be an array"),
        (["A: first", "A: second", "B: third"], "must run A, B, C"),
        (["A: repeated answer", "B: repeated answer"], "same answer"),
        (["A: Repeated   answer", "B: repeated answer"], "same answer"),
        (["A: repeated\nanswer", "B: repeated answer"], "same answer"),
        (["A: Straße", "B: STRASSE"], "same answer"),
        (["A: first", "B: second", "C: first"], "same answer"),
        (["A: first", ""], "non-empty strings"),
    ],
)
async def test_choice_quiz_rejects_malformed_options(path_id, options, error):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Pick one",
        expected_answer="A",
        question_type="choice",
        options=options,
    )

    assert result.success is False
    assert error in result.content
    assert LearningStore().load(path_id).pending_question is None


@pytest.mark.asyncio
async def test_choice_quiz_requires_options_even_when_type_is_explicit(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Pick one",
        expected_answer="A",
        question_type="choice",
        options=[],
    )

    assert result.success is False
    assert "full option bodies" in result.content


@pytest.mark.asyncio
async def test_choice_grade_reads_an_answer_typed_in_the_composer(path_id):
    """The card is not the only way in: a typed answer must grade the same."""
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Which is the general form?",
        expected_answer="C",
        question_type="choice",
        options=[
            "A: 3x² - 3x = 2x + 8",
            "B: 3x² - x - 8 = 0",
            "C: 3x² - 5x - 8 = 0",
            "D: 3x² - 5x + 8 = 0",
        ],
    )

    grade = await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="选C")
    assert grade.success is True
    assert json.loads(grade.content)["is_correct"] is True


@pytest.mark.asyncio
async def test_choice_grade_refuses_an_unreadable_answer_instead_of_failing_it(path_id):
    """An answer we cannot map to one option is unreadable, not wrong."""
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Which is the general form?",
        expected_answer="A",
        question_type="choice",
        options=["A: 3x² - 5x - 8 = 0", "B: 3x² - 5x + 8 = 0"],
    )

    grade = await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="A or B")
    assert grade.success is False
    assert "NOT graded" in grade.content
    # Nothing was recorded, so the question is still open for a real answer.
    progress = LearningStore().load(path_id)
    assert progress.pending_question is not None
    assert progress.quiz_attempts == []


@pytest.mark.asyncio
async def test_choice_quiz_preserves_bodies_and_normalizes_answer(path_id, session_store):
    session = await session_store.create_session(title="Choice Mastery")
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    quiz = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Where is the stop condition added?",
        expected_answer="Step 6",
        question_type="choice",
        options=[
            "A: Step 2 — write the first tool",
            "B: Step 4 — test one call",
            "C: Step 6 — add the stop condition",
            "D: Step 7 — add another tool",
        ],
    )
    assert quiz.success is True

    grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id=session["id"],
                _turn_id="turn_choice_1",
                answer="C",
            )
        ).content
    )
    assert grade["is_correct"] is True

    entries = await session_store.list_notebook_entries()
    entry = entries["items"][0]
    assert entry["options"] == {
        "A": "Step 2 — write the first tool",
        "B": "Step 4 — test one call",
        "C": "Step 6 — add the stop condition",
        "D": "Step 7 — add another tool",
    }
    assert entry["correct_answer"] == "C"
    assert entry["user_answer"] == "C"
    assert entry["is_correct"] is True


@pytest.mark.asyncio
async def test_pending_choice_status_reuses_public_contract_without_answer(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]

    registered = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="Pick a colour",
                expected_answer="blue",
                question_type="choice",
                options=["A: red", "B: blue"],
            )
        ).content
    )
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)

    pending = status["next"]["pending_question"]
    assert pending == registered["pending_question"]
    assert registered["ask_user"]["questions"][0] == {
        "id": pending["question_id"],
        "prompt": "Pick a colour",
        "options": [
            {"label": "A", "description": "red"},
            {"label": "B", "description": "blue"},
        ],
        "multi_select": False,
        "allow_free_text": True,
    }
    assert "expected_answer" not in registered
    assert "expected_answer" not in pending


@pytest.mark.asyncio
async def test_choice_grade_accepts_unique_persisted_body(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]
    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="Pick a colour",
                expected_answer="B",
                question_type="choice",
                options=["A: red", "B: blue"],
            )
        ).content
    )

    grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=quiz["question_id"],
                answer="blue",
            )
        ).content
    )

    assert grade["is_correct"] is True


@pytest.mark.asyncio
async def test_choice_grade_rejects_stale_question_id_without_clearing_pending(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]
    await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Pick a colour",
        expected_answer="B",
        question_type="choice",
        options=["A: red", "B: blue"],
    )

    grade = await MasteryGradeTool().execute(
        _mastery_path_id=path_id,
        question_id="stale-question",
        answer="B",
    )

    assert grade.success is False
    assert LearningStore().load(path_id).pending_question is not None


@pytest.mark.asyncio
async def test_choice_grade_keeps_legacy_bare_label_pending_compatible(path_id):
    await _build_basic(path_id)
    progress = LearningStore().load(path_id)
    assert progress is not None
    kp_id = progress.modules[0].knowledge_points[0].id
    progress.pending_question = PendingQuestion(
        question_id="legacy-question",
        knowledge_point_id=kp_id,
        module_id=progress.modules[0].id,
        prompt="Legacy choice",
        question_type="choice",
        expected_answer="B",
        options=["A", "B"],
    )
    LearningStore().save(progress)

    grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id="legacy-question",
                answer="B",
            )
        ).content
    )

    assert grade["is_correct"] is True


@pytest.mark.asyncio
async def test_duplicate_quiz_and_grade_are_idempotent(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]

    first_quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                _session_id="session-1",
                _turn_id="turn-1",
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
            )
        ).content
    )
    retry_quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                _session_id="session-1",
                _turn_id="turn-1",
                knowledge_point_id=kp_id,
                question="A model-authored replacement must not win",
                expected_answer="5",
            )
        ).content
    )
    assert retry_quiz["question_id"] == first_quiz["question_id"]
    assert retry_quiz["pending_question"]["prompt"] == "2+2?"
    assert retry_quiz["status"] == "already_pending"

    first_grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id="session-1",
                _turn_id="turn-1",
                question_id=first_quiz["question_id"],
                answer="4",
            )
        ).content
    )
    retry_grade = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id="session-1",
                _turn_id="turn-1",
                question_id=first_quiz["question_id"],
                answer="4",
            )
        ).content
    )

    progress = LearningStore().load(path_id)
    interaction = LearningStore().get_interaction(path_id, first_quiz["question_id"])
    assert progress is not None
    assert len(progress.quiz_attempts) == 1
    assert retry_grade["replayed"] is True
    assert retry_grade["path_revision"] == first_grade["path_revision"]
    assert interaction is not None
    assert interaction.status == InteractionStatus.GRADED
    assert LearningStore().get_active_interaction(path_id) is None


@pytest.mark.asyncio
async def test_new_quiz_repairs_stale_legacy_pending_after_grade(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]
    first = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="First?",
                expected_answer="yes",
            )
        ).content
    )
    await MasteryGradeTool().execute(
        _mastery_path_id=path_id,
        question_id=first["question_id"],
        answer="yes",
    )
    store = LearningStore()
    progress = store.load(path_id)
    graded = store.get_interaction(path_id, first["question_id"])
    assert progress is not None and graded is not None
    progress.pending_question = graded.question
    store.save(progress)

    second_result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Second?",
        expected_answer="yes",
    )
    second = json.loads(second_result.content)

    assert second_result.success is True
    assert second["status"] == "registered"
    assert second["question_id"] != first["question_id"]


@pytest.mark.asyncio
async def test_status_recovers_answered_interaction_without_exposing_answer_key(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]
    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
            )
        ).content
    )
    from deeptutor.learning.service import LearningService

    LearningService().record_question_answer(
        path_id,
        "4",
        interaction_id=quiz["question_id"],
    )

    recovered = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    assert recovered["pending_interaction"] == {
        "question_id": quiz["question_id"],
        "status": "answered",
        "learner_answer": "4",
    }
    assert "expected_answer" not in json.dumps(recovered)

    # The committed learner reply is authoritative even if a later model
    # round accidentally paraphrases or changes the tool argument.
    graded = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=quiz["question_id"],
                answer="5",
            )
        ).content
    )
    assert graded["is_correct"] is True


@pytest.mark.asyncio
async def test_grade_recovers_unreadable_choice_answer(path_id):
    """An unreadable clarifying commit must not permanently block grading (#1004)."""
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]
    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="Compute (2e^{iπ/3})³",
                expected_answer="A",
                options=["A: -8", "B: -6", "C: 8", "D: -2"],
            )
        ).content
    )
    from deeptutor.learning.service import LearningService

    # Simulate the pre-fix deadlock: clarifying prose already persisted.
    LearningService().record_question_answer(
        path_id,
        "先告诉我三角恒等式是什么？",
        interaction_id=quiz["question_id"],
    )
    stuck = LearningStore().get_interaction(path_id, quiz["question_id"])
    assert stuck is not None
    assert stuck.status == InteractionStatus.ANSWERED

    blocked = await MasteryGradeTool().execute(
        _mastery_path_id=path_id,
        question_id=quiz["question_id"],
        answer="先告诉我三角恒等式是什么？",
    )
    assert blocked.success is False
    assert "NOT graded" in blocked.content

    recovered = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=quiz["question_id"],
                answer="A",
            )
        ).content
    )
    assert recovered["is_correct"] is True
    graded = LearningStore().get_interaction(path_id, quiz["question_id"])
    assert graded is not None
    assert graded.status == InteractionStatus.GRADED
    assert graded.user_answer == "A"


# ── assess: the qualitative gate ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assess_passes_concept(path_id):
    await _build_basic(path_id)
    # Drive past the memory objective so status reaches the concept one.
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    mem_kp = status["next"]["knowledge_point_id"]
    for _ in range(3):
        await MasteryQuizTool().execute(
            _mastery_path_id=path_id, knowledge_point_id=mem_kp, question="q", expected_answer="a"
        )
        await MasteryGradeTool().execute(_mastery_path_id=path_id, answer="a")

    status2 = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    concept_kp = status2["next"]["knowledge_point_id"]
    assert status2["next"]["action"] == "probe"
    assert status2["next"]["knowledge_point_type"] == "concept"

    result = json.loads(
        (
            await MasteryAssessTool().execute(
                _mastery_path_id=path_id, knowledge_point_id=concept_kp, passed=True, feedback="ok"
            )
        ).content
    )
    assert result["mastered"] is True
    assert result["next"]["action"] == "complete"
    progress = LearningStore().load(path_id)
    assert progress is not None
    assert progress.repetition_states[concept_kp].interval_index == 0
    assert [task.knowledge_point_id for task in progress.review_queue] == [mem_kp, concept_kp]


@pytest.mark.asyncio
async def test_assess_rejects_quantitative_type(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    mem_kp = status["next"]["knowledge_point_id"]  # a memory objective
    result = await MasteryAssessTool().execute(
        _mastery_path_id=path_id, knowledge_point_id=mem_kp, passed=True
    )
    assert result.success is False


# ── path switching: a conversation is not bound to one path ───────────────


async def _build_named(path_id: str, module_name: str) -> None:
    await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=[
            {
                "name": module_name,
                "knowledge_points": [{"name": f"{module_name} basics", "type": "concept"}],
            }
        ],
    )


@pytest.mark.asyncio
async def test_paths_tool_reports_every_path_and_marks_the_active_one(path_id):
    await _build_named("calculus", "Calculus")
    await _build_named("algebra", "Algebra")

    payload = json.loads((await MasteryPathsTool().execute(_mastery_path_id="algebra")).content)

    assert payload["active_path_id"] == "algebra"
    by_id = {entry["path_id"]: entry for entry in payload["paths"]}
    assert by_id.keys() == {"calculus", "algebra"}
    assert by_id["algebra"]["active"] is True
    assert by_id["calculus"]["active"] is False
    assert by_id["calculus"]["objectives"] == 1
    assert by_id["calculus"]["mastered"] == 0


@pytest.mark.asyncio
async def test_paths_tool_hides_paths_with_nothing_to_teach(path_id):
    await _build_named("calculus", "Calculus")
    # A conversation-owned scratch path exists as soon as a mastery turn runs,
    # long before anyone builds objectives into it.
    with LearningStore().transaction("empty_scratch", create=True):
        pass

    payload = json.loads((await MasteryPathsTool().execute(_mastery_path_id="calculus")).content)

    assert [entry["path_id"] for entry in payload["paths"]] == ["calculus"]


@pytest.mark.asyncio
async def test_switch_rebinds_the_running_turn_and_hands_over_the_lease(path_id, session_store):
    await _build_named("calculus", "Calculus")
    await _build_named("algebra", "Algebra")
    store = LearningStore()
    store.acquire_path_lease("calculus", "session-1", "turn-1")
    bound: list[str] = []

    result = await MasterySwitchTool().execute(
        path_id="algebra",
        _mastery_path_id="calculus",
        _session_id="session-1",
        _turn_id="turn-1",
        _bind_active_path=bound.append,
    )

    assert result.success
    payload = json.loads(result.content)
    assert payload["previous_path_id"] == "calculus"
    assert payload["active_path_id"] == "algebra"
    # The rest of THIS turn must operate on the new path...
    assert bound == ["algebra"]
    # ...and exclusion moves with it, rather than being held on both or neither.
    assert store.get_path_lease("calculus") is None
    assert store.get_path_lease("algebra").turn_id == "turn-1"


@pytest.mark.asyncio
async def test_switch_to_an_unknown_path_changes_nothing(path_id):
    await _build_named("calculus", "Calculus")
    store = LearningStore()
    store.acquire_path_lease("calculus", "session-1", "turn-1")
    bound: list[str] = []

    result = await MasterySwitchTool().execute(
        path_id="not_a_path",
        _mastery_path_id="calculus",
        _session_id="session-1",
        _turn_id="turn-1",
        _bind_active_path=bound.append,
    )

    assert not result.success
    assert "mastery_paths" in result.content
    assert bound == []
    assert store.get_path_lease("calculus").turn_id == "turn-1"


@pytest.mark.asyncio
async def test_switch_into_a_path_busy_elsewhere_keeps_the_current_one(path_id):
    await _build_named("calculus", "Calculus")
    await _build_named("algebra", "Algebra")
    store = LearningStore()
    store.acquire_path_lease("calculus", "session-1", "turn-1")
    store.acquire_path_lease("algebra", "session-2", "turn-2")
    bound: list[str] = []

    result = await MasterySwitchTool().execute(
        path_id="algebra",
        _mastery_path_id="calculus",
        _session_id="session-1",
        _turn_id="turn-1",
        _bind_active_path=bound.append,
    )

    assert not result.success
    assert "another conversation" in result.content
    assert bound == []
    # Rolled back onto the path the learner was already on.
    assert store.get_path_lease("calculus").turn_id == "turn-1"
    assert store.get_path_lease("algebra").turn_id == "turn-2"


@pytest.mark.asyncio
async def test_leave_falls_back_to_the_conversation_scratch_path(path_id, session_store):
    await _build_named("calculus", "Calculus")
    store = LearningStore()
    store.acquire_path_lease("calculus", "session-1", "turn-1")
    bound: list[str] = []

    result = await MasteryLeaveTool().execute(
        _mastery_path_id="calculus",
        _session_id="session-1",
        _turn_id="turn-1",
        _bind_active_path=bound.append,
    )

    assert result.success
    payload = json.loads(result.content)
    assert payload["previous_path_id"] == "calculus"
    assert payload["active_path_id"] == "session-1"
    assert bound == ["session-1"]
    # The course keeps everything and stays resumable.
    assert store.load("calculus") is not None
    assert store.get_path_lease("calculus") is None
    assert store.get_path_lease("session-1").turn_id == "turn-1"


@pytest.mark.asyncio
async def test_leave_makes_the_conversation_own_its_scratch_path(path_id, session_store):
    """Otherwise leaving strews empty orphan paths that nothing cleans up."""
    await _build_named("calculus", "Calculus")
    store = LearningStore()
    store.acquire_path_lease("calculus", "session-1", "turn-1")

    await MasteryLeaveTool().execute(
        _mastery_path_id="calculus",
        _session_id="session-1",
        _turn_id="turn-1",
        _bind_active_path=lambda _path_id: None,
    )
    removed = store.detach_session("session-1", delete_owned_orphans=True)

    assert removed == ["session-1"]
    assert store.exists("session-1") is False
    assert store.exists("calculus") is True


@pytest.mark.asyncio
async def test_quiz_explanation_reaches_the_question_bank(path_id, session_store):
    """A mastery mistake must be reviewable, not just scored.

    The sync used to hard-code ``explanation`` and ``difficulty`` to empty, so
    every question the mastery path contributed to the bank showed a bare
    right/wrong with nothing saying why.
    """
    await _build_basic(path_id)
    session = await session_store.create_session(title="Mastery Session")
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="What does NAND return for (1, 1)?",
                expected_answer="0",
                question_type="short",
                explanation="NAND is NOT AND, so two true inputs give false.",
                difficulty="medium",
            )
        ).content
    )

    # The reference explanation is answer-adjacent: it must never ride along
    # on the card the learner is about to answer.
    rendered = json.dumps(quiz["ask_user"], ensure_ascii=False)
    assert "NOT AND" not in rendered
    assert "NOT AND" not in json.dumps(quiz["pending_question"], ensure_ascii=False)

    await MasteryGradeTool().execute(
        _mastery_path_id=path_id,
        _session_id=session["id"],
        _turn_id="turn_mastery_1",
        question_id=quiz["question_id"],
        answer="1",
    )

    entry = (await session_store.list_notebook_entries())["items"][0]
    assert entry["is_correct"] is False
    assert entry["explanation"] == "NAND is NOT AND, so two true inputs give false."
    assert entry["difficulty"] == "medium"


@pytest.mark.asyncio
async def test_unusable_difficulty_is_dropped_not_rejected(path_id, session_store):
    """A mislabelled difficulty must never cost the learner the question."""
    await _build_basic(path_id)
    session = await session_store.create_session(title="Mastery Session")
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
                question_type="short",
                difficulty="extremely tricky",
            )
        ).content
    )
    assert quiz["status"] == "registered"

    await MasteryGradeTool().execute(
        _mastery_path_id=path_id,
        _session_id=session["id"],
        _turn_id="turn_mastery_1",
        question_id=quiz["question_id"],
        answer="5",
    )
    entry = (await session_store.list_notebook_entries())["items"][0]
    assert entry["difficulty"] == ""


@pytest.mark.asyncio
async def test_pending_question_without_explanation_still_deserializes(path_id):
    """Paths persisted before the field existed must load unchanged."""
    legacy = PendingQuestion.model_validate(
        {
            "question_id": "q1",
            "knowledge_point_id": "kp1",
            "prompt": "old question",
            "expected_answer": "yes",
        }
    )
    assert legacy.explanation == ""
    assert legacy.difficulty == ""
