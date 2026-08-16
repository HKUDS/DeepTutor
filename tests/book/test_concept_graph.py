from __future__ import annotations

from deeptutor.book.blocks.concept_graph import render_mermaid
from deeptutor.book.models import ConceptEdge, ConceptGraph, ConceptNode


def test_mermaid_keeps_complete_chapter_titles() -> None:
    title = "Understanding transformations through complete geometric intuition"
    graph = ConceptGraph(
        nodes=[
            ConceptNode(id="root", label='A "quoted" book'),
            ConceptNode(id="chapter-one", label=title, chapter_id="chapter-1"),
        ],
        edges=[ConceptEdge(src="root", dst="chapter-one")],
    )

    rendered = render_mermaid(graph)

    assert title in rendered
    assert "A 'quoted' book" in rendered
    assert "…" not in rendered
