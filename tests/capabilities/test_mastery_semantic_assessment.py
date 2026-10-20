"""Semantic decisions are bounded, fenced, and never manufactured from a failure."""

import pytest

from deeptutor.learning.models import InteractionStatus
from deeptutor.learning.service import MasteryInteractionError
from tests.capabilities.test_mastery_question_groups import group, leaf

pytest_plugins = ["tests.capabilities.test_mastery_question_groups"]


@pytest.mark.asyncio
@pytest.mark.parametrize("result,quality", [("partial", 0.5), ("incorrect", 0.0)])
async def test_qualitative_bank_preserves_typed_result(monkeypatch, result, quality):
    from deeptutor.capabilities.mastery.tools import _sync_qualitative_to_question_bank

    captured = []

    async def record(value):
        captured.append(value)

    monkeypatch.setattr("deeptutor.learning.assessment.record_assessment", record)
    await _sync_qualitative_to_question_bank(
        path_id="p",
        session_id="s",
        turn_id="t",
        knowledge_point_id="kp",
        knowledge_point_name="Explain",
        passed=False,
        evidence="Actual learner reply",
        result=result,
        quality=quality,
    )
    assert captured[0].result == result
    assert captured[0].quality == quality


@pytest.mark.parametrize("grouped", [False, True])
def test_loop_seed_preserves_partial_and_clarification_receipts(grouped):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    receipt = {
        "question_id": "q1",
        "result": "partial",
        "is_correct": None,
        "final": True,
        "feedback": "One relationship is missing.",
    }
    context = UnifiedContext(user_message="my reply")
    context.metadata["mastery_card_grade"] = {
        "is_correct": None,
        "result": {"results": [receipt], "complete": True} if grouped else receipt,
    }
    seed = MasteryLoopCapability()._grade_seed(context)
    assert "partial" in seed and "One relationship is missing." in seed
    receipt.update(result="ungraded", final=False, needs_clarification=True)
    if grouped:
        context.metadata["mastery_card_grade"]["result"].update(
            complete=False, remaining_question_ids=["q1"]
        )
    seed = MasteryLoopCapability()._grade_seed(context)
    assert "ungraded" in seed and "clarif" in seed
    assert "incorrect" not in seed
    assert "correct option" not in seed and "pose the next question" not in seed


