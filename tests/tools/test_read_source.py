from __future__ import annotations

import asyncio

from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic.tool_dispatch import _prepare_tool_args
from deeptutor.runtime.registry.tool_registry import ToolRegistry


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.load_builtins()
    return registry


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
