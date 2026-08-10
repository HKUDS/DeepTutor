"""Focused coverage for RAG source extraction in the citation manager."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.research.utils.citation_manager import CitationManager


def _extract_rag_sources(tmp_path: Path, payload: Any) -> dict[str, Any]:
    manager = CitationManager("test-research", cache_dir=tmp_path)
    tool_trace = SimpleNamespace(
        query="What is gravity?",
        summary="Retrieved supporting material.",
        timestamp="2026-08-11T00:00:00Z",
    )
    return manager._extract_rag_citation(
        "CIT-1-01",
        "rag",
        json.dumps(payload),
        tool_trace,
    )


def test_rag_dict_payload_preserves_source_mapping_and_kb_name(tmp_path: Path) -> None:
    citation = _extract_rag_sources(
        tmp_path,
        {
            "kb_name": "physics",
            "documents": [
                {
                    "doc_title": "Gravity notes",
                    "text": "Evidence from the course notes.",
                    "filename": "gravity.pdf",
                    "page_number": 7,
                    "id": "chunk-7",
                    "similarity": 0.91,
                }
            ],
        },
    )

    assert citation["kb_name"] == "physics"
    assert citation["sources"] == [
        {
            "title": "Gravity notes",
            "content_preview": "Evidence from the course notes.",
            "source_file": "gravity.pdf",
            "page": 7,
            "chunk_id": "chunk-7",
            "score": 0.91,
        }
    ]
    assert citation["total_sources"] == 1


def test_rag_top_level_list_maps_document_and_string_sources(tmp_path: Path) -> None:
    citation = _extract_rag_sources(
        tmp_path,
        [
            {
                "title": "Lecture transcript",
                "content": "A" * 210,
                "source": "lecture.txt",
                "page": 3,
                "chunk_id": "chunk-3",
                "score": 0.8,
            },
            "Plain-text supporting evidence.",
        ],
    )

    assert citation["kb_name"] == ""
    assert citation["sources"] == [
        {
            "title": "Lecture transcript",
            "content_preview": "A" * 200,
            "source_file": "lecture.txt",
            "page": 3,
            "chunk_id": "chunk-3",
            "score": 0.8,
        },
        {"content_preview": "Plain-text supporting evidence."},
    ]
    assert citation["total_sources"] == 2


@pytest.mark.parametrize(
    "record",
    [
        {
            "entity_name": "Newton",
            "description": "A scientist in the knowledge graph.",
            "id": "entity-1",
            "score": 0.99,
        },
        {
            "src_id": "force",
            "tgt_id": "acceleration",
            "relation_id": "force->acceleration",
            "description": "A graph relationship, not a document source.",
        },
        {
            "title": "",
            "content": "",
            "source": "",
            "id": "chunk-0",
            "page": 1,
            "score": 0.5,
        },
    ],
    ids=["entity-with-id", "relationship", "empty-document-fields"],
)
def test_rag_top_level_list_ignores_non_document_records(
    tmp_path: Path,
    record: dict[str, Any],
) -> None:
    citation = _extract_rag_sources(tmp_path, [record])

    assert citation["kb_name"] == ""
    assert citation["sources"] == []
    assert citation["total_sources"] == 0


def test_rag_scalar_payload_has_no_sources(tmp_path: Path) -> None:
    citation = _extract_rag_sources(tmp_path, 42)

    assert citation["kb_name"] == ""
    assert citation["sources"] == []
    assert citation["total_sources"] == 0