@pytest.mark.asyncio
async def test_corrected_key_does_not_inherit_old_aliases(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    question = leaf(expected="alpha")
    question.accepted_answers = ["alpha", "first letter"]
    service.register_question("p", question)
    await service.grade_interaction_semantic("p", answer="first letter", question_id="q1")

    async def judge(config, items):
        assert items[0]["expected_answer"] == "beta"
        assert items[0]["accepted_answers"] == []
        return {
            "q1": semantic.Verdict(
                result="incorrect",
                confidence=0.99,
                feedback="The corrected question asks for beta.",
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    progress, receipt = await service.repair_question_semantic(
        "p", "q1", action="correct", expected_answer="beta", reason="Corrected the mistaken key."
    )
    assert receipt["is_correct"] is False
    assert progress.quiz_attempts[0].result == "incorrect"


@pytest.mark.asyncio
async def test_challenged_group_grade_reassesses_saved_answer_and_repairs_all_receipts(
    service, monkeypatch
):
    from deeptutor.learning import semantic_assessment as semantic

    service.register_question("p", group())
    # Historical lexical judgment incorrectly rejected a correct explanation.
    service.grade_interaction(
        "p",
        answer="",
        question_id="g",
        answers={"q1": "The first Greek letter is alpha.", "q2": "beta"},
    )

    async def judge(config, items):
        assert items[0]["answer"] == "The first Greek letter is alpha."
        return {
            "q1": semantic.Verdict(
                result="correct", confidence=0.99, feedback="The longer explanation is equivalent."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    progress, receipt = await service.repair_question_semantic(
        "p",
        "q1",
        action="correct",
        expected_answer="alpha",
        reason="The learner challenged the lexical rejection.",
    )
    assert receipt["is_correct"] is True and receipt["result"] == "correct"
    assert progress.quiz_attempts[0].result == "correct"
    assert progress.learning_evidence[0].result == "correct"
    parent = service.store.get_interaction("p", "g")
    assert parent.result["result"] == "correct"
    assert parent.result["results"][0]["feedback"] == "The longer explanation is equivalent."
    assert len(progress.quiz_attempts) == 2


@pytest.mark.asyncio
async def test_paraphrase_is_semantic_and_replay_is_free(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    calls = []

    async def judge(config, items):
        calls.append(items)
        return {
            item["question_id"]: semantic.Verdict(
                result="correct", confidence=0.96, feedback="Same meaning."
            )
            for item in items
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.register_question("p", leaf(expected="photosynthesis"))
    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", answer="Plants turn sunlight into stored chemical energy.", question_id="q1"
    )
    assert interaction.result["is_correct"] is True
    assert progress.quiz_attempts[0].user_answer.startswith("Plants")
    await service.grade_interaction_semantic("p", answer="anything", question_id="q1")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_uncertain_group_keeps_only_unfinished_leaf_revisable(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    async def judge(config, items):
        return {
            item["question_id"]: semantic.Verdict(
                result="ungraded", confidence=0.4, feedback="Explain the mechanism."
            )
            for item in items
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.register_question("p", group())
    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "maybe"}
    )
    assert interaction.result["remaining_question_ids"] == ["q2"]
    assert len(progress.quiz_attempts) == 1
    assert service.store.get_interaction("p", "q2").status == InteractionStatus.GRADED
    service.record_question_answer("p", "", interaction_id="g", answers={"q2": "beta"})
    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", answer="", question_id="g"
    )
    assert interaction.result["complete"]
    assert len(progress.quiz_attempts) == 2
    with pytest.raises(MasteryInteractionError):
        service.record_question_answer("p", "", interaction_id="g", answers={"q1": "changed"})


@pytest.mark.asyncio
async def test_provider_failure_does_not_save_wrong_answer(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    async def judge(config, items):
        raise semantic.AssessmentUnavailable("Retry connection")

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.register_question("p", leaf())
    with pytest.raises(MasteryInteractionError, match="Retry"):
        await service.grade_interaction_semantic("p", answer="a paraphrase", question_id="q1")
    assert not service.store.load("p").quiz_attempts


@pytest.mark.asyncio
async def test_partial_has_own_evidence_without_error_record(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    async def judge(config, items):
        return {
            item["question_id"]: semantic.Verdict(
                result="partial", confidence=0.95, feedback="Missing the second part."
            )
            for item in items
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.register_question("p", leaf())
    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", answer="some of it", question_id="q1"
    )
    assert interaction.result["result"] == "partial"
    assert interaction.result["is_correct"] is None
    assert progress.quiz_attempts[0].result == "partial"
    assert progress.learning_evidence[0].result == "partial"
    assert progress.mastery_levels["kp1"] == 0.5
    assert not progress.error_records


@pytest.mark.asyncio
async def test_changed_contract_while_judging_cannot_commit(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    async def judge(config, items):
        def change(tx):
            row = tx.get_interaction("q1")
            row.question.expected_answer = "different key"
            tx.put_interaction(row)

        service.store.mutate("p", change)
        return {"q1": semantic.Verdict(result="correct", confidence=0.95, feedback="Matches")}

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.register_question("p", leaf())
    with pytest.raises(MasteryInteractionError, match="changed"):
        await service.grade_interaction_semantic("p", answer="paraphrase", question_id="q1")
    assert not service.store.load("p").quiz_attempts


@pytest.mark.asyncio
async def test_permission_rechecked_after_judgment(service, monkeypatch):
    from deeptutor.learning import lesson_evidence
    from deeptutor.learning import semantic_assessment as semantic

    allowed = True

    def validate(*args, **kwargs):
        if not allowed:
            raise lesson_evidence.LessonUnavailable("Source access changed")

    async def judge(config, items):
        nonlocal allowed
        allowed = False
        return {"q1": semantic.Verdict(result="correct", confidence=0.95, feedback="Matches")}

    monkeypatch.setattr(semantic, "judge_answers", judge)
    monkeypatch.setattr(lesson_evidence, "validate_evidence", validate)
    service.register_question("p", leaf())
    with pytest.raises(MasteryInteractionError, match="access"):
        await service.grade_interaction_semantic("p", answer="paraphrase", question_id="q1")
    assert not service.store.load("p").quiz_attempts


@pytest.mark.asyncio
async def test_single_uncertain_answer_revises_without_reopening_lifecycle(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    async def judge(config, items):
        return {
            "q1": semantic.Verdict(result="correct", confidence=0.3, feedback="Please clarify.")
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.register_question("p", leaf())
    service.record_question_answer("p", "unclear", interaction_id="q1")
    progress, row, _ = await service.grade_interaction_semantic(
        "p", answer="invented", question_id="q1"
    )
    assert row.status == InteractionStatus.ANSWERED
    assert row.user_answer == "unclear"
    assert not progress.quiz_attempts
    service.record_question_answer("p", "alpha", interaction_id="q1")
    progress, row, _ = await service.grade_interaction_semantic(
        "p", answer="ignored", question_id="q1"
    )
    assert row.result["final"] and row.result["is_correct"] is True
    assert len(progress.quiz_attempts) == 1


@pytest.mark.asyncio
async def test_negation_is_not_a_lexical_fast_pass(service, monkeypatch):
    from deeptutor.learning import semantic_assessment as semantic

    async def judge(config, items):
        assert items[0]["answer"] == "not alpha"
        return {
            "q1": semantic.Verdict(
                result="incorrect", confidence=0.98, feedback="The negation contradicts the key."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.register_question("p", leaf())
    progress, row, _ = await service.grade_interaction_semantic(
        "p", answer="not alpha", question_id="q1"
    )
    assert row.result["result"] == "incorrect"
    assert len(progress.error_records) == 1


@pytest.mark.asyncio
async def test_qualitative_grades_actual_explanation_not_passed_flag(service, monkeypatch):
    from deeptutor.capabilities.mastery import tools
    from deeptutor.learning import semantic_assessment as semantic
    from deeptutor.learning.models import KnowledgeType

    def concept(tx):
        tx.progress.modules[0].knowledge_points[0].type = KnowledgeType.CONCEPT
        tx.touch()

    service.store.mutate("p", concept)

    async def judge(config, items):
        assert items[0]["answer"] == "I do not know"
        return {
            "kp1": semantic.Verdict(
                result="incorrect", confidence=0.99, feedback="An explanation is still needed."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    result = await tools.MasteryAssessTool().execute(
        _mastery_path_id="p",
        knowledge_point_id="kp1",
        passed=True,
        feedback="Great!",
        _learner_message="I do not know",
    )
    assert result.success
    progress = service.store.load("p")
    assert progress.qualitative_mastery["kp1"] is False
    assert progress.feynman_explanations["kp1"] == "I do not know"
    assert progress.learning_evidence[0].result == "incorrect"


@pytest.mark.asyncio
async def test_partial_packet_binds_only_exact_question_and_rejects_forged_original(
    service, monkeypatch
):
    from deeptutor.learning import lesson_evidence
    from deeptutor.learning import semantic_assessment as semantic

    progress = service.store.load("p")
    progress.lesson_evidence["kp1"] = {
        "coverage": {"scope": "focus", "complete": False},
        "sources": [
            {
                "ref": {},
                "text": "alpha is the first letter",
                "quote": "alpha",
                "supports": "letter order",
            }
        ],
    }
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *args, **kwargs: None)

    async def request(*args, **kwargs):
        return {
            "supported": True,
            "citations": [{"index": 0, "quote": "alpha is the first letter"}],
            "provenance": "original",
        }

    monkeypatch.setattr(semantic, "_request", request)
    question = leaf()
    await semantic.bind_question(service.store, progress, question)
    assert question.source_evidence["assessment_contract"]["provenance"] == "adapted"
    semantic.validate_question(service.store, progress, question)
    question.expected_answer = "beta"
    with pytest.raises(lesson_evidence.LessonUnavailable, match="changed"):
        semantic.validate_question(service.store, progress, question)


@pytest.mark.asyncio
async def test_question_support_must_quote_real_evidence(service, monkeypatch):
    from deeptutor.learning import lesson_evidence
    from deeptutor.learning import semantic_assessment as semantic

    progress = service.store.load("p")
    progress.lesson_evidence["kp1"] = {"sources": [{"ref": {}, "text": "unrelated material"}]}
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *args, **kwargs: None)

    async def request(*args, **kwargs):
        return {"supported": True, "citations": [{"index": 0, "quote": "fabricated fact"}]}

    monkeypatch.setattr(semantic, "_request", request)
    with pytest.raises(semantic.AssessmentUnavailable, match="absent"):
        await semantic.bind_question(service.store, progress, leaf())


@pytest.mark.asyncio
async def test_group_source_binding_is_one_call_with_individual_contracts(service, monkeypatch):
    from deeptutor.learning import lesson_evidence
    from deeptutor.learning import semantic_assessment as semantic

    progress = service.store.load("p")
    packet = {"sources": [{"ref": {}, "text": "alpha and beta are letters"}]}
    progress.lesson_evidence = {"kp1": packet, "kp2": packet}
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *args, **kwargs: None)
    calls = []

    async def request(config, instruction, payload, **kwargs):
        calls.append(payload)
        return {
            "contracts": [
                {
                    "question_id": item["question"]["question_id"],
                    "supported": True,
                    "citations": [{"index": 0, "quote": "alpha and beta are letters"}],
                    "provenance": "adapted",
                }
                for item in payload["questions"]
            ]
        }

    monkeypatch.setattr(semantic, "_request", request)
    question = group()
    await semantic.bind_questions(service.store, progress, question.questions)
    assert len(calls) == 1
    assert (
        question.questions[0].source_evidence["assessment_contract"]["fingerprint"]
        != question.questions[1].source_evidence["assessment_contract"]["fingerprint"]
    )


@pytest.mark.asyncio
async def test_source_assessment_sends_pixels_with_no_silent_fallback(monkeypatch):
    from contextlib import nullcontext

    from deeptutor.learning import lesson_evidence
    from deeptutor.learning import semantic_assessment as semantic
    from deeptutor.services.llm import factory
    from deeptutor.services.workspace import knowledge

    source = {"ref": {"kb_ref": "test-kb"}}
    image = {
        "role": "user",
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,synthetic"}}],
    }
    monkeypatch.setattr(lesson_evidence, "image_message", lambda sources: image)
    monkeypatch.setattr(knowledge, "learning_source_access", lambda names: nullcontext())

    async def complete(**kwargs):
        assert kwargs["allow_image_fallback"] is False
        assert kwargs["messages"][-1]["role"] == "user"
        assert [
            part for part in kwargs["messages"][-1]["content"] if part["type"] == "image_url"
        ] == image["content"]
        return '{"verdicts":[{"question_id":"q","result":"correct","confidence":0.99,"feedback":"The visual relationship matches."}]}'

    monkeypatch.setattr(factory, "complete_with_config", complete)
    result = await semantic.judge_answers(
        object(), [{"question_id": "q", "source_evidence": {"sources": [source]}}]
    )
    assert result["q"].result == "correct"


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [True, False])
async def test_group_visual_assessment_budgets_unique_pixels_and_retains_source_labels(
    monkeypatch, shared
):
    from copy import deepcopy
    import json

    from deeptutor.learning import semantic_assessment as semantic
    from deeptutor.services.llm import factory

    items = [
        {
            "question_id": f"q{i}",
            "answer": "The membrane separates the two compartments.",
            "_visual_images": [
                part
                for page in range(2)
                for part in (
                    {"type": "text", "text": f"Question q{i}, source page {page}"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,page-{page if shared else i * 2 + page}"
                        },
                    },
                )
            ],
        }
        for i in range(4)
    ]
    before = deepcopy(items)
    requests = []

    async def complete(**kwargs):
        requests.append(kwargs)
        parts = [
            part
            for message in kwargs["messages"]
            if isinstance(message["content"], list)
            for part in message["content"]
        ]
        assert sum(part["type"] == "image_url" for part in parts) == 2
        for i in range(4):
            assert any(f"Question q{i}, source page" in part.get("text", "") for part in parts)
        assert kwargs["allow_image_fallback"] is False
        return json.dumps(
            {
                "verdicts": [
                    {
                        "question_id": f"q{i}",
                        "result": "correct",
                        "confidence": 0.99,
                        "feedback": "The relationship matches.",
                    }
                    for i in range(4)
                ]
            }
        )

    monkeypatch.setattr(factory, "complete_with_config", complete)
    if shared:
        verdicts = await semantic.judge_answers(object(), items)
        assert len(verdicts) == 4 and len(requests) == 1
    else:
        with pytest.raises(semantic.AssessmentUnavailable, match="split the group"):
            await semantic.judge_answers(object(), items)
        assert not requests
    assert items == before


@pytest.mark.asyncio
async def test_scoped_group_clarification_resume_and_exactly_once_credit(service, monkeypatch):
    from deeptutor.learning import lesson_evidence
    from deeptutor.learning import semantic_assessment as semantic
    from deeptutor.learning.pending import public_pending_question

    packet = {
        "id": "scoped-source",
        "coverage": {"scope": "focus", "complete": False},
        "sources": [
            {
                "ref": {},
                "text": "alpha and beta are letters",
                "quote": "alpha and beta",
                "supports": "letter names",
            }
        ],
    }

    def source_check(store, progress, kp_id, evidence, *, allow_partial=False):
        assert evidence["id"] == "scoped-source"
        if not allow_partial:
            raise lesson_evidence.LessonUnavailable("Only this focused teaching slice is covered")

    monkeypatch.setattr(lesson_evidence, "validate_evidence", source_check)

    async def support(*args, **kwargs):
        return {
            "supported": True,
            "citations": [{"index": 0, "quote": "alpha and beta are letters"}],
            "provenance": "adapted",
        }

    monkeypatch.setattr(semantic, "_request", support)
    progress = service.store.load("p")
    progress.lesson_evidence = {"kp1": packet, "kp2": packet}
    service.save(progress)
    question = group()
    for child in question.questions:
        await semantic.bind_question(service.store, progress, child)
    service.register_question("p", question)
    assert "assessment_contract" not in str(public_pending_question(question).to_dict())
    calls = []

    async def judge(config, items):
        calls.append(items)
        return {
            "q2": semantic.Verdict(
                result="ungraded", confidence=0.4, feedback="Please clarify the second letter."
            )
        }

    monkeypatch.setattr(semantic, "judge_answers", judge)
    service.record_question_answer(
        "p", "", interaction_id="g", answers={"q1": "alpha", "q2": "maybe"}
    )
    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", answer="", question_id="g"
    )
    assert interaction.status == InteractionStatus.ANSWERED
    assert interaction.result["remaining_question_ids"] == ["q2"]
    service.register_question("p", None, pending_action="resume", resume_question_id="g")
    service.record_question_answer("p", "", interaction_id="g", answers={"q2": "beta"})
    progress, interaction, _ = await service.grade_interaction_semantic(
        "p", answer="", question_id="g"
    )
    assert interaction.result["complete"]
    assert [attempt.question_id for attempt in progress.quiz_attempts] == ["q1", "q2"]
    replay, _, replayed = await service.grade_interaction_semantic("p", answer="", question_id="g")
    assert replayed and len(replay.learning_evidence) == 2 and len(calls) == 1
