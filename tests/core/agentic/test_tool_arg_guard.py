"""Required-argument guard in front of tool dispatch (issue #779).

Under a large tool surface and long history, providers intermittently emit a
function call whose ``arguments`` is ``{}`` even though the schema marks
fields required. The tool used to be the one to reject it — ``exec`` raised
``exec requires a non-empty command``, ``write_note`` answered ``Unknown mode
''`` — neither of which reads as "an argument is missing", so the model
re-emitted the same empty call until the loop budget ran out.

Two things are pinned here: the guard's rules (what counts as missing, and
what must NOT be treated as missing so working calls keep working), and that
dispatch short-circuits without touching the tool.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.tool_protocol import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolResult,
)
from deeptutor.runtime.agentic.tool_arg_guard import (
    missing_args_message,
    missing_required_args,
    required_args,
    unsatisfied_required_args,
)
from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.runtime.stream_bus import StreamBus


def _write_note_definition() -> ToolDefinition:
    """``write_note``'s shape, reduced to what the guard reads."""
    return ToolDefinition(
        name="write_note",
        description="Save or edit a notebook record.",
        parameters=[
            ToolParameter(name="mode", type="string", enum=["append", "edit"]),
            ToolParameter(name="notebook_id", type="string"),
            ToolParameter(name="title", type="string", required=False),
        ],
    )


def test_empty_arguments_report_every_required_param() -> None:
    missing = missing_required_args(_write_note_definition(), {})
    assert [arg.name for arg in missing] == ["mode", "notebook_id"]


def test_optional_params_are_never_reported() -> None:
    definition = _write_note_definition()
    missing = missing_required_args(definition, {"mode": "append", "notebook_id": "nb1"})
    assert missing == []


def test_required_param_with_a_default_is_satisfiable_without_the_model() -> None:
    """A default means the tool can serve the call, so rejecting it would
    refuse work that used to succeed."""
    definition = ToolDefinition(
        name="t",
        description="",
        parameters=[ToolParameter(name="limit", type="integer", default=10)],
    )
    assert required_args(definition) == []
    assert missing_required_args(definition, {}) == []


def test_blank_string_counts_as_missing() -> None:
    """How providers serialise "the model left this out" in practice —
    ``exec``'s empty ``command`` arrived this way."""
    definition = ToolDefinition(
        name="exec",
        description="",
        parameters=[ToolParameter(name="command", type="string")],
    )
    assert [arg.name for arg in missing_required_args(definition, {"command": "   "})] == [
        "command"
    ]


def test_present_blank_string_is_classified_separately_from_absent() -> None:
    """Thinking models sometimes pass ``""`` on purpose (#1101). The guard
    still rejects the call, but the corrective message must say the key was
    empty — not that it was omitted — or the model retries verbatim."""
    definition = ToolDefinition(
        name="obsidian_create_note",
        description="",
        parameters=[
            ToolParameter(name="path", type="string"),
            ToolParameter(name="content", type="string"),
        ],
    )
    absent, blank = unsatisfied_required_args(
        definition,
        {"path": "Hub.md", "content": ""},
    )
    assert [arg.name for arg in absent] == []
    assert [arg.name for arg in blank] == ["content"]

    message = missing_args_message("obsidian_create_note", absent, empty=blank)
    assert "received empty value(s)" in message
    assert "`content`" in message
    assert "present but blank" in message
    assert "without its required argument(s)" not in message


def test_mixed_absent_and_blank_args_are_both_named() -> None:
    definition = ToolDefinition(
        name="obsidian_create_note",
        description="",
        parameters=[
            ToolParameter(name="path", type="string"),
            ToolParameter(name="content", type="string"),
        ],
    )
    absent, blank = unsatisfied_required_args(definition, {"content": "   "})
    assert [arg.name for arg in absent] == ["path"]
    assert [arg.name for arg in blank] == ["content"]
    message = missing_args_message("obsidian_create_note", absent, empty=blank)
    assert "without its required argument(s): `path`" in message
    assert "received empty value(s) for required argument(s): `content`" in message


