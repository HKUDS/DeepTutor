"""Failed quiz diagnostics must keep hidden answers out of trace and model messages."""

import json

import pytest

from deeptutor.capabilities.mastery import tools
from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.learning import lesson_evidence
from deeptutor.learning import semantic_assessment as semantic
from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.runtime.stream_bus import StreamBus
from tests.capabilities.test_mastery_adapted_source_binding import supported_source_decision

pytest_plugins = ["tests.capabilities.test_mastery_question_groups"]

SECRET_KEY = "SYNTHETIC_PRIVATE_ANSWER"
GENERIC_ERROR = "The selected source does not support this exact question and answer key."
SOURCE = "Synthetic source."


def unverified_requirement(requirement, *, missing_citations=False, reason_code=None):
    decision = supported_source_decision(SOURCE)
    decision["requirements"][requirement] = {
        "outcome": "supported" if missing_citations else "unsupported",
        "citations": [],
        "reason": SECRET_KEY,
        "reason_code": reason_code,
    }
    return decision


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected_hint"),
    [
        (
            {"supported": False, "reason_code": "incorrect_key"},
            "Check the proposed answer key against the selected source.",
        ),
        ({"supported": False, "reason_code": SECRET_KEY}, GENERIC_ERROR),
        ({"supported": False, "reason_code": {"text": SECRET_KEY}}, GENERIC_ERROR),
        ({"supported": False}, GENERIC_ERROR),
        (
            unverified_requirement("source_supported_requirement", missing_citations=True),
            "Provide a verifiable citation",
        ),
        (
            unverified_requirement("source_supported_requirement"),
            "Prepare source evidence for the skill being tested.",
        ),
        (
            unverified_requirement(
                "source_supported_requirement", reason_code="unsupported_rubric"
            ),
            "Check the grading requirements against the selected source.",
        ),
        (
            unverified_requirement("source_supported_requirement", reason_code="incorrect_key"),
            "Check the proposed answer key against the selected source.",
        ),
        (
            unverified_requirement("source_supported_requirement", reason_code=SECRET_KEY),
            "Prepare source evidence for the skill being tested.",
        ),
        (
            unverified_requirement("asserted_answer_claim"),
            "Verify the factual conclusion using the selected source.",
        ),
    ],
    ids=[
        "known-code",
        "arbitrary-code",
        "malformed-code",
        "legacy",
        "missing-citations",
        "missing-skill-evidence",
        "unsupported-rubric",
        "incorrect-key",
        "unrecognized-row-code",
        "unsupported-answer-claim",
    ],
)
async def test_failed_quiz_dispatch_only_relays_safe_binding_diagnostics(
    service, monkeypatch, decision, expected_hint
):
    progress = service.store.load("p")
    progress.lesson_evidence["kp1"] = {"sources": [{"ref": {}, "text": SOURCE}]}
    service.save(progress)
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    monkeypatch.setattr(lesson_evidence, "validate_evidence", lambda *args, **kwargs: None)

    async def verify(_config, _instruction, payload, **kwargs):
        assert payload["question"]["expected_answer"] == SECRET_KEY
        return {**decision, "reason": f"The correct answer is {SECRET_KEY}."}

    monkeypatch.setattr(semantic, "_request", verify)
    registry = ToolRegistry()
    registry.register(tools.MasteryQuizTool())
    bus = StreamBus()
    outcome = await dispatch_tool_calls(
        tool_calls=[
            {
                "id": "quiz",
                "name": "mastery_quiz",
                "arguments": json.dumps(
                    {
                        "knowledge_point_id": "kp1",
                        "question": "Synthetic question?",
                        "expected_answer": SECRET_KEY,
                    }
                ),
            }
        ],
        context=UnifiedContext(
            session_id="synthetic",
            metadata={
                "mastery_mode": True,
                "mastery_path_id": "p",
                "mastery_session_mode": "study",
            },
        ),
        stream=bus,
        source="mastery_path",
        stage="responding",
        iteration_index=0,
        registry=registry,
        kwarg_augmenter=MasteryLoopCapability().augment_kwargs,
    )
    await bus.close()
    events = [event.to_dict() async for event in bus.subscribe()]
    assert any(event["type"] == "tool_result" for event in events)
    assert SECRET_KEY not in json.dumps(events)
    assert SECRET_KEY not in json.dumps(outcome.tool_messages + outcome.model_messages)
    assert expected_hint in outcome.tool_messages[0]["content"]
    assert service.store.get_active_interaction("p") is None
