import pytest

from deeptutor.tools.builtin import KnowledgeFrontierTool
from deeptutor.tools.knowledge_frontier_tool import _dedupe_sources, discover_frontier


@pytest.mark.asyncio
async def test_requires_explicit_kb_name():
    tool = KnowledgeFrontierTool()
    with pytest.raises(ValueError, match="requires an explicit kb_name"):
        await tool.execute(kb_name="")


@pytest.mark.asyncio
async def test_empty_kb_returns_no_content(monkeypatch):
    async def _empty_rag(**kwargs):
        return {"answer": "", "content": "", "sources": []}

    monkeypatch.setattr("deeptutor.tools.knowledge_frontier_tool.rag_search", _empty_rag)
    tool = KnowledgeFrontierTool()
    result = await tool.execute(kb_name="test-kb")
    assert "no analysable content" in result.content.lower()
    assert result.sources == []


@pytest.mark.asyncio
async def test_dedupe_sources_removes_duplicates():
    sources = [
        {"source_id": "doc-1", "title": "A"},
        {"source_id": "doc-1", "title": "A duplicate"},
        {"source_id": "doc-2", "title": "B"},
    ]
    result = _dedupe_sources(sources)
    assert len(result) == 2
    assert result[0]["title"] == "A"
    assert result[1]["title"] == "B"


@pytest.mark.asyncio
async def test_dedupe_sources_caps_at_max():
    sources = [{"source_id": f"doc-{i}", "title": f"T{i}"} for i in range(20)]
    result = _dedupe_sources(sources)
    assert len(result) <= 12


@pytest.mark.asyncio
async def test_successful_discovery_aggregates_probes(monkeypatch):
    call_count = 0

    async def _mock_rag(**kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "answer": f"Probe {call_count} answer content.",
            "sources": [
                {"source_id": f"doc-{call_count}", "title": f"Doc {call_count}"},
            ],
        }

    monkeypatch.setattr("deeptutor.tools.knowledge_frontier_tool.rag_search", _mock_rag)
    payload = await discover_frontier("test-kb")
    assert call_count == 5
    assert "Core Topics" in payload["summary"]
    assert "Emerging Trends" in payload["summary"]
    assert "Coverage Gaps" in payload["summary"]
    assert len(payload["sources"]) == 5


@pytest.mark.asyncio
async def test_rag_failure_is_swallowed(monkeypatch):
    async def _failing_rag(**kwargs):
        raise RuntimeError("RAG unavailable")

    monkeypatch.setattr("deeptutor.tools.knowledge_frontier_tool.rag_search", _failing_rag)
    payload = await discover_frontier("test-kb")
    assert payload["summary"] == ""
    assert payload["sources"] == []


def test_tool_is_registered():
    from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPECS

    names = [spec.name for spec in BUILTIN_TOOL_SPECS]
    assert "knowledge_frontier" in names
