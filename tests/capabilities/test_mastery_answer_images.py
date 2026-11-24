"""Photos of a handwritten solution are graded as the learner's answer, never dropped."""

import base64
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from deeptutor.core.turn_request import MasteryCardAnswer, TurnRequest
from deeptutor.learning.answer_images import answer_image_refs
from deeptutor.learning.models import InteractionStatus
from deeptutor.learning.service import MasteryInteractionError
from deeptutor.services.session.turns.learning_adapter import LearningTurnAdapter
from deeptutor.services.storage import LocalDiskAttachmentStore
from tests.capabilities.test_mastery_question_groups import leaf

pytest_plugins = ["tests.capabilities.test_mastery_question_groups"]

PHOTO = b"\x89PNG synthetic handwritten working: 0.3*100 + 0.7*40 = 58"
OTHER_PHOTO = b"\x89PNG synthetic handwritten working: 0.5*100 + 0.5*40 = 70"
VISION = SimpleNamespace(binding="openai", model="vision-model")


def _attachment(data: bytes, attachment_id: str = "photo-1") -> dict:
    return {
        "type": "image",
        "id": attachment_id,
        "filename": "working.png",
        "mime_type": "image/png",
        "base64": base64.b64encode(data).decode(),
    }


@pytest.fixture
def attachments(tmp_path, monkeypatch):
    """A real attachment store holding uploads the way the turn runtime does."""
    store = LocalDiskAttachmentStore(tmp_path / "attachments")
    monkeypatch.setattr("deeptutor.services.storage.get_attachment_store", lambda: store)
    monkeypatch.setattr(
        "deeptutor.services.llm.capabilities.supports_vision",
        lambda binding, model=None: model == "vision-model",
    )

    async def upload(data: bytes, attachment_id: str = "photo-1"):
        await store.put(
            session_id="study",
            attachment_id=attachment_id,
            filename="working.png",
            data=data,
        )
        return answer_image_refs(
            [attachment_id], [_attachment(data, attachment_id)], session_id="study"
        )

    return SimpleNamespace(store=store, upload=upload)


def _answer_with_photo(service, refs, text="58"):
    service.register_question("p", leaf(expected="58"))
    service.record_question_answer(
        "p", text, interaction_id="q1", session_id="study", turn_id="t", answer_images=refs
    )


def _judge(monkeypatch, calls, *, result="correct", confidence=0.95):
    from deeptutor.learning import semantic_assessment as semantic

    async def request(config, instruction, payload, sources=None, native_images=None):
        calls.append({"instruction": instruction, "payload": payload, "images": native_images})
        return {
            "verdicts": [
                {
                    "question_id": item["question_id"],
                    "result": result,
                    "confidence": confidence,
                    "feedback": "The working in the photo reaches 58.",
                }
                for item in payload
            ]
        }

    monkeypatch.setattr(semantic, "_request", request)


def test_card_contract_accepts_photo_only_single_answers():
    card = MasteryCardAnswer(question_id="q", attachment_ids=["photo-1"])
    assert card.text == "" and card.attachment_ids == ["photo-1"]
    with pytest.raises(ValidationError):
        MasteryCardAnswer(question_id="q", text="")
    with pytest.raises(ValidationError):
        MasteryCardAnswer(question_id="q", attachment_ids=["a", "a"])
    with pytest.raises(ValidationError):
        MasteryCardAnswer(question_id="q", attachment_ids=["a", "b", "c", "d", "e"])
    with pytest.raises(ValidationError):
        MasteryCardAnswer(question_id="g", text="x", answers={"q": "x"}, attachment_ids=["a"])


def test_turn_request_requires_named_photos_to_be_uploaded_images():
    answer = {"question_id": "q", "attachment_ids": ["photo-1"]}
    TurnRequest(content="photo", mastery_answer=answer, attachments=[_attachment(PHOTO)])
    with pytest.raises(ValidationError):
        TurnRequest(content="photo", mastery_answer=answer, attachments=[])
    with pytest.raises(ValidationError):
        TurnRequest(
            content="photo",
            mastery_answer=answer,
            attachments=[{**_attachment(PHOTO), "type": "file"}],
        )


