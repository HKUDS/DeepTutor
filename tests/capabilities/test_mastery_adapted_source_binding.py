"""Adapted practice still needs a positive decision and verified citations."""

import pytest

from deeptutor.learning import lesson_evidence
from deeptutor.learning import semantic_assessment as semantic
from tests.capabilities.test_mastery_question_groups import leaf

pytest_plugins = ["tests.capabilities.test_mastery_question_groups"]


@pytest.mark.asyncio
async def test_adapted_revision_binds_its_exact_rubric_to_source_methods(service, monkeypatch):
    progress = service.store.load("p")
    quote = "A simple sentence contains one subject-predicate structure."
    progress.lesson_evidence["kp1"] = {
        "sources": [{"ref": {}, "text": quote, "quote": quote}],
    }
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *a, **k: None)
    question = leaf()
    question.prompt = (
        "Rewrite this supplied situation using complete sentences: a person visits a library."
    )
    question.expected_answer = (
        "Complete subject-predicate sentences that preserve the supplied situation."
    )

    async def request(_config, instruction, payload, **kwargs):
        # This is a contract for the request delivered to the verifier. The
        # model's ability to follow it is evaluated separately with a real model.
        assert "as premises to work with" in instruction
        assert "sources must support the tested principle and the grading rubric" in instruction
        assert "Never treat a proposed answer as a stipulated premise" in instruction
        assert payload["question"]["prompt"] == question.prompt
        assert payload["question"]["expected_answer"] == question.expected_answer
        return {
            "supported": True,
            "citations": [{"index": 0, "quote": quote}],
            "provenance": "adapted",
        }

    monkeypatch.setattr(semantic, "_request", request)
    await semantic.bind_question(service.store, progress, question)
    contract = question.source_evidence["assessment_contract"]
    assert contract["provenance"] == "adapted"
    assert contract["citations"] == [{"index": 0, "quote": quote}]
    semantic.validate_question(service.store, progress, question)
    question.expected_answer = "A different, unverified rubric."
    with pytest.raises(lesson_evidence.LessonUnavailable, match="changed"):
        semantic.validate_question(service.store, progress, question)


@pytest.mark.asyncio
@pytest.mark.parametrize("citations", [[], None, "not a list"])
async def test_positive_decision_without_citations_requests_a_verifiable_citation(
    service, monkeypatch, citations
):
    progress = service.store.load("p")
    progress.lesson_evidence["kp1"] = {
        "sources": [{"ref": {}, "text": "A simple sentence has a subject and a predicate."}],
    }
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *a, **k: None)

    async def request(*args, **kwargs):
        return {
            "supported": True,
            "citations": citations,
            "provenance": "adapted",
            "reason": "The source fully supports the question.",
        }

    monkeypatch.setattr(semantic, "_request", request)
    question = leaf()
    with pytest.raises(
        semantic.AssessmentUnavailable, match="Provide a verifiable citation"
    ) as exc:
        await semantic.bind_question(service.store, progress, question)
    assert "fully supports" not in str(exc.value)
    assert "assessment_contract" not in question.source_evidence


@pytest.mark.parametrize("code", [None, "", "unknown code", {}, 42])
def test_unrecognized_refusal_code_keeps_the_generic_error(code):
    with pytest.raises(semantic.AssessmentUnavailable) as failure:
        semantic._support_contract(leaf(), [], {"supported": False, "reason_code": code})
    assert str(failure.value) == (
        "The selected source does not support this exact question and answer key."
    )
