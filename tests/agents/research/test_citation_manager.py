"""Focused tests for research citation payload normalization."""

from __future__ import annotations

import json
from types import SimpleNamespace

from deeptutor.agents.research.utils.citation_manager import CitationManager


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
