"""Adapted practice still needs a positive decision and verified citations."""

import pytest

from deeptutor.learning import lesson_evidence
from deeptutor.learning import semantic_assessment as semantic
from tests.capabilities.test_mastery_question_groups import leaf

pytest_plugins = ["tests.capabilities.test_mastery_question_groups"]


def supported_source_decision(quote, *, provenance="adapted"):
    return {
        "supported": True,
        "provenance": provenance,
        "requirements": {
            "stipulated_premise": {"outcome": "not_applicable", "citations": []},
            "source_supported_requirement": {
                "outcome": "supported",
                "citations": [{"index": 0, "quote": quote}],
            },
            "asserted_answer_claim": {"outcome": "not_applicable", "citations": []},
        },
    }


@pytest.mark.asyncio
async def test_adapted_revision_binds_its_exact_rubric_to_source_methods(service, monkeypatch):
    progress = service.store.load("p")
    quote = "A simple sentence contains one subject-predicate structure."
    progress.lesson_evidence["kp1"] = {
        "sources": [{"ref": {}, "text": quote, "quote": quote}],
    }
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *a, **k: None)
    question = leaf()
    premise = "a person visits a library"
    question.prompt = f"Rewrite this supplied situation using complete sentences: {premise}."
    question.expected_answer = "A reader goes to a place that lends books. Accept complete sentences that retain the meaning."

    async def request(_config, _instruction, payload, **kwargs):
        assert payload["question"]["prompt"] == question.prompt
        assert payload["question"]["expected_answer"] == question.expected_answer
        requirements = payload["requirements"]
        assert set(requirements) == {
            "stipulated_premise",
            "source_supported_requirement",
            "asserted_answer_claim",
        }
        assert requirements["stipulated_premise"] == ["prompt"]
        assert "expected_answer" in requirements["source_supported_requirement"]
        assert "expected_answer" in requirements["asserted_answer_claim"]
        decision = supported_source_decision(quote)
        decision["requirements"]["stipulated_premise"]["excerpts"] = [premise]
        return decision

    monkeypatch.setattr(semantic, "_request", request)
    await semantic.bind_question(service.store, progress, question)
    contract = question.source_evidence["assessment_contract"]
    assert contract["provenance"] == "adapted"
    assert contract["citations"] == [{"index": 0, "quote": quote}]
    requirements = contract["requirements"]
    assert requirements["stipulated_premise"]["outcome"] == "not_applicable"
    assert requirements["stipulated_premise"]["citations"] == []
    assert requirements["source_supported_requirement"]["citations"] == contract["citations"]
    assert requirements["asserted_answer_claim"]["outcome"] == "not_applicable"
    assert requirements["asserted_answer_claim"]["citations"] == []
    semantic.validate_question(service.store, progress, question)
    question.expected_answer = "A different, unverified rubric."
    with pytest.raises(lesson_evidence.LessonUnavailable, match="changed"):
        semantic.validate_question(service.store, progress, question)


@pytest.mark.asyncio
@pytest.mark.parametrize("requirement", ["source_supported_requirement", "asserted_answer_claim"])
@pytest.mark.parametrize("citations", [[], None, "not a list"])
async def test_positive_decision_without_citations_requests_a_verifiable_citation(
    service, monkeypatch, requirement, citations
):
    progress = service.store.load("p")
    progress.lesson_evidence["kp1"] = {
        "sources": [{"ref": {}, "text": "A simple sentence has a subject and a predicate."}],
    }
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *a, **k: None)

    async def request(*args, **kwargs):
        decision = supported_source_decision("A simple sentence has a subject and a predicate.")
        decision["requirements"][requirement] = {"outcome": "supported", "citations": citations}
        return {**decision, "reason": "The source fully supports the question."}

    monkeypatch.setattr(semantic, "_request", request)
    question = leaf()
    with pytest.raises(
        semantic.AssessmentUnavailable, match="Provide a verifiable citation"
    ) as exc:
        await semantic.bind_question(service.store, progress, question)
    assert "fully supports" not in str(exc.value)
    assert "assessment_contract" not in question.source_evidence


