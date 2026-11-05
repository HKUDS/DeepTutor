from __future__ import annotations

import asyncio
import json

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic.tool_dispatch import _prepare_tool_args
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.tools.builtin import ReadSourceTool


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


@pytest.mark.asyncio
async def test_large_history_can_be_reconstructed_from_bounded_pages():
    tool = ReadSourceTool()
    original = '学员纠正了之前的答案。"\\\n' * 4000
    sources = {"hs-tutor-2": original}
    offset = 0
    pages = []
    while offset is not None:
        read = await tool.execute(
            source_id="hs-tutor-2",
            source_index=sources,
            offset=offset,
            _mastery_source_context=True,
        )
        assert read.success
        page = json.loads(read.content)
        assert page["offset"] == offset
        assert page["total_chars"] == len(original)
        assert 0 < len(page["content"]) <= tool.HISTORY_PAGE_CHARS
        assert page["next_offset"] == read.metadata["next_offset"]
        assert read.public_result == {"content": "Attached source inspected privately."}
        pages.append(page["content"])
        offset = page["next_offset"]
    assert "".join(pages) == original
    assert sources == {"hs-tutor-2": original}


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-1, True, "0", 1.5, 10, None])
async def test_history_page_rejects_invalid_offsets(offset):
    read = await ReadSourceTool().execute(
        source_id="hs-tutor-2", source_index={"hs-tutor-2": "short"}, offset=offset
    )
    assert not read.success
    assert "offset" in read.content


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", ["nb-1", "hs-session", "at-pdf-1", "hs-tutor-2"])
async def test_existing_full_source_reads_are_unchanged(source_id):
    text = "Original evidence" if source_id == "hs-tutor-2" else "Original evidence" * 4000
    read = await ReadSourceTool().execute(source_id=source_id, source_index={source_id: text})
    assert read.success
    assert read.content == text
    assert read.metadata == {"source_id": source_id, "char_count": len(text)}
