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
    MasterySkipQuestionTool,
    MasteryStatusTool,
    MasterySwitchTool,
)


def tool_payload(result):
    """A tool's structured payload, wherever that tool carries it.

    ``mastery_quiz`` now poses the question itself, so its body is prose for
    the tutor and its payload rides in metadata. Every other tool still
    returns it as JSON content.
    """
    payload = (result.metadata or {}).get("mastery_quiz")
    return payload if isinstance(payload, dict) else json.loads(result.content)


def posed_card(result):
    """The learner-facing card ``mastery_quiz`` put in front of them."""
    return (result.metadata or {}).get("mastery_question")


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
async def test_skip_question_unblocks_registration_without_credit(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]
    first = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="First?",
                expected_answer="right",
            )
        )
    )
    from deeptutor.learning.service import LearningService

    LearningService().record_question_answer(
        path_id,
        "wrong",
        interaction_id=first["question_id"],
    )
    before = LearningStore().load(path_id)
    assert before is not None
    mastery_before = before.mastery_levels.get(kp_id, 0.0)

    result = await MasterySkipQuestionTool().execute(_mastery_path_id=path_id)
    skipped = json.loads(result.content)
    progress = LearningStore().load(path_id)
    abandoned = LearningStore().get_interaction(path_id, first["question_id"])

    assert result.success is True
    assert skipped["skipped"] is True
    assert skipped["question_id"] == first["question_id"]
    assert skipped["next"]["action"] != "answer_pending"
    assert progress is not None
    assert progress.pending_question is None
    assert progress.quiz_attempts == []
    assert progress.mastery_levels.get(kp_id, 0.0) == mastery_before
    assert abandoned is not None
    assert abandoned.status == InteractionStatus.ABANDONED
    assert LearningStore().get_active_interaction(path_id) is None

    replacement = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="Replacement?",
                expected_answer="right",
            )
        )
    )
    assert replacement["status"] == "registered"
    assert replacement["question_id"] != first["question_id"]


@pytest.mark.asyncio
async def test_skip_question_without_open_question_is_no_op(path_id):
    await _build_basic(path_id)
    before = LearningStore().load(path_id)
    assert before is not None

    result = await MasterySkipQuestionTool().execute(_mastery_path_id=path_id)
    payload = json.loads(result.content)
    after = LearningStore().load(path_id)

    assert result.success is True
    assert payload["skipped"] is False
    assert payload["question_id"] == ""
    assert after is not None
    assert after.version == before.version


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
    quiz = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
                question_type="short",
            )
        )
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
    assert entry["source"] == "mastery_path"
    assert entry["material_id"] == path_id
    assert entry["section_id"] == kp_id
    assert entry["section_title"] == "Truth tables"

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
    assert pending.choice_map == {"A": "red", "B": "blue"}


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
async def test_choice_quiz_accepts_ask_user_key_names(path_id):
    """``description`` is ask_user's word for the body; models mix them up.

    Rejecting the shape used to cost the learner the question outright: the
    model retried it every round until the budget was gone.
    """
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="How does LangGraph merge that update?",
        expected_answer="B",
        question_type="choice",
        options=[
            {"label": "A: overwrite the old value", "description": "the reducer never ran"},
            {"label": "B: concatenate both lists", "description": "the reducer ran"},
            {"label": "C: raise, the reducer rejects a list", "description": "annotation clash"},
        ],
    )

    assert result.success is True
    pending = LearningStore().load(path_id).pending_question
    assert pending is not None
    assert pending.choice_map == {
        "A": "overwrite the old value",
        "B": "concatenate both lists",
        "C": "raise, the reducer rejects a list",
    }
    assert pending.expected_answer == "B"
    assert [option["body"] for option in posed_card(result)["options"]] == [
        "overwrite the old value",
        "concatenate both lists",
        "raise, the reducer rejects a list",
    ]


@pytest.mark.asyncio
async def test_choice_quiz_rejoins_bare_labels_sent_with_descriptions(path_id):
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Pick a colour",
        expected_answer="blue",
        options=[{"label": "A", "description": "red"}, {"label": "B", "description": "blue"}],
    )

    assert result.success is True
    pending = LearningStore().load(path_id).pending_question
    assert pending is not None
    assert pending.question_type == "choice"
    assert pending.choice_map == {"A": "red", "B": "blue"}
    assert pending.expected_answer == "B"