def test_empty_collections_are_left_alone() -> None:
    """``[]`` / ``{}`` can be a deliberate value for an array or object
    parameter; treating them as absent would reject valid calls."""
    definition = ToolDefinition(
        name="t",
        description="",
        parameters=[
            ToolParameter(name="items", type="array"),
            ToolParameter(name="spec", type="object"),
        ],
    )
    assert missing_required_args(definition, {"items": [], "spec": {}}) == []


def test_server_injected_argument_counts_as_supplied() -> None:
    """The guard runs on the *prepared* kwargs, so anything the pipeline
    injects on the model's behalf satisfies the schema."""
    definition = ToolDefinition(
        name="write_note",
        description="",
        parameters=[ToolParameter(name="conversation_history", type="string")],
    )
    assert missing_required_args(definition, {"conversation_history": "Q: hi"}) == []


def test_raw_json_schema_required_is_honoured() -> None:
    """MCP adapters carry verbatim JSON Schema rather than ToolParameter rows."""
    definition = ToolDefinition(
        name="mcp_fs_read",
        description="",
        raw_parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "encoding": {"type": "string", "default": "utf-8"},
                "mode": {"type": "string", "enum": ["text", "binary"]},
            },
            "required": ["path", "encoding", "mode"],
        },
    )
    # ``encoding`` declares a default, so only the other two are the model's job.
    assert [arg.name for arg in missing_required_args(definition, {})] == ["path", "mode"]


@pytest.mark.parametrize(
    ("property_schema", "accepts_null"),
    [
        ({"type": ["integer", "null"]}, True),
        ({"type": "null"}, True),
        ({"anyOf": [{"type": "integer"}, {"type": "null"}]}, True),
        ({"oneOf": [{"type": "integer"}, {"type": "null"}]}, True),
        ({"allOf": [{"type": ["integer", "null"]}, {"enum": [1, None]}]}, True),
        ({"enum": [1, None]}, True),
        ({"const": None}, True),
        ({}, True),
        (True, True),
        ({"type": "integer"}, False),
        ({"type": ["integer", "null"], "enum": [1]}, False),
        ({"allOf": [{"type": ["integer", "null"]}, {"not": {"type": "null"}}]}, False),
        ({"oneOf": [{}, {"type": "null"}]}, False),
        (False, False),
        ({"type": "invalid-schema-type"}, False),
        ({"$ref": "#/$defs/absent"}, False),
        ({"$ref": "https://example.invalid/schema.json"}, False),
    ],
)
def test_required_null_uses_schema_semantics_without_relaxing_omission(
    property_schema: Any,
    accepts_null: bool,
) -> None:
    definition = ToolDefinition(
        name="nullable_tool",
        description="",
        raw_parameters={
            "type": "object",
            "properties": {"value": property_schema},
            "required": ["value"],
        },
    )
    assert [arg.name for arg in missing_required_args(definition, {})] == ["value"]
    expected = [] if accepts_null else ["value"]
    assert [arg.name for arg in missing_required_args(definition, {"value": None})] == expected


def test_nullable_local_reference_is_resolved_in_the_tool_schema() -> None:
    definition = ToolDefinition(
        name="nullable_tool",
        description="",
        raw_parameters={
            "type": "object",
            "$defs": {"nullable_id": {"type": ["integer", "null"]}},
            "properties": {"value": {"$ref": "#/$defs/nullable_id"}},
            "required": ["value"],
        },
    )
    assert missing_required_args(definition, {"value": None}) == []


def test_invalid_referenced_schema_keeps_null_rejection() -> None:
    definition = ToolDefinition(
        name="nullable_tool",
        description="",
        raw_parameters={
            "type": "object",
            "$defs": {"invalid": {"type": "invalid-schema-type"}},
            "properties": {"value": {"$ref": "#/$defs/invalid"}},
            "required": ["value"],
        },
    )
    assert [arg.name for arg in missing_required_args(definition, {"value": None})] == ["value"]