@pytest.mark.asyncio
async def test_photo_reaches_the_judge_labelled_as_the_learner_answer(
    service, attachments, monkeypatch
):
    refs = await attachments.upload(PHOTO)
    # The typed result equals the key; the photo is still what gets judged.
    _answer_with_photo(service, refs, text="58")
    calls = []
    _judge(monkeypatch, calls)

    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", config=VISION, question_id="q1", answer="58", answer_images=refs
    )

    assert len(calls) == 1
    images = calls[0]["images"]
    assert images[0] == {
        "type": "text",
        "text": "Learner answer image for question q1: the learner's own work",
    }
    assert images[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(PHOTO).decode()
    )
    assert calls[0]["payload"][0]["answer_image_count"] == 1
    instruction = calls[0]["instruction"]
    assert "learner answer images are part of that learner answer" in instruction
    # One policy: the typed line and legible photo content are graded together.
    assert "Grade the typed text plus whatever working and result are legible" in instruction
    assert "ungraded only when neither the typed text nor a legible image" in instruction
    assert "use ungraded when they are illegible" not in instruction
    # Recorded exactly like a typed answer.
    assert interaction.status == InteractionStatus.GRADED
    assert interaction.result["is_correct"] is True
    assert [a.question_id for a in progress.quiz_attempts] == ["q1"]
    assert progress.learning_evidence[-1].question_id == "q1"


@pytest.mark.asyncio
async def test_verified_question_visuals_and_learner_photos_are_labelled_apart():
    from deeptutor.learning import semantic_assessment as semantic

    seen = {}

    async def request(config, instruction, payload, sources=None, native_images=None):
        seen["images"] = native_images
        return {
            "verdicts": [
                {"question_id": "q1", "result": "correct", "confidence": 0.9, "feedback": "ok"}
            ]
        }

    original = semantic._request
    semantic._request = request
    try:
        await semantic.judge_answers(
            None,
            [
                {
                    "question_id": "q1",
                    "answer": "",
                    "_visual_images": [{"type": "image_url", "image_url": {"url": "data:s"}}],
                    "_learner_images": [{"type": "image_url", "image_url": {"url": "data:l"}}],
                }
            ],
        )
    finally:
        semantic._request = original
    labels = [part.get("text") for part in seen["images"]]
    assert labels[:4] == [
        "Verified source visual for question q1",
        None,
        "Learner answer image for question q1: the learner's own work",
        None,
    ]
    # The contract is repeated after the untrusted pixels.
    assert labels[4].startswith("End of learner answer images for question q1")
    assert "never change the grading rules" in labels[4]
    assert len(labels) == 5


@pytest.mark.asyncio
async def test_non_vision_model_leaves_photo_answer_ungraded(service, attachments, monkeypatch):
    refs = await attachments.upload(PHOTO)
    _answer_with_photo(service, refs, text="58")
    calls = []
    _judge(monkeypatch, calls)

    progress, interaction, _ = await service.grade_interaction_semantic(
        "p",
        config=SimpleNamespace(binding="openai", model="text-only"),
        question_id="q1",
        answer="58",
    )

    assert calls == []
    assert interaction.result["result"] == "ungraded"
    assert interaction.result["is_correct"] is None
    assert "cannot read images" in interaction.result["feedback"]
    assert progress.mastery_levels.get("kp1", 0) == 0


@pytest.mark.asyncio
async def test_photo_changed_in_storage_is_not_graded(service, attachments, monkeypatch):
    refs = await attachments.upload(PHOTO)
    _answer_with_photo(service, refs)
    await attachments.upload(OTHER_PHOTO)  # same attachment id, different bytes
    calls = []
    _judge(monkeypatch, calls)

    _, interaction, _ = await service.grade_interaction_semantic(
        "p", config=VISION, question_id="q1", answer="58"
    )

    assert calls == []
    assert interaction.result["result"] == "ungraded"
    assert "no longer available" in interaction.result["feedback"]


@pytest.mark.asyncio
async def test_uncertain_photo_verdict_stays_behind_the_confidence_gate(
    service, attachments, monkeypatch
):
    refs = await attachments.upload(PHOTO)
    _answer_with_photo(service, refs)
    _judge(monkeypatch, [], result="correct", confidence=0.7)

    _, interaction, _ = await service.grade_interaction_semantic(
        "p", config=VISION, question_id="q1", answer="58"
    )

    assert interaction.result["result"] == "ungraded"
    assert interaction.result["final"] is False


