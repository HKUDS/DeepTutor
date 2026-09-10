"""``knowledge_frontier`` — grounded read-only extension of an existing KB."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents._shared.tool_composition import (
    AUTO_MOUNTED_TOOLS,
    ToolMountFlags,
    compose_enabled_tools,
)
from deeptutor.tools.builtin import (
    BUILTIN_TOOL_NAMES,
    KnowledgeFrontierTool,
)
from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPEC_BY_NAME

_PAPER = {
    "title": "Grounded Frontier Learning",
    "authors": ["Ada Lovelace"],
    "year": 2026,
    "abstract": "A recent direction.",
    "url": "https://arxiv.org/abs/2601.0001",
    "arxiv_id": "2601.0001",
}


class _EmptyRegistry:
    @staticmethod
    def get_enabled(_selected: list[str]) -> list[Any]:
        return []


class FakeArxivSearchTool:
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    async def search_papers(self, **kwargs: Any) -> list[dict[str, Any]]:
        FakeArxivSearchTool.calls.append(kwargs)
        return list(FakeArxivSearchTool.results)


def _stub_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accessible: bool = True,
    reason_answer: str = 'Here are queries: ["knowledge graphs", "causal tutoring"]',
    reason_error: Exception | None = None,
    rag_sources: list[dict[str, Any]] | None = None,
) -> None:
    FakeArxivSearchTool.calls = []
    FakeArxivSearchTool.results = [_PAPER]

    manifest = (
        SimpleNamespace(
            name="Course",
            total=2,
            documents=(
                SimpleNamespace(name="attention-basics.pdf"),
                SimpleNamespace(name="curriculum.md"),
            ),
        )
        if accessible
        else None
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest",
        lambda kb_name, **_kwargs: manifest,
        raising=False,
    )

    async def fake_rag_search(query: str, kb_name: str) -> dict[str, Any]:
        return {
            "answer": "The KB covers attention basics and curriculum design.",
            "sources": [] if rag_sources is None else rag_sources,
        }

    async def fake_reason(**kwargs: Any) -> dict[str, Any]:
        if reason_error:
            raise reason_error
        return {"answer": reason_answer, "model": "test-model"}

    import deeptutor.tools.reason as reason_module

    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", fake_rag_search)
    monkeypatch.setattr(reason_module, "reason", fake_reason)
    monkeypatch.setattr("deeptutor.tools.knowledge_frontier.ArxivSearchTool", FakeArxivSearchTool)


class TestRegistration:
    def test_tool_is_registered(self) -> None:
        assert "knowledge_frontier" in BUILTIN_TOOL_NAMES
        assert (
            BUILTIN_TOOL_SPEC_BY_NAME["knowledge_frontier"].class_path
            == "deeptutor.tools.builtin:KnowledgeFrontierTool"
        )

    def test_mounting_is_kb_owned_not_a_user_toggle(self) -> None:
        assert "knowledge_frontier" in AUTO_MOUNTED_TOOLS
        assert "knowledge_frontier" not in compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=["knowledge_frontier"],
            mount_flags=ToolMountFlags(has_kb=False),
        )

    def test_mounts_with_the_same_gate_as_rag(self) -> None:
        tools = compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=[],
            mount_flags=ToolMountFlags(has_kb=True),
        )
        assert {"rag", "kb_files", "knowledge_frontier"} <= set(tools)


class TestExecute:
    @pytest.mark.asyncio
    async def test_returns_grounded_deduplicated_papers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_runtime(monkeypatch, rag_sources=[{"title": "Attention notes", "content": "..."}])

        result = await KnowledgeFrontierTool().execute(
            kb_name="Course",
            focus="curriculum design",
            max_papers=1,
            years_limit=2,
        )

        assert result.success
        assert "Knowledge frontier for `Course`" in result.content
        assert "Grounded Frontier Learning" in result.content
        assert "recommendations, not knowledge-base contents" in result.content
        assert result.metadata["status"] == "papers_found"
        assert result.metadata["queries"] == ["knowledge graphs", "causal tutoring"]
        assert result.sources[0]["type"] == "rag"
        assert result.sources[-1]["type"] == "paper"
        assert FakeArxivSearchTool.calls[0]["max_results"] == 1
        assert FakeArxivSearchTool.calls[0]["years_limit"] == 2

    @pytest.mark.asyncio
    async def test_inaccessible_kb_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_runtime(monkeypatch, accessible=False)

        with pytest.raises(ValueError, match="not accessible"):
            await KnowledgeFrontierTool().execute(kb_name="secret")

    @pytest.mark.asyncio
    async def test_query_generation_failure_still_searches_from_document_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_runtime(monkeypatch, reason_error=RuntimeError("LLM unavailable"))
        FakeArxivSearchTool.results = []

        result = await KnowledgeFrontierTool().execute(kb_name="Course")

        assert "No recent arXiv preprints" in result.content
        assert result.metadata["status"] == "papers_not_found"
        assert result.metadata["query_plan"]["source"] == "fallback"
        assert result.metadata["queries"][0] == "attention basics"

    @pytest.mark.asyncio
    async def test_a_partner_can_deny_the_tool(self) -> None:
        tools = compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=[],
            mount_flags=ToolMountFlags(has_kb=True),
            builtin_whitelist={"rag"},
        )
        assert "rag" in tools and "knowledge_frontier" not in tools
