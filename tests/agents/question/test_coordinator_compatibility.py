from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.agents.question.coordinator import AgentCoordinator


@pytest.mark.asyncio
async def test_legacy_websocket_arguments_reach_question_pipeline(monkeypatch):
    coordinator = AgentCoordinator(language="en")
    pipeline = SimpleNamespace(run=AsyncMock(return_value={"summary": {"completed": 2}}))
    monkeypatch.setattr(coordinator, "_build_pipeline", lambda: pipeline)
    result = await coordinator.generate_from_topic(
        user_topic="Fractions",
        preference="Use everyday examples",
        question_type="multiple_choice",
        num_questions=2,
        difficulty="medium",
    )
    sent = pipeline.run.call_args.kwargs
    assert sent["question_types"] == ["multiple_choice"]
    assert sent["num_questions"] == 2
    assert sent["difficulty"] == "medium"
    assert "Use everyday examples" in sent["context"].user_message
    assert sent["context"].user_message == sent["user_message"]
    assert result["completed"] == 2
