"""Group answers stay independently identified across the runtime boundary."""

from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.turn_request import MasteryCardAnswer
from deeptutor.services.session.turns.learning_adapter import LearningTurnAdapter


def test_card_contract_keeps_independent_group_answers():
    card = MasteryCardAnswer(
        question_id="group", text="1: A; 2: B", answers={"first": "A", "second": "B"}
    )
    assert card.model_dump()["answers"] == {"first": "A", "second": "B"}
    assert MasteryCardAnswer(question_id="single", text="A").answers is None


@pytest.mark.parametrize("answers", [{}, {"first": "", "second": "B"}, {"first": 1, "second": "B"}])
def test_group_transport_rejects_empty_or_untyped_values(answers):
    with pytest.raises(ValidationError):
        MasteryCardAnswer(question_id="group", text="display", answers=answers)


def test_group_transport_accepts_one_actual_reply():
    card = MasteryCardAnswer(question_id="group", text="second only", answers={"second": "B"})
    assert card.answers == {"second": "B"}


def test_partial_group_seed_does_not_claim_unanswered_questions_were_graded():
    context = UnifiedContext(
        metadata={
            "mastery_mode": True,
            "mastery_card_grade": {
                "result": {
                    "question_type": "group",
                    "complete": False,
                    "remaining_question_ids": ["first"],
                    "results": [{"question_id": "second", "is_correct": True}],
                },
            },
        }
    )
    seed = MasteryLoopCapability().pre_loop_seed(context)
    assert "first" in seed and "unanswered" in seed
    assert "second: correct" in seed
    assert "The question group was already graded" not in seed


@pytest.mark.asyncio
async def test_runtime_forwards_group_map_not_display_summary(monkeypatch):
    calls = []
    published = []

    async def grade(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            content="{}",
            metadata={
                "mastery_grade": {
                    "question_id": "group",
                    "result": {"results": []},
                    "is_correct": False,
                }
            },
        )

    async def publish(execution, event):
        published.append(event)
        return {}

    monkeypatch.setattr("deeptutor.capabilities.mastery.tools.MasteryGradeTool.execute", grade)
    adapter = LearningTurnAdapter()
    adapter._publish_live_event = publish
    result = await adapter._grade_submitted_card_answer(
        SimpleNamespace(session_id="session", turn_id="turn"),
        path_id="path",
        answer={
            "question_id": "group",
            "text": "display only",
            "answers": {"first": "A", "second": "B"},
        },
    )
    assert result["question_id"] == "group"
    assert calls[0]["answers"] == {"first": "A", "second": "B"}
    assert calls[0].get("answer", "") != "display only"
    assert len(published) == 2


@pytest.mark.asyncio
async def test_commit_keeps_group_map_in_the_native_answer_record(monkeypatch):
    calls = []

    def record(self, path_id, answer, **kwargs):
        calls.append((path_id, answer, kwargs))

    monkeypatch.setattr("deeptutor.learning.service.LearningService.record_question_answer", record)
    await LearningTurnAdapter()._commit_mastery_card_answer(
        path_id="path",
        session_id="session",
        turn_id="turn",
        question_id="group",
        answer="display only",
        answers={"first": "A", "second": "B"},
    )
    assert calls[0][2]["answers"] == {"first": "A", "second": "B"}


@pytest.mark.parametrize(
    "reply",
    [
        "Answer these two practice questions; I will grade both answers.\n1. Which change increases the rate?\n2. Explain why it increases?",
        "Válaszolj erre a két gyakorló kérdésre.\n1. Melyik változás növeli a sebességet?\n2. Miért növeli?",
    ],
)
def test_numbered_question_discussion_can_finish_without_tools(reply):
    instruction = MasteryLoopCapability().finish_instruction(
        UnifiedContext(metadata={"mastery_mode": True}), reply
    )
    assert instruction is None


@pytest.mark.parametrize(
    "reply",
    [
        "Two useful ideas:\n1. Motion is random.\n2. The gradient changes net motion.",
        "Think about two examples:\n1. Where does it move?\n2. Which force matters?",
        "A korábbi kérdésről beszélünk, nem új feladatról.\n1. Miért fontos az irány?\n2. Mire utal a különbség?",
    ],
)
def test_connected_teaching_is_not_a_forced_assessment(reply):
    assert (
        MasteryLoopCapability().finish_instruction(
            UnifiedContext(metadata={"mastery_mode": True}), reply
        )
        is None
    )


def test_group_seed_reads_real_nested_results_and_keeps_unknown_neutral():
    context = UnifiedContext(
        metadata={
            "mastery_mode": True,
            "mastery_card_grade": {
                "question_id": "group",
                "is_correct": None,
                "result": {
                    "question_type": "group",
                    "results": [
                        {
                            "question_id": "first",
                            "knowledge_point_id": "point-a",
                            "is_correct": True,
                        },
                        {
                            "question_id": "second",
                            "knowledge_point_id": "point-b",
                            "is_correct": None,
                        },
                    ],
                },
            },
        }
    )
    seed = MasteryLoopCapability().pre_loop_seed(context)
    assert "first: correct" in seed
    assert "second: ungraded" in seed
    assert "second: incorrect" not in seed