@pytest.mark.parametrize("visual", [False, True])
def test_supported_answer_claim_and_rubric_keep_separate_citations(visual):
    rubric = "A complete sentence has a subject and a predicate."
    claim = "The library closes at five."
    question = leaf(expected=claim)
    question.prompt = "When does the library close? Answer in a complete sentence."
    sources = [
        {"ref": {}, "text": rubric, "quote": ""},
        {
            "ref": {"kb_ref": "test-kb"},
            "text": "" if visual else f"{question.prompt} {claim}",
            "quote": "",
        },
    ]
    decision = supported_source_decision(rubric, provenance="original")
    claim_citation = (
        {"index": 1, "visual_observation": "The posted schedule shows 5:00 as closing time."}
        if visual
        else {"index": 1, "quote": claim}
    )
    decision["requirements"]["asserted_answer_claim"] = {
        "outcome": "supported",
        "citations": [claim_citation],
    }

    contract = semantic._support_contract(question, sources, decision)

    assert contract["provenance"] == ("adapted" if visual else "original")
    assert contract["citations"] == [{"index": 0, "quote": rubric}, claim_citation]
    assert contract["requirements"]["asserted_answer_claim"]["citations"] == [claim_citation]


@pytest.mark.asyncio
@pytest.mark.parametrize("mislabeled_as_premise", [False, True])
async def test_answer_only_statistic_cannot_be_exempted(
    service, monkeypatch, mislabeled_as_premise
):
    quote = "A complete sentence has a subject and a predicate."
    progress = service.store.load("p")
    progress.lesson_evidence["kp1"] = {"sources": [{"ref": {}, "text": quote}]}
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *a, **k: None)
    question = leaf()
    question.prompt = (
        "Rewrite the given scenario in complete sentences: a reader checks a catalogue."
    )
    claim = "Checking the catalogue saves exactly four trips per month."
    question.expected_answer = f"Treat this as given and require it in the revision: {claim}"

    async def request(_config, _instruction, payload, **kwargs):
        assert payload["requirements"]["stipulated_premise"] == ["prompt"]
        assert "expected_answer" in payload["requirements"]["asserted_answer_claim"]
        decision = supported_source_decision(quote)
        if mislabeled_as_premise:
            decision["requirements"]["stipulated_premise"]["excerpts"] = [claim]
        else:
            decision["requirements"]["asserted_answer_claim"]["outcome"] = "unsupported"
        return decision

    monkeypatch.setattr(semantic, "_request", request)
    hint = None if mislabeled_as_premise else "Verify the factual conclusion"
    with pytest.raises(semantic.AssessmentUnavailable, match=hint) as failure:
        await semantic.bind_question(service.store, progress, question)
    assert claim not in str(failure.value)
    assert "assessment_contract" not in question.source_evidence


@pytest.mark.parametrize("malformed", ["missing", "unknown", "incomplete", "exempt-skill"])
def test_flat_citations_cannot_rescue_invalid_requirements(malformed):
    quote = "A complete sentence has a subject and a predicate."
    decision = supported_source_decision(quote)
    decision["citations"] = [{"index": 0, "quote": quote}]
    requirements = decision["requirements"]
    if malformed == "missing":
        del decision["requirements"]
    elif malformed == "unknown":
        requirements["unknown"] = {"outcome": "not_applicable", "citations": []}
    elif malformed == "incomplete":
        del requirements["asserted_answer_claim"]
    else:
        requirements["source_supported_requirement"] = {
            "outcome": "not_applicable",
            "citations": [],
        }

    source = {"ref": {}, "text": quote, "quote": quote}
    with pytest.raises(semantic.AssessmentUnavailable):
        semantic._support_contract(leaf(), [source], decision)


@pytest.mark.parametrize("code", [None, "", "unknown code", {}, 42])
def test_unrecognized_refusal_code_keeps_the_generic_error(code):
    with pytest.raises(semantic.AssessmentUnavailable) as failure:
        semantic._support_contract(leaf(), [], {"supported": False, "reason_code": code})
    assert str(failure.value) == (
        "The selected source does not support this exact question and answer key."
    )
