"""A visualize turn must explain a provider that cannot commit a canvas.

The canvas is only ever committed through the ``submit_visualization`` tool
call, so a provider that is handed no tool schemas can generate perfect HTML
and still render nothing. Local OpenAI-compatible servers (LM Studio, Ollama,
vLLM, llama.cpp) are opted out of native tools by default, and that used to
surface as a bare "no valid canvas payload" error after a full five-round loop
— with no hint that the fix is one Settings toggle away.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import deeptutor.agents.chat.agentic_pipeline as chat_pipeline
from deeptutor.agents.visualize.capability import VisualizeCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.llm.capabilities import set_catalog_capability_overrides
import deeptutor.services.llm.config as llm_config_module

_LOCAL_BINDING = "lm_studio"
_LOCAL_MODEL = "deepseek-r1-distill-qwen-32b"


class _PipelineWithoutSubmission:
    """A loop that answers in prose — i.e. never calls submit_visualization."""

    def __init__(self, **kwargs: Any) -> None:
        _ = kwargs
        self.usage = None

    async def run(self, context: UnifiedContext, stream: StreamBus) -> dict[str, Any]:
        _ = (context, stream)
        return {"completed": True, "rounds": 1}


async def _run_visualize(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[StreamEvent], str]:
    """Run one visualize turn whose loop commits nothing.

    Returns the streamed events and the resulting error message, so a test can
    assert on both the up-front warning and the final diagnosis.
    """
    monkeypatch.setattr(chat_pipeline, "AgenticChatPipeline", _PipelineWithoutSubmission)
    context = UnifiedContext(
        user_message="visualize a binary search",
        active_capability="visualize",
        config_overrides={"render_mode": "html"},
        language="en",
    )

    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError) as excinfo:
        await VisualizeCapability().run(context, bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer
    return events, str(excinfo.value)


def _warnings(events: list[StreamEvent]) -> list[str]:
    return [
        str(event.content)
        for event in events
        if (event.metadata or {}).get("trace_kind") == "warning"
    ]


def _use_llm_config(monkeypatch: pytest.MonkeyPatch, binding: str, model: str) -> None:
    monkeypatch.setattr(
        llm_config_module,
        "get_llm_config",
        lambda *args, **kwargs: SimpleNamespace(binding=binding, model=model),
    )


@pytest.mark.asyncio
async def test_local_provider_is_warned_up_front_and_diagnosed_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LM Studio gets no tool schemas, so say so before and after the loop."""
    _use_llm_config(monkeypatch, _LOCAL_BINDING, _LOCAL_MODEL)

    events, error = await _run_visualize(monkeypatch)

    warning = "".join(_warnings(events))
    assert "Tool calling is disabled" in warning
    assert f"{_LOCAL_BINDING}/{_LOCAL_MODEL}" in warning
    # The warning must be actionable, not merely descriptive: it names the tool
    # that commits the canvas and the exact setting that enables it.
    assert "submit_visualization" in warning
    assert "Tool calling → Supported" in warning

    assert f"{_LOCAL_BINDING}/{_LOCAL_MODEL}" in error
    assert "submit_visualization" in error
    assert "LM Studio" in error
    assert "Tool calling → Supported" in error


@pytest.mark.asyncio
async def test_tool_capable_provider_keeps_the_generic_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With tools attached, a missing payload is the model's own doing."""
    _use_llm_config(monkeypatch, "openai", "gpt-4o")

    events, error = await _run_visualize(monkeypatch)

    assert _warnings(events) == []
    assert error == "The visualization agent finished without a valid canvas payload."


@pytest.mark.asyncio
async def test_declaring_tool_support_clears_the_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Settings override is the documented fix, so it must take effect.

    A user who declares the local model tool-capable should stop being told to
    declare it — the same resolution order the chat loop uses.
    """
    _use_llm_config(monkeypatch, _LOCAL_BINDING, _LOCAL_MODEL)
    set_catalog_capability_overrides([(_LOCAL_BINDING, _LOCAL_MODEL, {"tools": True})])
    try:
        events, error = await _run_visualize(monkeypatch)
    finally:
        set_catalog_capability_overrides([])

    assert _warnings(events) == []
    assert error == "The visualization agent finished without a valid canvas payload."


@pytest.mark.asyncio
async def test_probe_failure_leaves_the_turn_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probing is a diagnosis aid; it must never be why a turn fails."""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no LLM configured")

    monkeypatch.setattr(llm_config_module, "get_llm_config", _boom)

    events, error = await _run_visualize(monkeypatch)

    assert _warnings(events) == []
    assert error == "The visualization agent finished without a valid canvas payload."
