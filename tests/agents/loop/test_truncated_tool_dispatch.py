"""A tool call cut off by the output limit must not run."""

from __future__ import annotations

import pytest

from deeptutor.agents.loop.loop_host import AgentLoopHost
from deeptutor.agents.loop.loop_state import AgentLoopState, LLMCallResult
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome

_CUT_OFF = '{"note": "Calculus/Week 7", "content": "## Integration\\n- take u'


class _Stream:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, object]] = []

    async def progress(self, message: str, **_kwargs: object) -> None:
        self.events.append(("progress", message, None))

    async def tool_call(self, tool_name: str, args: dict, **_kwargs: object) -> None:
        self.events.append(("tool_call", tool_name, args))

    async def tool_result(self, tool_name: str, result: str, **_kwargs: object) -> None:
        self.events.append(("tool_result", tool_name, result))


class _Pipeline:
    loop_max_tokens = 100
    dispatched: list[list[dict]]

    def __init__(self) -> None:
        self.dispatched = []

    def _t(self, _key: str, default: str = "") -> str:
        return default

    def _capability_tool_round_output_policy(self, _context, _text: str, _names: tuple) -> str:
        return ""

    async def _dispatch_tool_calls(self, **kwargs: object) -> DispatchOutcome:
        self.dispatched.append(list(kwargs["tool_calls"]))  # type: ignore[arg-type]
        return DispatchOutcome(
            tool_messages=[
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "obsidian_append",
                    "content": '{"status": "appended"}',
                }
            ]
        )


class _Loop:
    source = "chat"
    stage = "exploring"
    context = None

    def __init__(self, pipeline: _Pipeline, stream: _Stream) -> None:
        self.pipeline = pipeline
        self.stream = stream
        self._transient_model_messages: list[dict] = []

    def _clean(self, text: str) -> str:
        return text

    async def _release_deferred_output(self, _result: LLMCallResult) -> None:
        return None

    async def _discard_deferred_output(self, _result: LLMCallResult) -> None:
        return None


def _host(finish_reason: str) -> tuple[AgentLoopHost, _Pipeline, _Stream]:
    pipeline = _Pipeline()
    stream = _Stream()
    loop = _Loop(pipeline, stream)
    host = AgentLoopHost(loop, [], AgentLoopState(), 0)  # type: ignore[arg-type]
    host.result = LLMCallResult(
        text="Appending the note.",
        visible_text="Appending the note.",
        finish_reason=finish_reason,
        tool_calls=[
            {
                "id": "call_1",
                "name": "obsidian_append",
                "arguments": _CUT_OFF,
            }
        ],
    )
    return host, pipeline, stream


@pytest.mark.asyncio
async def test_truncated_tool_call_is_not_executed() -> None:
    host, pipeline, stream = _host("length")

    outcome = await host.dispatch_tools()

    assert outcome == {"pause": False}
    assert pipeline.dispatched == []
    assert host.dispatch is not None
    assert host.dispatch.tool_messages == [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "obsidian_append",
            "content": (
                "Model output was truncated. No tools in this batch were executed; "
                "retry with complete arguments."
            ),
        }
    ]
    assert [message["role"] for message in host.messages] == ["assistant", "tool"]
    assert host.messages[0]["tool_calls"][0]["function"]["arguments"] == _CUT_OFF
    assert stream.events[0][0] == "progress"
    assert "not executed" in str(stream.events[0][1])
    assert stream.events[1] == ("tool_call", "obsidian_append", {"arguments": _CUT_OFF})
    assert stream.events[2][0] == "tool_result"
    assert "were executed" in str(stream.events[2][2])


@pytest.mark.asyncio
async def test_complete_tool_call_still_dispatches() -> None:
    host, pipeline, _stream = _host("stop")

    outcome = await host.dispatch_tools()

    assert outcome == {"pause": False}
    assert pipeline.dispatched == [host.result.tool_calls]  # type: ignore[union-attr]
    assert host.dispatch is not None
    assert host.dispatch.tool_messages[0]["content"] == '{"status": "appended"}'
