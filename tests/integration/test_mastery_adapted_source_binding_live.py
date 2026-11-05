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

SOURCE = (
    "A complete declarative sentence has a subject and a predicate. "
    "A supporting example develops the main idea by showing how it applies in a specific situation. "
    "Checking a library catalogue can help a reader plan a visit."
)
CASES = [
    (
        "adapted-revision",
        "Revise this given example in complete sentences: a reader's local library lacks the "
        "needed edition. The reader checks the catalogue to locate a copy at another branch "
        "before travelling. Keep the meaning and show how the catalogue avoids a wasted trip.",
        "Accept complete subject-predicate sentences that preserve the missing local edition "
        "and explain how finding the right branch before setting out supports the main idea.",
        True,
    ),
    (
        "unsupported-statistic",
        "According to the passage, how many wasted trips per month does checking a catalogue save?",
        "Checking a catalogue saves exactly four trips per month.",
        False,
    ),
    (
        "contradicted-key",
        "What two parts does the passage say a complete declarative sentence needs?",
        "It only needs a predicate; it never needs a subject.",
        False,
    ),
]


@pytest.mark.asyncio
async def test_real_verifier_distinguishes_scenario_premises_from_factual_keys(
    monkeypatch, tmp_path
):
    store = LearningStore(tmp_path)
    progress = LearningProgress(
        book_id="fixture",
        lesson_evidence={"writing": {"sources": [{"ref": {}, "text": SOURCE}]}},
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
    for case, prompt, rubric, supported in CASES:
        question = PendingQuestion(
            question_id=case,
            knowledge_point_id="writing",
            prompt=prompt,
            expected_answer=rubric,
            question_type="open",
        )
        decisions.clear()
        if supported:
            await semantic.bind_questions(store, progress, [question])
            contract = question.source_evidence["assessment_contract"]
            assert contract["provenance"] == "adapted"
            assert contract["citations"]
        else:
            with pytest.raises(semantic.AssessmentUnavailable):
                await semantic.bind_questions(store, progress, [question])
            assert "assessment_contract" not in question.source_evidence
        # A provider outage, invalid JSON, or a bad citation isn't a negative control.
        assert decisions and decisions[-1].get("supported") is supported, case
