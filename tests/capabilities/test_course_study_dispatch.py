"""The hand-off's trip through the real dispatcher.

Everything else about Course Study is tested against the tools directly. This
file covers the one seam those tests cannot see: what the *frontend* actually
receives. A tool's own ``ToolResult.metadata`` does not arrive at the top level
of a stream event — the dispatcher nests it under ``tool_metadata`` — and the
card reader in ``web/lib/course-handoff.ts`` reads exactly that path. Reading
the top level instead type-checks fine and silently finds nothing, which is why
the contract is pinned here rather than trusted.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.course_study import CourseStudyLoopCapability
from deeptutor.capabilities.course_study.capability import COURSE_ID_KEY
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus

COURSE_ID = "course-1"

#: Every key `CourseHandoffPayload` in `web/lib/course-handoff.ts` reads.
FRONTEND_CONTRACT = ("target", "prompt", "reason", "ref_id", "label", "course_id")


def _stub_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the pipeline construct without a configured model.

    Only ``_augment_tool_kwargs`` is exercised here, but it is reached through
    the real pipeline instance so the augmentation path under test is the one
    production uses. Constructing that instance reads the LLM config, which a
    checkout has no reason to carry.
    """
    import deeptutor.agents.loop.pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "get_llm_config",
        lambda *args, **kwargs: SimpleNamespace(
            binding="openai", model="stub", api_key="stub", base_url=""
        ),
    )


def _bind_course(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services import courses

    course = SimpleNamespace(
        resources=[SimpleNamespace(id="res_1", ref_id="path-1", label="Virtual memory path")]
    )
    monkeypatch.setattr(
        courses, "get_course_service", lambda: SimpleNamespace(get=lambda _: course)
    )


def _capture(stream: StreamBus) -> list[Any]:
    seen: list[Any] = []
    original = stream.emit

    async def emit(event: Any) -> None:
        seen.append(event)
        await original(event)

    stream.emit = emit  # type: ignore[method-assign]
    return seen


def _handoff_payloads(events: list[Any]) -> list[dict[str, Any]]:
    """Read the hand-off exactly where the browser reads it."""
    payloads = []
    for event in events:
        metadata = getattr(event, "metadata", None) or {}
        nested = metadata.get("tool_metadata")
        if isinstance(nested, dict) and "course_handoff" in nested:
            payloads.append(nested["course_handoff"])
    return payloads


@pytest.mark.asyncio
async def test_handoff_reaches_the_browser_where_the_card_reader_looks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls

    _stub_llm_config(monkeypatch)
    _bind_course(monkeypatch)
    context = UnifiedContext(
        user_message="what should I do next",
        session_id="session-1",
        metadata={COURSE_ID_KEY: COURSE_ID, "turn_id": "turn-1"},
    )
    context.active_capability = "course_study"
    capability = CourseStudyLoopCapability()
    assert capability.is_active(context), "gate must hold, or nothing below is exercised"

    stream = StreamBus()
    events = _capture(stream)
    pipeline = AgenticChatPipeline(language="en")

    await dispatch_tool_calls(
        tool_calls=[
            {
                "id": "c1",
                "name": "course_handoff",
                # The model never writes the course id: it is server-owned and
                # injected by the capability's kwarg augmenter.
                "arguments": json.dumps(
                    {
                        "target": "mastery_path",
                        "prompt": "Pick up at multi-level page tables.",
                        "reason": "Your wrong answers cluster on address translation.",
                        "ref_id": "res_1",
                    }
                ),
            }
        ],
        context=context,
        stream=stream,
        source="chat",
        stage="responding",
        iteration_index=0,
        kwarg_augmenter=pipeline._augment_tool_kwargs,
    )

    payloads = _handoff_payloads(events)
    assert len(payloads) == 1, "the card reader would find nothing"
    payload = payloads[0]
    assert tuple(payload) == FRONTEND_CONTRACT
    assert payload["course_id"] == COURSE_ID, "augment_kwargs did not bind the course"
    # The summary lists resources by resource_id; the router needs the ref_id.
    assert payload["ref_id"] == "path-1"
    assert payload["label"] == "Virtual memory path"
    assert payload["target"] == "mastery_path"


@pytest.mark.asyncio
async def test_handoff_is_refused_when_the_turn_has_no_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a bound course the tool must not invent one.

    The dispatcher swallows tool errors into an error result rather than
    raising, so what matters is that no hand-off payload reaches the stream —
    a card pointing into a course that was never opened is worse than none.
    """
    from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls

    _stub_llm_config(monkeypatch)
    _bind_course(monkeypatch)
    context = UnifiedContext(user_message="what next", session_id="session-1")
    context.active_capability = "course_study"
    stream = StreamBus()
    events = _capture(stream)
    pipeline = AgenticChatPipeline(language="en")

    await dispatch_tool_calls(
        tool_calls=[
            {
                "id": "c1",
                "name": "course_handoff",
                "arguments": json.dumps({"target": "chat", "prompt": "hi", "reason": "because"}),
            }
        ],
        context=context,
        stream=stream,
        source="chat",
        stage="responding",
        iteration_index=0,
        kwarg_augmenter=pipeline._augment_tool_kwargs,
    )

    assert _handoff_payloads(events) == []