@pytest.mark.asyncio
async def test_photos_lost_by_the_commit_are_refused_not_graded_as_text(
    service, attachments, monkeypatch
):
    refs = await attachments.upload(PHOTO)
    service.register_question("p", leaf(expected="58"))
    service.record_question_answer("p", "58", interaction_id="q1")  # no photos recorded
    calls = []
    _judge(monkeypatch, calls)

    with pytest.raises(MasteryInteractionError, match="photos were not recorded"):
        await service.grade_interaction_semantic(
            "p", config=VISION, question_id="q1", answer="58", answer_images=refs
        )
    assert calls == []
    assert not service.store.load("p").quiz_attempts


@pytest.mark.asyncio
async def test_text_only_answers_are_judged_without_learner_images(service, monkeypatch):
    calls = []
    _judge(monkeypatch, calls)
    service.register_question("p", leaf(expected="58"))

    _, interaction, _ = await service.grade_interaction_semantic(
        "p", config=VISION, question_id="q1", answer="fifty-eight"
    )

    assert interaction.result["is_correct"] is True
    assert calls[0]["images"] == []
    assert "answer_image_count" not in calls[0]["payload"][0]
    assert "learner answer images" not in calls[0]["instruction"]


@pytest.mark.asyncio
async def test_card_replay_with_different_photo_is_a_stale_card(service, attachments, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    refs = await attachments.upload(PHOTO)
    calls = []
    _judge(monkeypatch, calls)
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda: service.store)
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config", lambda: VISION, raising=False
    )

    async def no_bank_sync(**kwargs):
        return None

    monkeypatch.setattr(tools, "_sync_mastery_attempt_to_question_bank", no_bank_sync)
    published = []

    async def publish(execution, event):
        published.append(event)
        return {}

    adapter = LearningTurnAdapter()
    adapter._publish_live_event = publish
    service.register_question("p", leaf(expected="58"))
    execution = SimpleNamespace(session_id="study", turn_id="t1")
    submission = {"question_id": "q1", "text": "58", "attachment_ids": ["photo-1"]}
    first = adapter._card_answer_images("study", submission, [_attachment(PHOTO)])
    assert first == refs
    monkeypatch.setattr("deeptutor.learning.service.LearningService", lambda: service)
    await adapter._commit_mastery_card_answer(
        path_id="p",
        session_id="study",
        turn_id="t1",
        question_id="q1",
        answer="58",
        answer_images=first,
    )
    graded = await adapter._grade_submitted_card_answer(
        execution, path_id="p", answer=submission, answer_images=first
    )
    assert graded["is_correct"] is True
    assert len(calls) == 1 and calls[0]["images"][0]["text"].startswith("Learner answer image")

    # Same card, same typed text, a different photo: not the graded submission.
    published.clear()
    replay = SimpleNamespace(session_id="study", turn_id="t2")
    second = adapter._card_answer_images("study", submission, [_attachment(OTHER_PHOTO)])
    before = service.store.get_interaction("p", "q1").model_dump()
    result = await adapter._grade_submitted_card_answer(
        replay, path_id="p", answer=submission, answer_images=second
    )
    assert result == {"question_id": "q1", "reason": "stale_card"}
    rejected = published[0].metadata["tool_metadata"]["mastery_answer_rejected"]
    assert rejected["reason"] == "stale_card"
    assert service.store.get_interaction("p", "q1").model_dump() == before
    assert len(calls) == 1
    assert len(service.store.load("p").quiz_attempts) == 1

    # The same typed text without the photo is a different submission too.
    assert await adapter._is_mismatched_card_replay(
        path_id="p",
        submission={"question_id": "q1", "text": "58"},
        receipt={"replayed": True, "result": {"learner_answer": "58"}},
    )


def test_existing_database_gains_the_answer_images_column(tmp_path):
    import sqlite3

    from deeptutor.learning.models import LearningProgress, MasteryInteraction
    from deeptutor.learning.storage import LearningStore, _initialized_db_paths

    store = LearningStore(root=tmp_path)
    store.save(LearningProgress(book_id="p"))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("ALTER TABLE mastery_interactions DROP COLUMN answer_images_json")
    _initialized_db_paths.discard(store.db_path.resolve())

    upgraded = LearningStore(root=tmp_path)
    ref = {
        "session_id": "s",
        "attachment_id": "a",
        "filename": "f.png",
        "mime_type": "image/png",
        "sha256": "0" * 64,
    }
    row = MasteryInteraction(interaction_id="q1", path_id="p", question=leaf(), answer_images=[ref])
    upgraded.mutate("p", lambda tx: tx.put_interaction(row))
    assert upgraded.get_interaction("p", "q1").answer_images == [ref]


