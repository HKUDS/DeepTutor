"""Inspectable source-to-question-to-durable-evidence workflows (#1611)."""

from __future__ import annotations

from hashlib import sha256
import json
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pymupdf
import pytest

from deeptutor.capabilities.mastery import tools
from deeptutor.learning.models import (
    InteractionStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from deeptutor.learning.policy import is_assessed_mastered, visual_achievements
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.visual_assets import VisualAssetStore, collect_visual_assets
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def lesson(tmp_path, monkeypatch):
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    source = kb / "raw" / "anatomy.pdf"
    image = tmp_path / "images" / "numbered.png"
    image.parent.mkdir()
    picture = Image.new("RGB", (400, 250), "white")
    draw = ImageDraw.Draw(picture)
    draw.ellipse((40, 40, 160, 200), outline="red", width=4)
    draw.text((95, 110), "1", fill="black")
    draw.ellipse((220, 40, 340, 200), outline="blue", width=4)
    draw.text((270, 110), "2", fill="black")
    picture.save(image)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text(
        (50, 50), "Figure 1: Number 1 refers to an artery. The artery lies left of the vein."
    )
    page.insert_image(pymupdf.Rect(50, 80, 450, 330), filename=str(image))
    page.insert_text((50, 360), "Table 1: speed (m/s), row A: 12, row B: 20. Row B is larger.")
    pdf.save(source, deflate=True)
    pdf.close()
    parsed = ParsedDocument(
        markdown="",
        asset_dir=image.parent,
        parser_signature="fixture",
        blocks=[
            {
                "type": "image",
                "img_path": str(image),
                "page_idx": 0,
                "image_caption": ["Figure 1: numbered structures"],
                "text": "Number 1 refers to an artery. The artery lies left of the vein.",
            }
        ],
    )
    candidate = collect_visual_assets(parsed, source, kb)[0]
    VisualAssetStore(kb).publish([candidate])
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_for_rag",
        lambda name: SimpleNamespace(base_dir=kb.parent, name=kb.name) if name == "kb" else None,
    )
    store = LearningStore(tmp_path / "learning")
    service = LearningService(store)
    progress = LearningProgress(book_id="visual")
    kp = KnowledgePoint(
        id="identify",
        name="Identify and interpret the original source",
        type=KnowledgeType.MEMORY,
        module_id="m1",
        required_visual_tasks=["identification"],
    )
    progress.modules = [
        LearningModule(id="m1", name="Source practice", order=0, knowledge_points=[kp])
    ]
    progress.knowledge_types[kp.id] = kp.type
    service.save(progress)
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    session_store = SQLiteSessionStore(tmp_path / "chat.db")
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store", lambda: session_store
    )
    return SimpleNamespace(
        kb=kb,
        source=source,
        asset=candidate.record["asset_id"],
        image_hash=candidate.record["image_sha256"],
        service=service,
        store=store,
        session_store=session_store,
        kp=kp,
    )


def visual(lesson, *, task="identification", cues="none", quote="Number 1 refers to an artery."):
    return {
        "task": task,
        "sources": [{"kb_name": "kb", "asset_id": lesson.asset}],
        "reference_quote": quote,
        "accepted_answers": ["artery", "an artery", "动脉"],
        "key_status": "verified",
        "answer_cues": cues,
    }


async def pose(lesson, **overrides):
    kwargs = {
        "_mastery_path_id": "visual",
        "_attached_kb_names": ["kb"],
        "_inspected_image_hashes": [lesson.image_hash],
        "knowledge_point_id": "identify",
        "question": "Identify numbered structure 1 in the original figure.",
        "expected_answer": "artery",
        "explanation": "The source explains that structure 1 is an artery; the original numbered figure supplies the target.",
        "visual": visual(lesson),
        **overrides,
    }
    if "_inspected_image_hashes" not in overrides:
        from deeptutor.services.rag.source_visuals import retrieve_visual

        kwargs["_inspected_image_hashes"] = [
            sha256(
                retrieve_visual(
                    lesson.kb,
                    "kb",
                    **{
                        key: ref[key]
                        for key in ("asset_id", "source_path", "page", "source_hash", "region")
                        if ref.get(key) is not None
                    },
                ).images[0][1]
            ).hexdigest()
            for ref in kwargs["visual"]["sources"]
        ]
    result = await tools.MasteryQuizTool().execute(**kwargs)
    assert result.success, result.content
    card = result.metadata["mastery_question"]
    return card


