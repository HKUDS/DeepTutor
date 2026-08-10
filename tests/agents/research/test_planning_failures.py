from __future__ import annotations

import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deeptutor.agents.research.pipeline import ResearchPipeline
from deeptutor.agents.research.recovery import ResearchTerminalError, verify_checkpoint
from deeptutor.core.agentic import AgenticModelError
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus


class _Registry:
    def build_openai_schemas(self, _names):
        return []

    def build_prompt_text(self, _names, **_kwargs):
        return "- none"

    def get(self, _name):
        return None

    def get_enabled(self, _names):
        return []


def _pipeline() -> ResearchPipeline:
    config = SimpleNamespace(
        binding="openai", model="gpt-x", api_key="k", base_url="u",
        api_version=None, extra_headers={}, reasoning_effort=None,
        api_protocol="openai_responses", resolved_api_protocol="openai_responses",
        strict_protocol=True,
    )
    with (
        patch("deeptutor.agents.research.pipeline.get_llm_config", lambda: config),
        patch("deeptutor.agents.research.pipeline.get_tool_registry", lambda: _Registry()),
    ):
        return ResearchPipeline(language="en", runtime_config={"queue": {"max_length": 5}})


@pytest.mark.parametrize(
    "phase,code,termination",
    [
        (
            "rephrasing", "model_output_incomplete",
            {"provider_status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        ),
        ("decomposing", "research_planning_failed", {"provider_status": "completed"}),
        ("decomposing", "model_output_empty", {"provider_status": "completed"}),
    ],
)
@pytest.mark.asyncio
async def test_typed_planning_failure_emits_failed_result_and_zero_block_checkpoint(
    phase: str, code: str, termination: dict
) -> None:
    pipeline = _pipeline()
    pipeline.rephrase_enabled = True
    stream = StreamBus()
    context = UnifiedContext(session_id="s1", user_message="topic")
    error = AgenticModelError(
        code, "Safe planning failure.", retryable=code == "model_output_incomplete",
        normalized_result={"content": "", "tool_calls": [], "termination": termination},
    )

    async def rephrase(self, **_kwargs):
        if phase == "rephrasing":
            raise error
        return "refined topic"

    async def decompose(self, **_kwargs):
        raise error

    pipeline._rephrase = types.MethodType(rephrase, pipeline)
    pipeline._decompose = types.MethodType(decompose, pipeline)

    with pytest.raises(ResearchTerminalError) as excinfo:
        await pipeline._run_inner(
            context=context, topic="topic", image_attachments=[],
            confirmed_outline=None, stream=stream, client=object(),
        )

    results = [event for event in stream._history if event.type == StreamEventType.RESULT]
    assert len(results) == 1
    outcome = results[0].metadata["metadata"]
    assert outcome["outcome"] == "failed"
    assert outcome["failure"] == {
        "code": code, "stage": phase, "summary": "Safe planning failure.",
        "retryable": code == "model_output_incomplete", "termination": termination,
        "retry_strategy": "full_research",
    }
    checkpoint = excinfo.value.checkpoint
    assert verify_checkpoint(checkpoint)
    assert checkpoint["blocks"] == []
    assert checkpoint["input"]["confirmed_outline"] == []
    assert checkpoint["strategy"] == "full_research"
    assert context.metadata["_research_attempt_checkpoint"] == checkpoint


@pytest.mark.asyncio
async def test_unexpected_planning_failure_uses_safe_public_surface() -> None:
    pipeline = _pipeline()
    pipeline.rephrase_enabled = True
    stream = StreamBus()

    async def fail_with_secret(self, **_kwargs):
        raise RuntimeError("https://secret.invalid bearer-SECRET")

    pipeline._rephrase = types.MethodType(fail_with_secret, pipeline)
    pipeline._build_client = types.MethodType(lambda self: object(), pipeline)

    with pytest.raises(RuntimeError):
        await pipeline.run(
            context=UnifiedContext(session_id="s1", user_message="topic"),
            topic="topic", confirmed_outline=None, attachments=[], stream=stream,
        )

    public_events = repr([event.to_dict() for event in stream._history])
    assert "secret.invalid" not in public_events
    assert "bearer-SECRET" not in public_events
    assert "Research could not be completed." in public_events