@pytest.mark.asyncio
@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("failure", ["rejected", "exception", "missing_receipt"])
async def test_rejected_group_answer_emits_card_recovery_event(monkeypatch, grouped, failure):
    published = []

    async def grade(self, **kwargs):
        if failure == "exception":
            raise RuntimeError("assessment provider unavailable")
        return SimpleNamespace(
            success=failure == "missing_receipt", content="invalid answers", metadata={}
        )

    async def publish(execution, event):
        published.append(event)
        return {}

    monkeypatch.setattr("deeptutor.capabilities.mastery.tools.MasteryGradeTool.execute", grade)
    adapter = LearningTurnAdapter()
    adapter._publish_live_event = publish
    result = await adapter._grade_submitted_card_answer(
        SimpleNamespace(session_id="session", turn_id="turn"),
        path_id="path",
        answer={
            "question_id": "group",
            "text": "display",
            **({"answers": {"first": "A", "second": "B"}} if grouped else {}),
        },
    )
    assert result is None
    assert len(published) == 2
    metadata = published[0].metadata
    assert metadata["tool_metadata"]["mastery_answer_rejected"]["question_id"] == "group"
    assert "turn" in metadata["call_id"]
    assert "mastery_grade" not in metadata["tool_metadata"]


@pytest.fixture
def replay_runtime(tmp_path, monkeypatch):
    """Keep a real terminal attempt and an unrelated open question in SQLite."""
    from deeptutor.learning.models import (
        InteractionStatus,
        LearningProgress,
        MasteryInteraction,
        PendingQuestion,
    )
    from deeptutor.learning.service import LearningService
    from deeptutor.learning.storage import LearningStore

    store = LearningStore(root=tmp_path)
    store.save(LearningProgress(book_id="path"))
    question = PendingQuestion(
        question_id="old",
        knowledge_point_id="kp",
        prompt="Pick B",
        question_type="choice",
        expected_answer="B",
        options=["A: first option", "B: second option", "C: third option", "D: fourth option"],
    )
    old = MasteryInteraction(
        interaction_id="old",
        path_id="path",
        question=question,
        status=InteractionStatus.GRADED,
        session_id="study",
        turn_id="original",
        user_answer="D",
        result={
            "learner_answer": "D",
            "correct_label": "B",
            "is_correct": False,
            "final": True,
            "result": "incorrect",
        },
    )
    new = MasteryInteraction(
        interaction_id="new",
        path_id="path",
        question=question.model_copy(update={"question_id": "new"}),
        status=InteractionStatus.AWAITING_INPUT,
    )
    store.mutate("path", lambda tx: (tx.put_interaction(old), tx.put_interaction(new)))
    service = LearningService(store=store)
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda: store)

    async def grade(self, **kwargs):
        _, row, replayed = service.grade_interaction(
            "path",
            question_id=kwargs["question_id"],
            answer=kwargs.get("answer", ""),
            session_id="review",
            turn_id="reply",
        )
        return SimpleNamespace(
            success=True,
            content="saved receipt",
            metadata={
                "mastery_grade": {
                    "question_id": row.interaction_id,
                    "replayed": replayed,
                    "result": row.result,
                }
            },
        )

    monkeypatch.setattr("deeptutor.capabilities.mastery.tools.MasteryGradeTool.execute", grade)
    published = []

    async def publish(execution, event):
        published.append(event)
        return {}

    adapter = LearningTurnAdapter()
    adapter._publish_live_event = publish
    return store, adapter, published


@pytest.mark.asyncio
@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize(
    "text,stale",
    [
        ("B", True),
        ("D", False),
        (" d ", False),
        ("fourth option", False),
        ("Why is D wrong?", True),
    ],
)
async def test_old_card_replay_checks_actual_submission_without_changing_history(
    replay_runtime,
    mapped,
    text,
    stale,
):
    store, adapter, published = replay_runtime
    before = store.get_interaction("path", "old").model_dump()
    active_before = store.get_active_interaction("path").model_dump()
    revision = store.load("path").version
    result = await adapter._grade_submitted_card_answer(
        SimpleNamespace(session_id="review", turn_id="reply"),
        path_id="path",
        answer={
            "question_id": "old",
            "text": text,
            **({"answers": {"old": text}} if mapped else {}),
        },
    )
    event = published[0].metadata["tool_metadata"]
    if stale:
        assert result == {"question_id": "old", "reason": "stale_card"}
        assert event["mastery_answer_rejected"]["reason"] == "stale_card"
        assert "mastery_grade" not in event
        assert "not graded" in published[0].content
    else:
        assert result["replayed"] is True
        assert event["mastery_grade"]["result"]["learner_answer"] == "D"
    assert store.get_interaction("path", "old").model_dump() == before
    assert store.get_active_interaction("path").model_dump() == active_before
    assert store.load("path").version == revision


@pytest.mark.asyncio
async def test_only_final_single_replays_need_comparison():
    adapter = LearningTurnAdapter()
    for receipt in [
        {"replayed": False, "result": {"learner_answer": "D"}},
        {"replayed": True, "result": {"learner_answer": "D", "final": False}},
        {"replayed": True, "result": {"results": [], "question_type": "group"}},
    ]:
        assert not await adapter._is_mismatched_card_replay(
            path_id="unused",
            submission={"question_id": "q", "text": "B"},
            receipt=receipt,
        )


def test_stale_rejection_seed_takes_priority_over_historical_grade():
    capability = MasteryLoopCapability()
    context = UnifiedContext(
        metadata={
            "mastery_mode": True,
            "mastery_card_rejection": {"question_id": "old", "reason": "stale_card"},
            "mastery_card_grade": {"result": {"is_correct": False, "learner_answer": "D"}},
        }
    )
    seed = capability.pre_loop_seed(context)
    assert "NOT graded" in seed
    assert "another pending question" in seed
    assert "do not call mastery_grade" in seed.lower()
    assert 'they answered "D"' not in seed
    assert capability._stale_card_seed(UnifiedContext()) == ""