def test_turn_request_rejects_a_photo_with_a_non_image_mime_type():
    with pytest.raises(ValidationError):
        TurnRequest(
            content="photo",
            mastery_answer={"question_id": "q", "attachment_ids": ["photo-1"]},
            attachments=[{**_attachment(PHOTO), "mime_type": "text/html"}],
        )


@pytest.mark.asyncio
async def test_correction_regrades_the_photos_not_the_typed_text(service, attachments, monkeypatch):
    refs = await attachments.upload(PHOTO)
    _answer_with_photo(service, refs, text="")
    calls = []
    _judge(monkeypatch, calls)
    await service.grade_interaction_semantic("p", config=VISION, question_id="q1", answer="")
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config", lambda: VISION, raising=False
    )

    _, receipt = await service.repair_question_semantic(
        "p", "q1", config=VISION, action="correct", expected_answer="58.00", reason="Key format."
    )

    assert len(calls) == 2
    assert calls[1]["images"][0]["text"].startswith("Learner answer image for question q1")
    assert receipt["is_correct"] is True


@pytest.mark.asyncio
async def test_chat_message_after_an_ungraded_photo_does_not_replace_the_photos(
    service, attachments, monkeypatch
):
    from deeptutor.capabilities.mastery import tools

    refs = await attachments.upload(PHOTO)
    _answer_with_photo(service, refs, text="")
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config",
        lambda: SimpleNamespace(binding="openai", model="text-only"),
        raising=False,
    )

    async def no_bank_sync(**kwargs):
        return None

    monkeypatch.setattr(tools, "_sync_mastery_attempt_to_question_bank", no_bank_sync)
    for message in ("Photo of my solution", "Photo of my solution"):
        await tools.MasteryGradeTool().execute(
            _mastery_path_id="p", question_id="q1", _learner_message=message
        )

    interaction = service.store.get_interaction("p", "q1")
    assert interaction.answer_images == refs
    assert interaction.user_answer == ""
    assert interaction.result["result"] == "ungraded"


@pytest.mark.asyncio
async def test_photos_can_be_resubmitted_after_grading_failed_without_a_verdict(
    service, attachments, monkeypatch
):
    from deeptutor.learning import semantic_assessment as semantic

    refs = await attachments.upload(PHOTO)
    _answer_with_photo(service, refs, text="")

    async def unavailable(*args, **kwargs):
        raise semantic.AssessmentUnavailable("Assessment images exceed the bounded request budget")

    monkeypatch.setattr(semantic, "_request", unavailable)
    with pytest.raises(MasteryInteractionError):
        await service.grade_interaction_semantic(
            "p", config=VISION, question_id="q1", answer="", answer_images=refs
        )

    smaller = await attachments.upload(OTHER_PHOTO, "photo-2")
    service.record_question_answer("p", "", interaction_id="q1", answer_images=smaller)
    calls = []
    _judge(monkeypatch, calls)
    _, interaction, _ = await service.grade_interaction_semantic(
        "p", config=VISION, question_id="q1", answer="", answer_images=smaller
    )
    assert interaction.answer_images == smaller
    assert interaction.result["is_correct"] is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_photos_that_overflow_the_shared_image_budget_reopen_the_card(
    service, attachments, monkeypatch
):
    from deeptutor.learning import semantic_assessment as semantic

    refs = []
    for index in range(4):
        refs += await attachments.upload(PHOTO + bytes([index]), f"photo-{index}")
    question = leaf(expected="58")
    # Three source pages ground the question and travel to the judge as images.
    question.source_evidence = {
        "sources": [{"ref": {"kb_ref": "kb", "page_index": page}} for page in range(3)],
        "assessment_contract": {"fingerprint": "bound"},
    }
    monkeypatch.setattr(semantic, "validate_question", lambda *args: None)
    service.register_question("p", question)
    service.record_question_answer(
        "p", "58", interaction_id="q1", session_id="study", turn_id="t", answer_images=refs
    )
    calls = []
    _judge(monkeypatch, calls)

    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", config=VISION, question_id="q1", answer="58", answer_images=refs
    )

    assert calls == []
    assert interaction.result["result"] == "ungraded"
    assert interaction.result["final"] is False
    assert "already sends 3 source images" in interaction.result["feedback"]
    assert "at most 3 photos" in interaction.result["feedback"]
    assert progress.mastery_levels.get("kp1", 0) == 0

    # Resubmitting three photos fits beside the three pages and is graded.
    service.record_question_answer(
        "p", "58", interaction_id="q1", session_id="study", turn_id="t2", answer_images=refs[:3]
    )
    _, interaction, _ = await service.grade_interaction_semantic(
        "p", config=VISION, question_id="q1", answer="58", answer_images=refs[:3]
    )
    assert len(calls) == 1
    assert interaction.result["is_correct"] is True