@pytest.mark.asyncio
async def test_choice_quiz_names_an_option_it_cannot_read(path_id):
    """A rejection has to say which entry was unusable, or the retry repeats it."""
    await _build_basic(path_id)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = status["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Pick one",
        expected_answer="A",
        question_type="choice",
        options=[{"note": "first"}, "B: second"],
    )

    assert result.success is False
    assert "must each be an option" in result.content
    assert "{'note': 'first'}" in result.content
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

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Pick a colour",
        expected_answer="blue",
        question_type="choice",
        options=["A: red", "B: blue"],
    )
    registered = tool_payload(result)
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)

    pending = status["next"]["pending_question"]
    assert pending == registered["pending_question"]
    # Posing the question and registering it are the same call: the turn ends
    # on a card derived from what was just persisted.
    card = posed_card(result)
    assert card is not None
    # The card is mastery's own shape on its own key — it no longer doubles as
    # an ask_user payload.
    assert "questions" not in card
    assert card["question_id"] == pending["question_id"]
    assert card["prompt"] == "Pick a colour"
    assert card["allow_free_text"] is True
    assert card["options"] == [
        {"label": "A", "body": "red"},
        {"label": "B", "body": "blue"},
    ]
    assert card["objective"]["id"] == kp_id
    assert card["attempt"] == 1
    # The answer key never travels to the learner.
    rendered = json.dumps(card, ensure_ascii=False)
    assert "expected_answer" not in rendered
    assert "expected_answer" not in registered
    assert "expected_answer" not in pending


@pytest.mark.asyncio
async def test_choice_grade_accepts_unique_persisted_body(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]
    quiz = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="Pick a colour",
                expected_answer="B",
                question_type="choice",
                options=["A: red", "B: blue"],
            )
        )
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
async def test_a_repeat_quiz_call_says_it_posed_nothing(path_id):
    """The second call in a round must not read like a fresh question.

    The engine holds one open question per path, so a repeat call re-presents
    the existing card. Reported with the same wording as a new question, a
    model that had already posed one this round could not tell that its extra
    call did nothing — and kept making it.
    """
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]

    posed = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        _session_id="session-1",
        _turn_id="turn-1",
        knowledge_point_id=kp_id,
        question="2+2?",
        expected_answer="4",
    )
    repeated = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        _session_id="session-1",
        _turn_id="turn-1",
        knowledge_point_id=kp_id,
        question="a different question",
        expected_answer="5",
    )

    assert "on the learner's answer card" in posed.content
    assert "No new question was posed" in repeated.content
    assert "do not call any further tools after mastery_quiz" in repeated.content
    # Both still end the turn: the card is in front of the learner either way.
    assert tool_payload(repeated)["status"] == "already_pending"


@pytest.mark.asyncio
async def test_quiz_strips_options_restated_in_the_question(path_id):
    """A stem that repeats its options would show every choice twice."""
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        _session_id="session-1",
        _turn_id="turn-1",
        knowledge_point_id=kp_id,
        question="Which one accumulates? A: plain list B: Annotated with a reducer",
        expected_answer="B",
        options=["A: plain list", "B: Annotated with a reducer"],
    )

    stem = tool_payload(result)["pending_question"]["prompt"]
    assert stem == "Which one accumulates?"
    # The options themselves are untouched; only the duplicate prose is gone.
    card = posed_card(result)
    assert "your question text also listed the options" in result.content
    assert card is not None


@pytest.mark.asyncio
async def test_duplicate_quiz_and_grade_are_idempotent(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]

    first_quiz = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                _session_id="session-1",
                _turn_id="turn-1",
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
            )
        )
    )
    retry_quiz = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                _session_id="session-1",
                _turn_id="turn-1",
                knowledge_point_id=kp_id,
                question="A model-authored replacement must not win",
                expected_answer="5",
            )
        )
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
    first = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="First?",
                expected_answer="yes",
            )
        )
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
    second = tool_payload(second_result)

    assert second_result.success is True
    assert second["status"] == "registered"
    assert second["question_id"] != first["question_id"]


