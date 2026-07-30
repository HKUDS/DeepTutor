"""An MCP server's progress notifications, on their way to the trace.

A long MCP call — a crawl, a render, a big query — is the case where a static
spinner is the whole of what a reader gets. The server already tells us how far
along it is; these tests pin that we ask for that, and that every shape a server
may send still renders as something a person can read.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.mcp.manager import (
    MCPConnectionManager,
    MCPToolAdapter,
    _progress_reporter,
    _ServerConnection,
    describe_connect_failure,
)


class _Sink:
    """Stands in for the dispatcher's channel into one call's sub-trace."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def __call__(
        self, event_type: str, message: str = "", metadata: dict[str, Any] | None = None
    ) -> None:
        self.events.append((event_type, message, metadata or {}))


# ── how a notification renders ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_counted_step_renders_as_a_percentage() -> None:
    sink = _Sink()
    await _progress_reporter(sink, "crawler")(3, 10, "fetching pages")

    kind, message, meta = sink.events[0]
    assert kind == "tool_progress"
    assert message == "fetching pages (30%)"
    assert meta["tool_source"] == "mcp"
    assert meta["tool_provider"] == "crawler"
    assert meta["progress_fraction"] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_numbers_with_no_message_still_say_something() -> None:
    sink = _Sink()
    await _progress_reporter(sink, "crawler")(1, 4, None)

    assert sink.events[0][1] == "25%"


@pytest.mark.asyncio
async def test_a_message_with_no_total_is_passed_through_verbatim() -> None:
    """No total means no percentage to invent; the message is the whole signal."""
    sink = _Sink()
    await _progress_reporter(sink, "crawler")(7, None, "indexing")

    assert sink.events[0][1] == "indexing"
    assert "progress_fraction" not in sink.events[0][2]


@pytest.mark.asyncio
async def test_a_bare_tick_reports_its_counter() -> None:
    """Still the difference between "working" and "hung", so it must render."""
    sink = _Sink()
    await _progress_reporter(sink, "crawler")(12, None, None)

    assert sink.events[0][1] == "step 12"


@pytest.mark.asyncio
async def test_a_total_of_zero_does_not_divide_by_it() -> None:
    sink = _Sink()
    await _progress_reporter(sink, "crawler")(0, 0, "starting")

    assert sink.events[0][1] == "starting"


@pytest.mark.asyncio
async def test_a_progress_beyond_the_total_is_clamped() -> None:
    """Servers do overshoot. A 130% status line reads as a bug in DeepTutor."""
    sink = _Sink()
    await _progress_reporter(sink, "crawler")(13, 10, "almost")

    assert sink.events[0][1] == "almost (100%)"
    assert sink.events[0][2]["progress_fraction"] == 1.0


@pytest.mark.asyncio
async def test_a_failing_sink_cannot_fail_the_tool_call() -> None:
    """This runs inside the SDK's notification handler."""

    async def _broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("stream is gone")

    await _progress_reporter(_broken, "crawler")(1, 2, "half")  # must not raise


# ── whether we ask for it at all ──────────────────────────────────────────


class _Session:
    def __init__(self) -> None:
        self.progress_callback: object = "unset"

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any], progress_callback: object = None
    ):
        from mcp import types

        self.progress_callback = progress_callback
        return types.CallToolResult(content=[types.TextContent(type="text", text="done")])


def _adapter(manager: MCPConnectionManager, session: _Session) -> MCPToolAdapter:
    from deeptutor.services.mcp.config import MCPServerConfig

    conn = _ServerConnection(
        name="crawler",
        config=MCPServerConfig(url="https://crawler.example/mcp"),
        signature="sig",
        owner="u_ada",
        status="connected",
    )
    conn.session = session
    manager._connections[("u_ada", "crawler")] = conn
    return MCPToolAdapter(
        manager=manager,
        owner="u_ada",
        server_name="crawler",
        original_name="crawl",
        description="d",
        input_schema=None,
        tool_timeout=5,
    )


@pytest.mark.asyncio
async def test_a_call_with_a_sub_trace_asks_the_server_for_progress() -> None:
    session = _Session()
    adapter = _adapter(MCPConnectionManager(), session)
    sink = _Sink()

    await adapter.execute(event_sink=sink, url="https://x.example")

    assert callable(session.progress_callback), (
        "the SDK only requests notifications when a callback is supplied, so this "
        "is what decides whether a long call reports anything at all"
    )


