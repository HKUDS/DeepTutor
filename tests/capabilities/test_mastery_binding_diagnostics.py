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

pytest_plugins = ["tests.capabilities.test_mastery_question_groups"]

SECRET_KEY = "SYNTHETIC_PRIVATE_ANSWER"
GENERIC_ERROR = "The selected source does not support this exact question and answer key."


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
            {"supported": True, "citations": [], "reason_code": "incorrect_key"},
            "No supporting citations were returned. Provide a verifiable citation from the selected source.",
        ),
    ],
    ids=["known-code", "arbitrary-code", "malformed-code", "legacy", "missing-citations"],
)
async def test_failed_quiz_dispatch_only_relays_safe_binding_diagnostics(
    service, monkeypatch, decision, expected_hint
):
    progress = service.store.load("p")
    progress.lesson_evidence["kp1"] = {"sources": [{"ref": {}, "text": "Synthetic source."}]}
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