def test_unproductive_reference_cycle_keeps_null_rejection() -> None:
    definition = ToolDefinition(
        name="nullable_tool",
        description="",
        raw_parameters={
            "type": "object",
            "$defs": {"cycle": {"$ref": "#/$defs/cycle"}},
            "properties": {"value": {"$ref": "#/$defs/cycle"}},
            "required": ["value"],
        },
    )
    assert [arg.name for arg in missing_required_args(definition, {"value": None})] == ["value"]


def test_remote_reference_does_not_fetch_a_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_network(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("required-argument checking must not perform network I/O")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", unexpected_network)
    definition = ToolDefinition(
        name="nullable_tool",
        description="",
        raw_parameters={
            "type": "object",
            "properties": {"value": {"$ref": "https://example.invalid/schema.json"}},
            "required": ["value"],
        },
    )
    assert [arg.name for arg in missing_required_args(definition, {"value": None})] == ["value"]


def test_nullable_parameter_row_accepts_explicit_null() -> None:
    definition = ToolDefinition(
        name="null_tool",
        description="",
        parameters=[ToolParameter(name="value", type="null")],
    )
    assert missing_required_args(definition, {"value": None}) == []
    assert [arg.name for arg in missing_required_args(definition, {})] == ["value"]


def test_nullable_string_still_rejects_present_blank_content() -> None:
    definition = ToolDefinition(
        name="nullable_tool",
        description="",
        raw_parameters={
            "type": "object",
            "properties": {"value": {"type": ["string", "null"]}},
            "required": ["value"],
        },
    )
    absent, blank = unsatisfied_required_args(definition, {"value": "   "})
    assert absent == []
    assert [arg.name for arg in blank] == ["value"]


def test_non_nullable_parameter_row_still_rejects_explicit_null() -> None:
    assert [
        arg.name
        for arg in missing_required_args(
            _write_note_definition(), {"mode": "append", "notebook_id": None}
        )
    ] == ["notebook_id"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "preview", "revisions": [{"module_id": "m1"}], "preview_id": None},
        {"action": "commit", "revisions": None, "preview_id": 1},
    ],
)
def test_preview_commit_contract_can_supply_required_inactive_fields_as_null(
    arguments: dict[str, Any],
) -> None:
    definition = ToolDefinition(
        name="reviewed_revision",
        description="",
        raw_parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["preview", "commit"]},
                "revisions": {"type": ["array", "null"]},
                "preview_id": {"type": ["integer", "null"]},
            },
            "required": ["action", "revisions", "preview_id"],
        },
    )
    assert missing_required_args(definition, arguments) == []


def test_schema_without_required_list_reports_nothing() -> None:
    definition = ToolDefinition(
        name="mcp_loose",
        description="",
        raw_parameters={"type": "object", "properties": {"q": {"type": "string"}}},
    )
    assert required_args(definition) == []


def test_message_names_the_missing_args_and_their_accepted_values() -> None:
    missing = missing_required_args(_write_note_definition(), {})
    message = missing_args_message("write_note", missing)
    assert "`mode`" in message and "`notebook_id`" in message
    # The enum is what turns "Unknown mode ''" into a one-round fix.
    assert "one of: append | edit" in message
    # And the model must be told that retrying verbatim is pointless.
    assert "rejected again" in message