@pytest.mark.asyncio
async def test_a_call_with_nowhere_to_publish_does_not_ask() -> None:
    """Asking for notifications we would discard is pure traffic."""
    session = _Session()
    adapter = _adapter(MCPConnectionManager(), session)

    await adapter.execute(url="https://x.example")

    assert session.progress_callback is None


@pytest.mark.asyncio
async def test_the_sink_never_reaches_the_server_as_an_argument() -> None:
    """It is dispatcher plumbing; forwarding it would corrupt the tool's args."""

    class _Recording(_Session):
        def __init__(self) -> None:
            super().__init__()
            self.arguments: dict[str, Any] = {}

        async def call_tool(self, tool_name, arguments, progress_callback=None):  # type: ignore[no-untyped-def]
            self.arguments = dict(arguments)
            return await super().call_tool(tool_name, arguments, progress_callback)

    session = _Recording()
    adapter = _adapter(MCPConnectionManager(), session)

    await adapter.execute(event_sink=_Sink(), url="https://x.example")

    assert session.arguments == {"url": "https://x.example"}


@pytest.mark.asyncio
async def test_progress_reaches_the_sink_end_to_end() -> None:
    """The seam the feature actually lives on: server notification → trace event."""

    class _Reporting(_Session):
        async def call_tool(self, tool_name, arguments, progress_callback=None):  # type: ignore[no-untyped-def]
            if progress_callback is not None:
                await progress_callback(1, 2, "halfway")
            return await super().call_tool(tool_name, arguments, progress_callback)

    sink = _Sink()
    adapter = _adapter(MCPConnectionManager(), _Reporting())

    result = await adapter.execute(event_sink=sink, url="https://x.example")

    assert [event[1] for event in sink.events] == ["halfway (50%)"]
    assert result.content == "done"


# ── why a connection failed ────────────────────────────────────────────────


def test_a_wrapped_transport_failure_reports_the_real_cause() -> None:
    """The MCP SDK runs its transport in an anyio task group, so nearly every
    failure arrives wrapped. Reporting the wrapper produced *"ExceptionGroup:
    unhandled errors in a TaskGroup (1 sub-exception)"* under a server's row —
    which is what someone whose URL needs OAuth used to be told."""
    from deeptutor.services.mcp.manager import describe_connect_failure

    wrapped = ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("401 Unauthorized")])

    described = describe_connect_failure(wrapped)

    assert "401 Unauthorized" in described
    assert "TaskGroup" not in described


def test_nested_groups_are_flattened() -> None:
    inner = ExceptionGroup("inner", [ValueError("bad host")])
    outer = ExceptionGroup("outer", [inner])

    assert "bad host" in describe_connect_failure(outer)


def test_the_same_cause_repeated_is_said_once() -> None:
    """A retrying transport contributes the same error several times, and "401"
    three times is not more informative than once."""
    from deeptutor.services.mcp.manager import describe_connect_failure

    group = ExceptionGroup("g", [RuntimeError("401 Unauthorized") for _ in range(3)])

    assert describe_connect_failure(group).count("401 Unauthorized") == 1


def test_several_distinct_causes_are_all_reported_but_bounded() -> None:
    from deeptutor.services.mcp.manager import describe_connect_failure

    group = ExceptionGroup(
        "g",
        [RuntimeError(f"cause {index}") for index in range(6)],
    )

    described = describe_connect_failure(group)
    assert "cause 0" in described and "cause 2" in described
    assert "cause 5" not in described, "an unbounded list would fill the row"


def test_a_plain_exception_is_passed_through() -> None:
    from deeptutor.services.mcp.manager import describe_connect_failure

    assert describe_connect_failure(TimeoutError("took too long")) == "TimeoutError: took too long"


def test_an_empty_group_still_says_something() -> None:
    """Degenerate, but a blank status cell is worse than a vague one."""
    from deeptutor.services.mcp.manager import describe_connect_failure

    assert describe_connect_failure(ExceptionGroup("g", [ValueError()])).strip()