def test_learner_image_overflow_counts_bytes_beside_verified_visuals(monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    monkeypatch.setattr(semantic, "MAX_REQUEST_IMAGE_CHARS", 10)
    image = {"type": "image_url", "image_url": {"url": "data:123456"}}
    item = {"question_id": "q", "_visual_images": [image], "_learner_images": [image]}
    assert "too large" in semantic.learner_image_overflow(item)
    assert semantic.learner_image_overflow({**item, "_learner_images": []}) == ""


def test_photos_are_never_committed_beside_a_choice_pick(service):
    from deeptutor.learning.models import PendingQuestion

    service.register_question(
        "p",
        PendingQuestion(
            question_id="c1",
            knowledge_point_id="kp1",
            module_id="m",
            prompt="Pick one.",
            question_type="choice",
            options=["A. one", "B. two"],
            expected_answer="A",
        ),
    )
    refs = [
        {
            "session_id": "s",
            "attachment_id": "a",
            "filename": "f",
            "mime_type": "image/png",
            "sha256": "d",
        }
    ]

    with pytest.raises(MasteryInteractionError, match="single free-text question"):
        service.record_question_answer("p", "A", interaction_id="c1", answer_images=refs)
    interaction = service.store.get_interaction("p", "c1")
    assert interaction.status != InteractionStatus.ANSWERED
    assert interaction.answer_images == []


def test_unreadable_or_oversized_photos_are_refused_before_commit(monkeypatch):
    from deeptutor.services.config import runtime_settings

    unreadable = {**_attachment(PHOTO), "base64": "@@@"}
    with pytest.raises(ValueError, match="could not be read"):
        answer_image_refs(["photo-1"], [unreadable], session_id="s")

    limits = runtime_settings.get_chat_attachment_limits()
    monkeypatch.setattr(
        runtime_settings,
        "get_chat_attachment_limits",
        lambda: limits.__class__(**{**limits.__dict__, "max_file_bytes": len(PHOTO) - 1}),
    )
    with pytest.raises(ValueError, match="larger than the configured attachment limit"):
        answer_image_refs(["photo-1"], [_attachment(PHOTO)], session_id="s")


@pytest.mark.asyncio
async def test_start_turn_describes_card_photos_once_and_rejects_bad_ones_without_a_turn(
    monkeypatch, tmp_path
):
    import asyncio

    from deeptutor.learning.storage import LearningStore
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore
    from deeptutor.services.session.turn_runtime import TurnRuntimeManager
    from tests.services.session.test_turn_runtime_subscribe import (
        _isolate_learning_store,
        _mastery_payload,
    )

    _isolate_learning_store(monkeypatch, tmp_path)
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session("session-1")
    seen = []
    hold = asyncio.Event()

    async def hold_turn(execution):
        seen.append(execution.mastery_card_answer_images)
        await hold.wait()

    monkeypatch.setattr(runtime, "_run_turn", hold_turn)
    payload = {
        **_mastery_payload(session["id"], "shared"),
        "attachments": [_attachment(PHOTO)],
        "mastery_answer": {"question_id": "q1", "attachment_ids": ["photo-1"]},
    }

    unreadable = {**payload, "attachments": [{**_attachment(PHOTO), "base64": "@@@"}]}
    with pytest.raises(RuntimeError, match="could not be read"):
        await runtime.start_turn(unreadable)
    assert await store.get_active_turn(session["id"]) is None
    assert LearningStore().get_path_lease("shared") is None

    _, turn = await runtime.start_turn(payload)
    await asyncio.sleep(0)
    assert [ref["attachment_id"] for ref in seen[0]] == ["photo-1"]
    assert seen[0][0]["session_id"] == session["id"]

    await runtime.cancel_turn(turn["id"])
    LearningStore().release_path_lease("shared", turn_id=turn["id"])
