"""Source preparation must actually run at the native model-request boundary."""

import json

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.agents.loop import agent_loop as loop_module
from deeptutor.core.capability_protocol import CapabilityPrerequisiteError
from deeptutor.core.context import UnifiedContext
from deeptutor.learning.lesson_evidence import LessonUnavailable
from deeptutor.services.session.model_history import normalize_model_turn
from tests.agents.chat.test_agent_loop import _isolated_runtime as _isolated_runtime
from tests.agents.chat.test_agent_loop import _llm_chunk, _Registry, _run, _ScriptedChatClient


def pixels(label):
    return {
        "role": "user",
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + label}}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("forced_finish", [False, True])
async def test_native_boundary_refreshes_each_round_and_keeps_tool_pixels_ephemeral(
    monkeypatch, forced_finish
):
    class Registry(_Registry):
        async def execute(self, name, **kwargs):
            result = await super().execute(name, **kwargs)
            result.model_message = pixels("fresh-tool-image")
            return result

    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(
                    tool_calls=[
                        {"id": "inspect", "name": "web_search", "arguments": '{"query":"figure"}'}
                    ]
                )
            ],
            [_llm_chunk(content="A supported explanation.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = Registry()
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
    if forced_finish:
        pipeline._max_rounds = 1
        monkeypatch.setattr(loop_module, "MAX_SETTLEMENT_ROUNDS", 0)
    checks = []

    async def prepare(context, stream, messages):
        checks.append(True)
        messages[:] = [m for m in messages if not m.get("_lesson_packet")]
        messages.append(
            {"role": "user", "content": "current authorized source packet", "_lesson_packet": True}
        )
        return [pixels("cached-page-image")]

    monkeypatch.setattr(pipeline, "prepare_model_request", prepare, raising=False)
    context = UnifiedContext(session_id="synthetic-source", user_message="Inspect the figure")
    await _run(pipeline, context)
    assert len(checks) == client.call_count == 2
    assert "cached-page-image" in json.dumps(client.calls[0]["messages"])
    assert "fresh-tool-image" in json.dumps(client.calls[1]["messages"])
    assert "cached-page-image" not in json.dumps(client.calls[1]["messages"])
    assert all("_lesson_packet" not in m for call in client.calls for m in call["messages"])
    assert "base64" not in json.dumps(context.runtime.model_turn)
    messages = client.calls[1]["messages"]
    call_index = next(i for i, m in enumerate(messages) if m.get("tool_calls"))
    assert messages[call_index + 1]["tool_call_id"] == "inspect"
    assert ("tools" not in client.calls[1]) is forced_finish


@pytest.mark.asyncio
@pytest.mark.parametrize("forced_finish", [False, True])
@pytest.mark.parametrize("error_type", [LessonUnavailable, CapabilityPrerequisiteError])
async def test_source_check_failure_cannot_be_bypassed_by_finishing(
    monkeypatch, forced_finish, error_type
):
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(
                    tool_calls=[
                        {"id": "change", "name": "web_search", "arguments": '{"query":"change"}'}
                    ]
                )
            ],
            [_llm_chunk(content="Must not run.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
    if forced_finish:
        pipeline._max_rounds = 1
        monkeypatch.setattr(loop_module, "MAX_SETTLEMENT_ROUNDS", 0)
    checks = []

    async def prepare(context, stream, messages):
        checks.append(True)
        if len(checks) > 1:
            raise error_type("Selected source access changed")
        return []

    monkeypatch.setattr(pipeline, "prepare_model_request", prepare, raising=False)
    with pytest.raises(error_type):
        await _run(pipeline, UnifiedContext(user_message="Teach"))
    assert client.call_count == 1


def test_durable_packet_marker_survives_normalization_for_later_refresh():
    record = normalize_model_turn(
        {
            "version": 1,
            "messages": [
                {"role": "user", "content": "Teach"},
                {"role": "user", "content": "old source packet", "_lesson_packet": True},
                {"role": "assistant", "content": "Explanation"},
            ],
        }
    )
    assert record["messages"][1]["_lesson_packet"] is True