@pytest.mark.asyncio
async def test_status_recovers_answered_interaction_without_exposing_answer_key(path_id):
    await _build_basic(path_id)
    initial = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    kp_id = initial["next"]["knowledge_point_id"]
    quiz = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
            )
        )
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
    quiz = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="Compute (2e^{iπ/3})³",
                expected_answer="A",
                options=["A: -8", "B: -6", "C: 8", "D: -2"],
            )
        )
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

    posed = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="What does NAND return for (1, 1)?",
        expected_answer="0",
        question_type="short",
        explanation="NAND is NOT AND, so two true inputs give false.",
        difficulty="medium",
    )
    quiz = tool_payload(posed)

    # The reference explanation is answer-adjacent: it must never ride along
    # on the card the learner is about to answer.
    rendered = json.dumps(posed_card(posed), ensure_ascii=False)
    assert "NOT AND" not in rendered
    assert "NOT AND" not in json.dumps(quiz["pending_question"], ensure_ascii=False)
    # Difficulty is shown, so it has to reach the card.
    assert posed_card(posed)["difficulty"] == "medium"

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

    quiz = tool_payload(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question="2+2?",
                expected_answer="4",
                question_type="short",
                difficulty="extremely tricky",
            )
        )
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


# ── revising one module's waypoints ─────────────────────────────────────────


async def _build_with_objective(path_id):
    build = MasteryBuildTool()
    return await build.execute(
        _mastery_path_id=path_id,
        path_name="命题逻辑",
        modules=[
            {
                "name": "布尔基础",
                "objective": "读懂一个真值表并判断两个命题是否等价",
                "knowledge_points": [
                    {"name": "真值表", "type": "memory"},
                    {"name": "XOR 的意义", "type": "concept"},
                ],
            }
        ],
    )


@pytest.mark.asyncio
async def test_build_keeps_the_module_objective(path_id):
    """The objective is the contract a revision is later measured against, so
    it has to survive the build that wrote it."""
    payload = json.loads((await _build_with_objective(path_id)).content)
    module = payload["map"]["modules"][0]
    assert module["objective"] == "读懂一个真值表并判断两个命题是否等价"


@pytest.mark.asyncio
async def test_revise_rewrites_a_waypoint_and_resets_only_its_progress(path_id):
    from deeptutor.tools.mastery_tool import MasteryReviseTool

    built = json.loads((await _build_with_objective(path_id)).content)
    module = built["map"]["modules"][0]
    target = module["knowledge_points"][1]

    revised = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        module_id=module["id"],
        rewrite=[
            {
                "knowledge_point_id": target["id"],
                "name": "用 XOR 判断两个命题何时等价",
                "type": "procedure",
            }
        ],
    )
    payload = json.loads(revised.content)
    assert payload["status"] == "revised"
    # The promise the revision had to stay inside is echoed back with it.
    assert payload["module_objective"] == "读懂一个真值表并判断两个命题是否等价"
    names = [kp["name"] for kp in payload["knowledge_points"]]
    assert names == ["真值表", "用 XOR 判断两个命题何时等价"]
    # A restated waypoint is a different waypoint: fresh id, progress reset,
    # and the tutor is told so it can say so.
    assert payload["knowledge_points"][1]["id"] != target["id"]
    assert payload["knowledge_points"][1]["type"] == "procedure"
    assert payload["progress_reset"] == ["XOR 的意义"]
    # The untouched waypoint keeps its identity, and so its evidence.
    assert payload["knowledge_points"][0]["id"] == module["knowledge_points"][0]["id"]


@pytest.mark.asyncio
async def test_revise_adds_and_removes_within_one_module(path_id):
    from deeptutor.tools.mastery_tool import MasteryReviseTool

    built = json.loads((await _build_with_objective(path_id)).content)
    module = built["map"]["modules"][0]

    revised = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        module_id=module["id"],
        remove=[module["knowledge_points"][0]["id"]],
        add=[{"name": "德摩根定律", "type": "memory"}],
    )
    payload = json.loads(revised.content)
    assert [kp["name"] for kp in payload["knowledge_points"]] == ["XOR 的意义", "德摩根定律"]
    assert payload["progress_reset"] == []


