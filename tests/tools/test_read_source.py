from __future__ import annotations

import asyncio

from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic.tool_arg_guard import (
    missing_required_args,
    required_args,
)
from deeptutor.runtime.agentic.tool_dispatch import (
    KwargAugmenter,
    _prepare_tool_args,
    dispatch_tool_calls,
)
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.runtime.stream_bus import StreamBus


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.load_builtins()
    return registry


def _source_augmenter(source_index: dict[str, str]) -> KwargAugmenter:
    """Mirror the explorer: read_source receives the turn's source index."""

    def augment(
        tool_name: str,
        args: dict[str, object],
        _context: UnifiedContext,
    ) -> dict[str, object]:
        augmented = dict(args)
        if tool_name == "read_source":
            augmented["source_index"] = source_index
        return augmented

    return augment


def test_pdf_alias_reads_the_only_attached_source() -> None:
    result = asyncio.run(
        _registry().execute(
            "pdf",
            source_index={"at-pdf-1": "Algebra worksheet contents"},
        )
    )

    assert result.success is True
    assert result.content == "Algebra worksheet contents"
    assert result.metadata["source_id"] == "at-pdf-1"


def test_pdf_alias_does_not_guess_between_multiple_sources() -> None:
    result = asyncio.run(
        _registry().execute(
            "pdf",
            source_index={
                "at-pdf-1": "First PDF",
                "at-pdf-2": "Second PDF",
            },
        )
    )

    assert result.success is False
    assert "source_id is required when multiple sources are available" in result.content


def test_pdf_alias_is_augmented_as_read_source() -> None:
    source_index = {"at-pdf-1": "Algebra worksheet contents"}

    def augment(
        tool_name: str,
        args: dict[str, object],
        _context: UnifiedContext,
    ) -> dict[str, object]:
        augmented = dict(args)
        if tool_name == "read_source":
            augmented["source_index"] = source_index
        return augmented

    prepared, _ = _prepare_tool_args(
        [{"id": "call-1", "name": "pdf", "arguments": "{}"}],
        UnifiedContext(),
        augment,
        registry=_registry(),
    )

    assert prepared == [("call-1", "pdf", {"source_index": source_index})]


def test_alias_defaults_survive_canonical_argument_augmentation() -> None:
    def augment(
        tool_name: str,
        args: dict[str, object],
        _context: UnifiedContext,
    ) -> dict[str, object]:
        augmented = dict(args)
        if tool_name == "rag":
            augmented.setdefault("mode", "hybrid")
        return augmented

    prepared, _ = _prepare_tool_args(
        [{"id": "call-1", "name": "rag_naive", "arguments": "{}"}],
        UnifiedContext(),
        augment,
        registry=_registry(),
    )

    assert prepared == [("call-1", "rag_naive", {"mode": "naive"})]


def test_read_source_schema_does_not_require_source_id() -> None:
    """The tool auto-selects the sole source, so the guard must not require it.

    Issue #1223: the model calls the ``pdf`` alias with empty arguments for a
    single attached PDF. While ``source_id`` was schema-required the
    pre-dispatch guard rejected the call before ``read_source`` could apply its
    single-source fallback, and the agent fell back to scraping the file with
    Python.
    """
    definition = _registry().get("read_source").get_definition()

    assert [arg.name for arg in required_args(definition)] == []
    assert missing_required_args(definition, {"source_index": {"at-pdf-1": "text"}}) == []


def test_pdf_alias_with_empty_arguments_reads_the_only_source() -> None:
    """End-to-end: the guard must let the bare ``pdf`` call reach the tool."""

    async def _run() -> list[dict[str, object]]:
        source_index = {"at-pdf-1": "Algebra worksheet contents"}
        outcome = await dispatch_tool_calls(
            tool_calls=[{"id": "call-1", "name": "pdf", "arguments": "{}"}],
            context=UnifiedContext(
                session_id="s1",
                user_message="Can you solve it?",
                metadata={"source_index": source_index},
            ),
            stream=StreamBus(),
            source="chat",
            stage="responding",
            iteration_index=0,
            registry=_registry(),
            kwarg_augmenter=_source_augmenter(source_index),
        )
        return outcome.tool_messages

    tool_messages = asyncio.run(_run())

    assert [message["content"] for message in tool_messages] == ["Algebra worksheet contents"]


def test_pdf_alias_with_empty_arguments_still_refuses_ambiguous_sources() -> None:
    """Relaxing the guard must not let the tool guess between two sources."""

    async def _run() -> list[dict[str, object]]:
        source_index = {"at-pdf-1": "First", "at-pdf-2": "Second"}
        outcome = await dispatch_tool_calls(
            tool_calls=[{"id": "call-1", "name": "pdf", "arguments": "{}"}],
            context=UnifiedContext(
                session_id="s1",
                user_message="Summarise both.",
                metadata={"source_index": source_index},
            ),
            stream=StreamBus(),
            source="chat",
            stage="responding",
            iteration_index=0,
            registry=_registry(),
            kwarg_augmenter=_source_augmenter(source_index),
        )
        return outcome.tool_messages

    tool_messages = asyncio.run(_run())

    assert "source_id is required when multiple sources are available" in str(
        tool_messages[0]["content"]
    )
