"""Focused tests for research citation payload normalization."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.agents.research.utils.citation_manager import CitationManager
from deeptutor.services.rag.pipelines.pageindex.storage import CLOUD_PROVIDER, OSS_PROVIDER
from deeptutor.services.rag.pipelines.pageindex.tools import PageIndexSDKTool


def _trace() -> SimpleNamespace:
    return SimpleNamespace(query="What is RAG?", summary="Retrieved sources", timestamp="now")


def test_rag_citation_accepts_top_level_source_list(tmp_path, capsys) -> None:
    manager = CitationManager("research-list", cache_dir=tmp_path)
    raw_answer = json.dumps(
        [
            {
                "title": "Retrieval-Augmented Generation",
                "content": "Ground an answer in retrieved documents.",
                "filename": "rag.pdf",
                "page_number": 3,
            }
        ]
    )

    citation = manager._extract_rag_citation("CIT-1-01", "rag", raw_answer, _trace())

    assert citation["kb_name"] == ""
    assert citation["total_sources"] == 1
    assert citation["sources"][0] == {
        "title": "Retrieval-Augmented Generation",
        "content_preview": "Ground an answer in retrieved documents.",
        "source_file": "rag.pdf",
        "page": 3,
        "chunk_id": 0,
        "score": "",
    }
    assert "Failed to parse RAG source info" not in capsys.readouterr().out


def test_rag_citation_preserves_object_payload_metadata(tmp_path) -> None:
    manager = CitationManager("research-object", cache_dir=tmp_path)
    raw_answer = json.dumps(
        {
            "kb_name": "course-notes",
            "chunks": [{"text": "A source chunk", "id": "chunk-1", "similarity": 0.9}],
        }
    )

    citation = manager._extract_rag_citation("CIT-1-01", "rag", raw_answer, _trace())

    assert citation["kb_name"] == "course-notes"
    assert citation["total_sources"] == 1
    assert citation["sources"][0]["content_preview"] == "A source chunk"
    assert citation["sources"][0]["chunk_id"] == "chunk-1"
    assert citation["sources"][0]["score"] == 0.9


def test_rag_citation_prefers_the_structured_tool_metadata(tmp_path) -> None:
    """``raw_answer`` is the prose shown to the model, not a JSON payload.

    Every RAG pipeline normalises what it retrieved into ``metadata["sources"]``,
    and that is what reaches the citation manager as ``tool_metadata`` — so a
    perfectly ordinary textual answer must still produce source links.
    """
    manager = CitationManager("research-metadata", cache_dir=tmp_path)
    metadata = {
        "answer": "RAG grounds an answer in retrieved documents.",
        "kb_name": "lecture-notes",
        "sources": [
            {
                "title": "Retrieval-Augmented Generation",
                "content": "Ground an answer in retrieved documents.",
                "source": "rag.pdf",
                "page": 3,
                "score": 0.91,
            }
        ],
    }

    citation = manager._extract_rag_citation(
        "CIT-1-01",
        "rag",
        "RAG grounds an answer in retrieved documents.",
        _trace(),
        metadata,
    )

    assert citation["kb_name"] == "lecture-notes"
    assert citation["total_sources"] == 1
    assert citation["sources"][0]["source_file"] == "rag.pdf"
    assert citation["sources"][0]["page"] == 3


def test_rag_citation_falls_back_to_the_answer_without_metadata(tmp_path) -> None:
    """Traces recorded before metadata reached this extractor still resolve."""
    manager = CitationManager("research-fallback", cache_dir=tmp_path)
    raw_answer = json.dumps({"kb_name": "kb", "sources": [{"title": "T", "content": "C"}]})

    citation = manager._extract_rag_citation("CIT-1-02", "rag", raw_answer, _trace(), None)

    assert citation["kb_name"] == "kb"
    assert citation["total_sources"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [CLOUD_PROVIDER, OSS_PROVIDER])
@pytest.mark.parametrize(
    ("query", "kb_name", "filename", "expected"),
    [
        (
            "What is gravity?",
            "Physics",
            "Gravitation.pdf",
            "RAG: What is gravity? [KB: Physics] [Sources: Gravitation.pdf]",
        ),
        (
            "<gravity> & mass",
            "Physics & <lab>",
            "A&B <notes>.pdf",
            "RAG: &lt;gravity&gt; &amp; mass [KB: Physics &amp; &lt;lab&gt;] "
            "[Sources: A&amp;B &lt;notes&gt;.pdf]",
        ),
    ],
)
async def test_pageindex_report_citation_preserves_tool_sources(
    tmp_path, provider, query, kb_name, filename, expected
):
    sdk_tool = SimpleNamespace(
        name="get_page_content",
        description="Read pages",
        params_json_schema={},
        on_invoke_tool=AsyncMock(
            return_value=json.dumps(
                {
                    "success": True,
                    "doc_name": filename,
                    "content": [{"page": 3, "text": "Grounded answer"}],
                }
            )
        ),
    )
    tool = PageIndexSDKTool(
        sdk_tool, provider=provider, kb_name=kb_name, doc_ids={filename: "doc-1"}
    )
    result = await tool.execute(doc_name=filename, pages="3")
    manager = CitationManager("research-pageindex", cache_dir=tmp_path)
    trace = SimpleNamespace(query=query, summary="Retrieved sources", timestamp="now")

    assert manager.add_citation("CIT-1-01", tool.name, trace, result.content, result.metadata)
    assert manager.format_citation_for_report("CIT-1-01") == expected


@pytest.mark.parametrize("tool_type", ["rag", "rag_naive", "rag_hybrid"])
def test_existing_rag_report_citation_keeps_sources(tmp_path, tool_type):
    manager = CitationManager("research-rag", cache_dir=tmp_path)
    metadata = {"kb_name": "Notes", "sources": [{"title": "Document"}]}
    assert manager.add_citation("CIT-1-01", tool_type, _trace(), "Answer", metadata)
    assert manager.format_citation_for_report("CIT-1-01") == (
        "RAG: What is RAG? [KB: Notes] [Sources: Document]"
    )


def test_web_report_citation_keeps_escaped_links(tmp_path):
    manager = CitationManager("research-web", cache_dir=tmp_path)
    metadata = {"citations": [{"title": "A & B", "url": "https://example.com/?a=1&b=2"}]}
    assert manager.add_citation("CIT-1-01", "web_search", _trace(), "Answer", metadata)
    assert manager.format_citation_for_report("CIT-1-01") == (
        'Web Search: What is RAG?<br><a href="https://example.com/?a=1&amp;b=2">A &amp; B</a>'
    )