@pytest.mark.asyncio
async def test_revise_refuses_to_erase_a_mastered_waypoint(path_id):
    """Proven work is the one thing a passing dislike must not delete."""
    from deeptutor.tools.mastery_tool import MasteryReviseTool

    built = json.loads((await _build_with_objective(path_id)).content)
    module = built["map"]["modules"][0]
    concept = module["knowledge_points"][1]

    assessed = await MasteryAssessTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=concept["id"],
        passed=True,
        explanation="学习者说清楚了 XOR 与等价的关系。",
    )
    assert json.loads(assessed.content)["mastered"] is True

    refused = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        module_id=module["id"],
        rewrite=[{"knowledge_point_id": concept["id"], "name": "换一个说法"}],
    )
    assert refused.success is False
    assert "already mastered" in refused.content
    # …and nothing moved: the waypoint keeps both its id and its pass.
    status = tool_payload(await MasteryStatusTool().execute(_mastery_path_id=path_id))
    survivor = status["map"]["modules"][0]["knowledge_points"][1]
    assert survivor["id"] == concept["id"]
    assert survivor["status"] == "mastered"


@pytest.mark.asyncio
async def test_revise_rejects_an_unknown_module_by_listing_the_real_ones(path_id):
    from deeptutor.tools.mastery_tool import MasteryReviseTool

    await _build_with_objective(path_id)
    result = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        module_id="not_a_module",
        remove=["whatever"],
    )
    assert result.success is False
    assert "布尔基础" in result.content


# ── intake: who is learning this goal ───────────────────────────────────────


@pytest.mark.asyncio
async def test_status_asks_for_intake_until_the_learner_has_been_asked(path_id):
    """A goal nobody has been asked about must say so, not quietly design a
    route for an average learner who does not exist."""
    from deeptutor.tools.mastery_tool import MasteryProfileTool

    before = tool_payload(await MasteryStatusTool().execute(_mastery_path_id=path_id))
    assert before["intake_needed"] is True
    assert before["learner_profile"] is None
    assert "how much time" in before["intake_instruction"]

    await MasteryProfileTool().execute(
        _mastery_path_id=path_id,
        prior_knowledge="矩阵乘法会，特征值忘了",
        time_budget="两周，每天晚上一小时",
    )
    after = tool_payload(await MasteryStatusTool().execute(_mastery_path_id=path_id))
    assert after["intake_needed"] is False
    assert after["learner_profile"]["time_budget"] == "两周，每天晚上一小时"


@pytest.mark.asyncio
async def test_the_profile_travels_with_every_status_call_not_just_the_first(path_id):
    """The failure intake exists to prevent is being forgotten by the thirtieth
    knowledge point — so the profile rides on the built path's status too."""
    from deeptutor.tools.mastery_tool import MasteryProfileTool

    await MasteryProfileTool().execute(
        _mastery_path_id=path_id, preferences="中文讲解，术语保留英文"
    )
    await _build_basic(path_id)

    status = tool_payload(await MasteryStatusTool().execute(_mastery_path_id=path_id))
    assert status["status"] == "active"
    assert status["learner_profile"]["preferences"] == "中文讲解，术语保留英文"
    assert status["intake_needed"] is False


@pytest.mark.asyncio
async def test_a_correction_merges_instead_of_wiping_the_other_answers(path_id):
    from deeptutor.tools.mastery_tool import MasteryProfileTool

    profile = MasteryProfileTool()
    await profile.execute(
        _mastery_path_id=path_id,
        prior_knowledge="学过一学期线性代数",
        target_level="能看懂论文里的推导",
        time_budget="一个月",
    )
    # Months later: only the time changed.
    corrected = json.loads(
        (await profile.execute(_mastery_path_id=path_id, time_budget="改成两周")).content
    )
    assert corrected["updated_fields"] == ["time_budget"]
    assert corrected["learner_profile"] == {
        "prior_knowledge": "学过一学期线性代数",
        "target_level": "能看懂论文里的推导",
        "time_budget": "改成两周",
        "preferences": "",
        "notes": "",
    }


@pytest.mark.asyncio
async def test_resending_an_unchanged_answer_reports_no_new_information(path_id):
    """Re-sending what is already on file must not read back as the learner
    having said something new."""
    from deeptutor.tools.mastery_tool import MasteryProfileTool

    profile = MasteryProfileTool()
    await profile.execute(_mastery_path_id=path_id, target_level="能自己实现一遍")
    again = json.loads(
        (await profile.execute(_mastery_path_id=path_id, target_level="能自己实现一遍")).content
    )
    assert again["updated_fields"] == []


@pytest.mark.asyncio
async def test_an_empty_profile_call_is_refused_with_the_fields_it_wanted(path_id):
    from deeptutor.tools.mastery_tool import MasteryProfileTool

    result = await MasteryProfileTool().execute(_mastery_path_id=path_id)
    assert result.success is False
    assert "time_budget" in result.content