class _WriteNote(BaseTool):
    """Records whether it was ever reached."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_definition(self) -> ToolDefinition:
        return _write_note_definition()

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(content="saved", success=True)


class _Registry:
    """The read-only slice of a registry the dispatcher actually uses."""

    def __init__(self, tool: _WriteNote) -> None:
        self._tool = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tool if name == "write_note" else None

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        kwargs.pop("event_sink", None)
        return await self._tool.execute(**kwargs)


async def _run_dispatch(
    tool_calls: list[dict[str, Any]],
    registry: Any,
    *,
    kwarg_augmenter: Any = None,
) -> list[StreamEvent]:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await dispatch_tool_calls(
        tool_calls=tool_calls,
        context=UnifiedContext(session_id="s1", user_message="hi"),
        stream=bus,
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=registry,
        kwarg_augmenter=kwarg_augmenter,
    )
    await bus.close()
    await consumer
    return events


def _call_states(events: list[StreamEvent]) -> list[str]:
    return [
        str((e.metadata or {}).get("call_state") or "")
        for e in events
        if (e.metadata or {}).get("trace_kind") == "call_status"
    ]


@pytest.mark.asyncio
async def test_call_with_empty_arguments_never_reaches_the_tool() -> None:
    tool = _WriteNote()
    events = await _run_dispatch(
        [{"id": "c1", "name": "write_note", "arguments": "{}"}],
        _Registry(tool),
    )

    assert tool.calls == [], "a malformed call must not run"
    result = next(e for e in events if e.type == StreamEventType.TOOL_RESULT)
    assert "`mode`" in result.content and "`notebook_id`" in result.content
    # The sub-trace closes with a terminal state rather than reading as running…
    assert _call_states(events) == ["error"]
    # …on a PROGRESS event: a rejected call is recoverable, and a stream ERROR
    # makes a partner turn re-run the whole turn on its backup model.
    assert [e for e in events if e.type == StreamEventType.ERROR] == []


@pytest.mark.asyncio
async def test_call_with_empty_string_arg_names_blank_not_missing() -> None:
    """#1101: a deliberate ``""`` must not be framed as an omitted key."""
    tool = _WriteNote()
    events = await _run_dispatch(
        [
            {
                "id": "c1",
                "name": "write_note",
                "arguments": json.dumps({"mode": "", "notebook_id": "nb1"}),
            }
        ],
        _Registry(tool),
    )

    assert tool.calls == []
    result = next(e for e in events if e.type == StreamEventType.TOOL_RESULT)
    assert "received empty value(s)" in result.content
    assert "`mode`" in result.content
    assert "without its required argument(s)" not in result.content
    assert _call_states(events) == ["error"]


@pytest.mark.asyncio
async def test_well_formed_call_is_dispatched_untouched() -> None:
    tool = _WriteNote()
    events = await _run_dispatch(
        [
            {
                "id": "c1",
                "name": "write_note",
                "arguments": json.dumps({"mode": "append", "notebook_id": "nb1"}),
            }
        ],
        _Registry(tool),
    )

    assert [c["mode"] for c in tool.calls] == ["append"]
    assert _call_states(events) == ["running", "complete"]


class _NullableWriteNote(_WriteNote):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_note",
            description="",
            raw_parameters={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "notebook_id": {"type": ["string", "null"]},
                },
                "required": ["mode", "notebook_id"],
            },
        )


@pytest.mark.asyncio
async def test_nullable_argument_is_dispatched_once_and_preserved() -> None:
    tool = _NullableWriteNote()
    events = await _run_dispatch(
        [{"id": "c1", "name": "write_note", "arguments": '{"mode":"append","notebook_id":null}'}],
        _Registry(tool),
    )
    assert [(call["mode"], call["notebook_id"]) for call in tool.calls] == [("append", None)]
    assert _call_states(events) == ["running", "complete"]


@pytest.mark.asyncio
async def test_runtime_injected_nullable_argument_counts_as_supplied() -> None:
    tool = _NullableWriteNote()
    events = await _run_dispatch(
        [{"id": "c1", "name": "write_note", "arguments": '{"mode":"append"}'}],
        _Registry(tool),
        kwarg_augmenter=lambda _name, args, _context: {**args, "notebook_id": None},
    )
    assert [call["notebook_id"] for call in tool.calls] == [None]
    assert _call_states(events) == ["running", "complete"]


@pytest.mark.asyncio
async def test_unknown_tool_still_reaches_the_registry() -> None:
    """The registry owns unknown-name errors; the guard must not pre-empt them."""
    tool = _WriteNote()
    events = await _run_dispatch(
        [{"id": "c1", "name": "nope", "arguments": "{}"}],
        _Registry(tool),
    )

    assert _call_states(events) == ["running", "complete"]
