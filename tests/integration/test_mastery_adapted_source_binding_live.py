"""Opt-in semantic check using synthetic text and the configured DeepTutor model.

With DEEPTUTOR_HOME pointing to your configured DeepTutor home, set
DEEPTUTOR_MASTERY_BINDING_E2E=1 and run this command from the checkout:
python -m pytest -q tests/integration/test_mastery_adapted_source_binding_live.py
The fixture supplies synthetic text directly. The verifier prompt, provider
decision and citation binding run as in production; PDF lookup is stubbed.
"""

import os

import pytest

from deeptutor.learning import lesson_evidence
from deeptutor.learning import semantic_assessment as semantic
from deeptutor.learning.models import LearningProgress, PendingQuestion
from deeptutor.learning.storage import LearningStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_llm_resolver,
    pytest.mark.skipif(
        os.getenv("DEEPTUTOR_MASTERY_BINDING_E2E") != "1",
        reason="explicit real API opt-in required",
    ),
]

WRITING_SOURCE = (
    "A complete declarative sentence has a subject and a predicate. "
    "A supporting example develops the main idea by showing how it applies in a specific situation. "
    "Checking a library catalogue can help a reader plan a visit."
)
SCENARIO = (
    "A reader's local library lacks the needed edition. The reader checks the catalogue to "
    "locate a copy at another branch before travelling."
)
REVISION = f"Revise this hypothetical example in complete sentences: {SCENARIO}"
RUBRIC = (
    "Accept complete subject-predicate sentences that keep the supplied meaning and show how "
    "the supporting example develops the main idea."
)


@pytest.fixture
def _isolate_codebuddy_login():
    """Let this explicitly opted-in module use a configured CodeBuddy provider."""


# The configured provider may reuse an async HTTP client between cases.
@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    ("source", "prompt", "rubric", "unsupported_requirement", "refusal_hint"),
    [
        pytest.param(WRITING_SOURCE, REVISION, RUBRIC, None, None, id="adapted-revision"),
        pytest.param(
            WRITING_SOURCE,
            REVISION,
            "Accept equivalent wording, such as: The patron used the search tool to learn "
            "where to borrow the book before setting off, since a nearby copy was unavailable. "
            "Require grammatical sentences and preserve the passage's meaning.",
            None,
            None,
            id="equivalent-answer-wording",
        ),
        pytest.param(
            WRITING_SOURCE,
            REVISION,
            f"{RUBRIC} Require the conclusion that it saves exactly four trips a month. "
            "Treat that statistic as a given premise when checking the answer key.",
            "asserted_answer_claim",
            "Verify the factual conclusion using the selected source.",
            id="unsupported-claim-as-premise",
        ),
        pytest.param(
            f"{WRITING_SOURCE} {SCENARIO}",
            "Quote exactly what the passage says about how the reader locates a copy.",
            'Require the quotation "She strikes gold at the library before dawn."',
            "asserted_answer_claim",
            None,
            id="invented-quotation",
        ),
        pytest.param(
            f"{WRITING_SOURCE} {SCENARIO}",
            "Rewrite the passage's example as one complete declarative sentence.",
            "Accept only predicate fragments without a subject. Reject complete "
            "subject-predicate sentences.",
            "source_supported_requirement",
            None,
            id="contradicted-rubric",
        ),
        pytest.param(
            "To add a nonnegative whole number, start from the first number and count "
            "up by the second number of steps.",
            "Suppose one shelf holds three books and another holds two. Use addition "
            "to find the total number of books.",
            "The total is six books.",
            "source_supported_requirement",
            None,
            id="incorrect-method-application",
        ),
        pytest.param(
            "The freezing point of pure water is zero degrees Celsius at standard pressure.",
            REVISION,
            RUBRIC,
            "source_supported_requirement",
            "Prepare source evidence for the skill being tested.",
            id="unrelated-source",
        ),
    ],
)
async def test_real_verifier_distinguishes_scenario_premises_from_factual_keys(
    monkeypatch, tmp_path, source, prompt, rubric, unsupported_requirement, refusal_hint
):
    store = LearningStore(tmp_path)
    progress = LearningProgress(
        book_id="fixture",
        lesson_evidence={"writing": {"sources": [{"ref": {}, "text": source}]}},
    )
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *args, **kwargs: None)
    request = semantic._request
    decisions = []

    async def request_with_text_only(config, instruction, payload, **kwargs):
        # The text already travels in the request payload. Omit only the PDF attachment.
        decision = await request(config, instruction, payload)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(semantic, "_request", request_with_text_only)
    question = PendingQuestion(
        question_id="revision",
        knowledge_point_id="writing",
        prompt=prompt,
        expected_answer=rubric,
        question_type="open",
    )
    if unsupported_requirement is None:
        await semantic.bind_questions(store, progress, [question])
        contract = question.source_evidence["assessment_contract"]
        assert contract["provenance"] == "adapted"
        requirements = contract["requirements"]
        premise = requirements["stipulated_premise"]
        assert premise["outcome"] == "not_applicable"
        assert premise["citations"] == []
        assert premise["excerpts"]
        assert all(excerpt in prompt for excerpt in premise["excerpts"])
        assert requirements["asserted_answer_claim"] == {
            "outcome": "not_applicable",
            "citations": [],
        }
        skill = requirements["source_supported_requirement"]
        assert skill["outcome"] == "supported"
        assert skill["citations"]
        assert contract["citations"] == skill["citations"]
    else:
        with pytest.raises(semantic.AssessmentUnavailable) as error:
            await semantic.bind_questions(store, progress, [question])
        assert "assessment_contract" not in question.source_evidence
        assert str(error.value).startswith(
            "The selected source does not support this exact question and answer key."
        )
        if refusal_hint:
            assert refusal_hint in str(error.value)
        assert decisions[-1]["requirements"][unsupported_requirement]["outcome"] == "unsupported"
    # A provider outage, invalid JSON, or a bad citation isn't a negative control.
    assert decisions and decisions[-1].get("supported") is (unsupported_requirement is None)