@pytest.mark.asyncio
async def test_teach_then_source_visual_practice_equivalent_answer_and_restart(lesson, monkeypatch):
    explanation = (
        "An artery has a thicker wall than a vein; structure 1 is the artery in this source."
    )
    stream = StreamBus(assign_seq=True)
    await stream.content(explanation, source="mastery_path", stage="responding")
    explained = await tools.MasteryNoteExplainedTool().execute(
        _mastery_path_id="visual",
        _session_id="s",
        _turn_id="teaching",
        knowledge_point_id="identify",
        summary="Explained artery/vein prerequisites concisely at beginner level using the numbered source.",
        explanation_quote=explanation,
        _teaching_delivery=lambda: {
            "path_id": "visual",
            "session_id": "s",
            "turn_id": "teaching",
            "segments": stream.public_content_snapshot(source="mastery_path", stage="responding"),
        },
    )
    assert explained.success
    before = lesson.store.load("visual")
    assert before.explained_objectives["identify"]["summary"]
    assert before.mastery_levels.get("identify", 0) == 0
    card = await pose(lesson)
    from deeptutor.learning import semantic_assessment as semantic

    async def translation(config, items):
        assert items[0]["answer"] == "动脉"
        assert items[0]["_visual_images"]
        return {
            card["question_id"]: semantic.Verdict(
                result="correct", confidence=0.99, feedback="Equivalent translation of artery."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", translation)
    assert card["visual"]["sources"][0]["image_url"].endswith(lesson.asset + "?dt_workspace=")
    assert "reference_quote" not in json.dumps(card) and "accepted_answers" not in json.dumps(card)
    result = await tools.MasteryGradeTool().execute(
        _mastery_path_id="visual", question_id=card["question_id"], answer="动脉"
    )
    assert result.success
    grade = result.metadata["mastery_grade"]
    assert grade["result"]["is_correct"]
    fresh = LearningService(LearningStore(lesson.store._root))
    progress = fresh.store.load("visual")
    assert progress.quiz_attempts[0].visual_context["sources"][0]["asset_id"] == lesson.asset
    assert progress.quiz_attempts[0].independent
    assert visual_achievements(progress, "identify") == ["identification"]


@pytest.mark.asyncio
async def test_native_visual_paraphrase_uses_current_pixels_and_retains_assistance(
    lesson, monkeypatch
):
    from deeptutor.learning import semantic_assessment as semantic

    card = await pose(lesson, visual=visual(lesson, cues="visible"))

    async def judge(config, items):
        assert len(items) == 1
        assert items[0]["answer"] == "The red structure is the artery on the left."
        assert any(part["type"] == "image_url" for part in items[0]["_visual_images"])
        return {
            card["question_id"]: semantic.Verdict(
                result="correct", confidence=0.98, feedback="The artery is correctly identified."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    progress, row, _ = await lesson.service.grade_interaction_semantic(
        "visual",
        answer="The red structure is the artery on the left.",
        question_id=card["question_id"],
    )
    assert row.result["is_correct"] is True
    assert progress.quiz_attempts[0].user_answer == "The red structure is the artery on the left."
    assert not progress.quiz_attempts[0].independent
    assert progress.learning_evidence[0].quality <= 0.6


@pytest.mark.asyncio
async def test_native_visual_revocation_during_semantic_call_grants_no_credit(lesson, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    card = await pose(lesson)

    async def judge(config, items):
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_for_rag", lambda name: None
        )
        return {
            card["question_id"]: semantic.Verdict(
                result="correct", confidence=0.98, feedback="Matches."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    from deeptutor.learning.service import MasteryInteractionError

    with pytest.raises(MasteryInteractionError, match="access"):
        await lesson.service.grade_interaction_semantic(
            "visual", answer="The artery is on the left.", question_id=card["question_id"]
        )
    assert not lesson.store.load("visual").quiz_attempts


@pytest.mark.asyncio
async def test_model_supplied_visual_alias_cannot_bypass_semantic_verdict(lesson, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    requested = visual(lesson)
    requested["accepted_answers"] = ["vein"]
    card = await pose(lesson, visual=requested)

    async def judge(config, items):
        assert items[0]["answer"] == "vein"
        return {
            card["question_id"]: semantic.Verdict(
                result="incorrect", confidence=0.99, feedback="The marked vessel is the artery."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    progress, row, _ = await lesson.service.grade_interaction_semantic(
        "visual", answer="vein", question_id=card["question_id"]
    )
    assert row.result["is_correct"] is False
    assert progress.learning_evidence[0].result == "incorrect"


@pytest.mark.asyncio
async def test_assistance_immediate_repeat_and_delayed_independence_are_distinct(lesson):
    first = await pose(lesson, visual=visual(lesson, cues="visible"))
    lesson.service.grade_interaction(
        "visual",
        answer="artery",
        question_id=first["question_id"],
        scheduler=SpacedRepetitionScheduler(),
    )
    second = await pose(lesson)
    progress, _, _ = lesson.service.grade_interaction(
        "visual",
        answer="artery",
        question_id=second["question_id"],
        scheduler=SpacedRepetitionScheduler(),
    )
    assert all(not attempt.independent for attempt in progress.quiz_attempts)
    assert not is_assessed_mastered(progress, lesson.kp)
    assert progress.mastery_levels["identify"] == 0
    assert all(e.hints_used and e.quality <= 0.6 for e in progress.learning_evidence)
    for attempt in progress.quiz_attempts:
        attempt.timestamp -= 86400
    lesson.service.save(progress)
    third = await pose(lesson)
    progress, _, _ = lesson.service.grade_interaction(
        "visual",
        answer="an artery",
        question_id=third["question_id"],
        scheduler=SpacedRepetitionScheduler(),
    )
    assert progress.quiz_attempts[-1].independent
    assert visual_achievements(progress, "identify") == ["identification"]


@pytest.mark.asyncio
async def test_supported_wrong_choice_is_graded_and_faulty_assessment_repair_removes_effect(lesson):
    card = await pose(
        lesson,
        question_type="choice",
        options=[{"label": "A", "body": "artery"}, {"label": "B", "body": "vein"}],
        expected_answer="A",
    )
    wrong = next(option["label"] for option in card["options"] if option["body"] == "vein")
    progress, interaction, _ = lesson.service.grade_interaction(
        "visual",
        answer=wrong,
        question_id=card["question_id"],
        scheduler=SpacedRepetitionScheduler(),
    )
    assert interaction.result["result"] == "incorrect"
    assert progress.learning_evidence[0].result == "incorrect"
    from deeptutor.learning.service import MasteryInteractionError

    with pytest.raises(MasteryInteractionError, match="source-supported"):
        lesson.service.repair_question(
            "visual",
            question_id=card["question_id"],
            action="correct",
            expected_answer=wrong,
            reason="Learner says their answer should be accepted.",
        )
    progress, details = lesson.service.repair_question(
        "visual",
        question_id=card["question_id"],
        action="void",
        reason="Independent review found the target labeling ambiguous.",
        scheduler=SpacedRepetitionScheduler(),
    )
    assert progress.quiz_attempts[0].voided
    assert not progress.learning_evidence
    assert "identify" not in progress.repetition_states
    assert progress.mastery_levels.get("identify", 0) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["key", "wording", "changed", "conflicting_key"])
async def test_ambiguous_unverified_or_changed_evidence_creates_no_negative_mastery(lesson, case):
    v = visual(lesson)
    if case == "key":
        v["reference_quote"] = "Invented unsupported key"
    card = await pose(
        lesson, visual=v, expected_answer="vein" if case == "conflicting_key" else "artery"
    )
    if case == "changed":
        lesson.source.write_bytes(lesson.source.read_bytes() + b"changed source")
    answer = "some unverified terminology" if case == "wording" else "artery"
    progress, interaction, _ = lesson.service.grade_interaction(
        "visual",
        answer=answer,
        question_id=card["question_id"],
        scheduler=SpacedRepetitionScheduler(),
    )
    assert interaction.result["result"] == "ungraded"
    assert interaction.result["is_correct"] is None
    assert (
        not progress.quiz_attempts and not progress.learning_evidence and not progress.error_records
    )
    assert not progress.repetition_states


@pytest.mark.asyncio
async def test_retry_is_one_attempt_but_new_question_is_new_evidence_and_outline_cannot_transfer_it(
    lesson,
):
    first = await pose(lesson)
    for _ in range(2):
        lesson.service.grade_interaction(
            "visual", answer="artery", question_id=first["question_id"]
        )
    second = await pose(lesson)
    progress, _, _ = lesson.service.grade_interaction(
        "visual", answer="artery", question_id=second["question_id"]
    )
    assert len(progress.quiz_attempts) == len(progress.learning_evidence) == 2
    old_id = progress.modules[0].knowledge_points[0].id
    replacement = [
        LearningModule(
            id="m1",
            name="Different subject",
            order=0,
            knowledge_points=[
                KnowledgePoint(
                    id=old_id,
                    name="Unrelated geometry theorem",
                    type=KnowledgeType.MEMORY,
                    module_id="m1",
                )
            ],
        )
    ]
    progress = lesson.service.replace_modules_for_path("visual", replacement)
    assert progress.modules[0].knowledge_points[0].id != old_id
    assert not is_assessed_mastered(progress, progress.modules[0].knowledge_points[0])


@pytest.mark.asyncio
async def test_relationship_table_and_comparison_use_both_original_sources(lesson):
    for task, expected, quote in [
        ("relationship", "left", "The artery lies left of the vein."),
        ("table_graph", "Row B", "Row B is larger."),
    ]:
        refs = (
            [{"kb_name": "kb", "asset_id": lesson.asset}]
            if task == "relationship"
            else [{"kb_name": "kb", "source_path": "anatomy.pdf", "page": 1}]
        )
        card = await pose(
            lesson,
            expected_answer=expected,
            question="Interpret the relationship/value in the original source.",
            visual={
                "task": task,
                "sources": refs,
                "reference_quote": quote,
                "key_status": "verified",
                "accepted_answers": [expected],
                "answer_cues": "none",
            },
        )
        progress, interaction, _ = lesson.service.grade_interaction(
            "visual", answer=expected, question_id=card["question_id"]
        )
        assert interaction.result["result"] == "correct"
        assert progress.learning_evidence[-1].visual_context["task"] == task
    v = visual(lesson, task="comparison")
    v["sources"] = [v["sources"][0], {"kb_name": "kb", "source_path": "anatomy.pdf", "page": 1}]
    card = await pose(lesson, visual=v)
    assert len(card["visual"]["sources"]) == 2


def test_generic_text_success_does_not_satisfy_required_visual_task(lesson):
    progress = lesson.store.load("visual")
    progress.mastery_levels["identify"] = 1.0
    assert not is_assessed_mastered(progress, lesson.kp)


@pytest.mark.asyncio
async def test_pdf_region_can_assess_relationship_without_displaying_the_reference_key(
    lesson, monkeypatch
):
    card = await pose(
        lesson,
        expected_answer="left",
        question="Describe where numbered structure 1 is relative to structure 2.",
        visual={
            "task": "relationship",
            "sources": [
                {
                    "kb_name": "kb",
                    "source_path": "anatomy.pdf",
                    "page": 1,
                    "region": [0.07, 0.08, 0.8, 0.4],
                }
            ],
            "reference_quote": "The artery lies left of the vein.",
            "key_status": "verified",
            "accepted_answers": ["left", "左侧"],
            "answer_cues": "none",
        },
    )
    assert card["visual"]["hints_used"] == 0
    assert card["visual"]["key_status"] == "verified"
    from deeptutor.learning import semantic_assessment as semantic

    async def translation(config, items):
        assert items[0]["answer"] == "左侧"
        assert items[0]["_visual_images"]
        return {
            card["question_id"]: semantic.Verdict(
                result="correct", confidence=0.99, feedback="Correct relative position."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", translation)
    progress, interaction, _ = await lesson.service.grade_interaction_semantic(
        "visual", answer="左侧", question_id=card["question_id"]
    )
    assert interaction.result["result"] == "correct"
    assert progress.quiz_attempts[-1].independent
    assert "relationship" in visual_achievements(progress, "identify")


@pytest.mark.asyncio
async def test_help_after_question_is_assisted_and_deferral_never_claims_mastery(lesson):
    card = await pose(lesson)
    explanation = (
        "The thick-walled vessel is an artery; compare the two vessel walls in the source."
    )
    stream = StreamBus(assign_seq=True)
    await stream.content(explanation, source="mastery_path", stage="responding")
    explained = await tools.MasteryNoteExplainedTool().execute(
        _mastery_path_id="visual",
        _session_id="s",
        _turn_id="hint",
        knowledge_point_id="identify",
        summary="Gave a source-based hint after the learner asked for help with structure 1.",
        explanation_quote=explanation,
        _teaching_delivery=lambda: {
            "path_id": "visual",
            "session_id": "s",
            "turn_id": "hint",
            "segments": stream.public_content_snapshot(source="mastery_path", stage="responding"),
        },
    )
    assert explained.success, explained.content
    progress, _interaction, _ = lesson.service.grade_interaction(
        "visual", answer="artery", question_id=card["question_id"]
    )
    assert not progress.quiz_attempts[0].independent
    assert progress.learning_evidence[0].hints_used
    deferred = await tools.MasteryDeferObjectiveTool().execute(
        _mastery_path_id="visual", knowledge_point_id="identify", reason="Move on for now"
    )
    assert deferred.success
    fresh = lesson.store.load("visual")
    assert "identify" in fresh.deferred_objectives
    assert not is_assessed_mastered(fresh, lesson.kp)


@pytest.mark.asyncio
@pytest.mark.parametrize("hashes", [[], ["some_other_image"]])
async def test_source_without_inspected_pixels_is_not_registered(lesson, hashes):
    """A resolved source the model never saw must not become an answer card (#2494)."""
    from deeptutor.learning.visual_practice import prepare_visual

    before = lesson.store.load("visual").model_dump()
    with pytest.raises(ValueError, match="No matching source pixels were verified"):
        prepare_visual(
            visual(lesson),
            expected_answer="artery",
            options={},
            attached_kbs=["kb"],
            inspected_image_hashes=hashes,
        )
    result = await tools.MasteryQuizTool().execute(
        _mastery_path_id="visual",
        _attached_kb_names=["kb"],
        _inspected_image_hashes=hashes,
        knowledge_point_id="identify",
        question="Identify numbered structure 1 in the original figure.",
        expected_answer="artery",
        explanation="The source explains that structure 1 is an artery.",
        visual=visual(lesson),
    )
    assert not result.success
    assert result.content.startswith("Visual practice is unavailable:")
    assert "No matching source pixels were verified" in result.content
    assert "no assessment was created" in result.content
    grouped = await tools.MasteryQuizTool().execute(
        _mastery_path_id="visual",
        _attached_kb_names=["kb"],
        _inspected_image_hashes=hashes,
        questions=[
            {
                "knowledge_point_id": "identify",
                "question": "Identify numbered structure 1.",
                "expected_answer": "artery",
                "visual": visual(lesson),
            },
            {
                "knowledge_point_id": "identify",
                "question": "Identify numbered structure 2.",
                "expected_answer": "vein",
                "visual": visual(lesson),
            },
        ],
    )
    assert not grouped.success
    assert "Visual practice is unavailable" in grouped.content
    assert lesson.store.load("visual").model_dump() == before
    assert lesson.store.get_active_interaction("visual") is None


def _legacy_uninspected_card() -> PendingQuestion:
    """A visual card stored before uninspected sources were refused."""
    return PendingQuestion(
        question_id="legacy-visual",
        knowledge_point_id="identify",
        module_id="m1",
        prompt="Trace the automaton using the rule on the cited page.",
        expected_answer="accept",
        explanation="The transition table in the stem is enough; the page was only a citation.",
        visual_context={
            "task": "relationship",
            "sources": [
                {
                    "kb_name": "kb",
                    "source_path": "anatomy.pdf",
                    "page": 1,
                    "region": [0, 0, 1, 1],
                    "asset_id": "",
                }
            ],
            "answer_cues": "unverified",
            "key_status": "unverified",
            "pixels_inspected": False,
            "reference_quote": "tracing rule",
            "reference_answer": "accept",
            "hints_used": 0,
        },
    )


@pytest.mark.asyncio
async def test_legacy_uninspected_visual_stays_ungraded_and_correct_asks_to_void(lesson):
    """Cards already stored without inspected pixels can be voided, not re-keyed (#2494)."""
    lesson.service.register_question("visual", _legacy_uninspected_card())
    graded = await tools.MasteryGradeTool().execute(
        _mastery_path_id="visual",
        question_id="legacy-visual",
        answer="accept",
    )
    assert graded.success
    receipt = graded.metadata["mastery_grade"]["result"]
    assert receipt["result"] == "ungraded"
    assert receipt["is_correct"] is None
    assert "No matching source pixels were verified" in receipt["feedback"]
    progress = lesson.store.load("visual")
    assert not progress.quiz_attempts
    assert not progress.learning_evidence
    assert progress.mastery_levels.get("identify", 0) == 0
    assert not visual_achievements(progress, "identify")

    corrected = await tools.MasteryRepairQuestionTool().execute(
        _mastery_path_id="visual",
        question_id="legacy-visual",
        action="correct",
        expected_answer="accept",
        reason="The learner's trace matches the transition table.",
    )
    assert not corrected.success
    assert "Void it and pose a supported replacement" in corrected.content
    assert "No matching source pixels" not in corrected.content
    held = lesson.store.get_interaction("visual", "legacy-visual")
    assert held.status == InteractionStatus.ANSWERED
    assert lesson.store.load("visual").pending_question is not None
    assert lesson.store.load("visual").mastery_levels.get("identify", 0) == 0

    voided = await tools.MasteryRepairQuestionTool().execute(
        _mastery_path_id="visual",
        question_id="legacy-visual",
        action="void",
        reason="The visual was never inspected, so the card cannot be graded.",
    )
    assert voided.success, voided.content
    fresh = lesson.store.load("visual")
    assert fresh.pending_question is None
    assert not fresh.quiz_attempts
    assert fresh.mastery_levels.get("identify", 0) == 0
    assert (
        lesson.store.get_interaction("visual", "legacy-visual").status
        == InteractionStatus.ABANDONED
    )


@pytest.mark.asyncio
async def test_canonical_writer_keeps_visual_context_and_ungraded_attempt_once(lesson):
    session = await lesson.session_store.create_session()
    v = visual(lesson)
    v["key_status"] = "unverified"
    card = await pose(lesson, visual=v)
    for _ in range(2):
        result = await tools.MasteryGradeTool().execute(
            _mastery_path_id="visual",
            _session_id=session["id"],
            _turn_id="turn1",
            question_id=card["question_id"],
            answer="artery",
        )
        assert result.success
        assert result.metadata["mastery_grade"]["result"]["result"] == "ungraded"
    with lesson.session_store._connect() as connection:
        row = connection.execute("SELECT assessment_json FROM assessment_attempts").fetchall()
    assert len(row) == 1
    payload = json.loads(row[0][0])
    assert payload["result"] == "ungraded"
    assert payload["visual_context"]["sources"][0]["asset_id"] == lesson.asset
