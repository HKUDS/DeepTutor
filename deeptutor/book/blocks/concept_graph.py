"""Concept-graph block — deterministically rendered from the spine's graph.

This generator never calls an LLM. It reads ``ctx.extra['concept_graph']`` (a
``ConceptGraph`` model dump injected by the engine) and emits both:

- A Mermaid ``graph TD`` source the frontend can render with its existing
  Mermaid pipeline.
- A structured ``index`` payload (chapter list + concept ↔ chapter mapping)
  the frontend can use for an interactive sidebar in the Overview chapter.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType, ConceptGraph, SourceAnchor
from .base import BlockContext, BlockGenerator, GenerationFailure


def _safe_id(node_id: str, used: set[str]) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in (node_id or "n"))
    cleaned = cleaned.strip("_") or "n"
    candidate = cleaned[:32]
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{cleaned[:30]}_{suffix}"
    used.add(candidate)
    return candidate


def _escape_label(text: str) -> str:
    """Return a complete, single-line Mermaid-safe label."""
    cleaned = " ".join((text or "").split())
    cleaned = cleaned.replace('"', "'")
    return cleaned or "concept"


def render_mermaid(graph: ConceptGraph) -> str:
    """Render a ``ConceptGraph`` as a Mermaid ``graph TD`` source.

    When nodes carry ``chapter_id`` (chapter-level mind map produced by
    ``_build_chapter_map``), each node is rendered with a chapter number
    prefix. Labels stay complete; the frontend provides a scrollable viewport
    for diagrams wider or taller than the available card.
    The virtual book-title root (no ``chapter_id``) gets a stadium shape
    ``(["..."])`` to stand out visually.
    """
    if not graph.nodes:
        return 'graph TD\n  empty["(no concepts yet)"]'

    chapter_mode = any(n.chapter_id for n in graph.nodes)

    used: set[str] = set()
    id_map: dict[str, str] = {}
    lines = ["graph TD"]
    chapter_seq = 0
    for node in graph.nodes:
        sid = _safe_id(node.id or node.label, used)
        id_map[node.id] = sid

        if chapter_mode and node.chapter_id:
            chapter_seq += 1
            num = str(chapter_seq).zfill(2)
            label = _escape_label(node.label)
            lines.append(f'  {sid}["{num} · {label}"]')
        elif chapter_mode and not node.chapter_id:
            label = _escape_label(node.label)
            lines.append(f'  {sid}(["{label}"])')
        else:
            lines.append(f'  {sid}["{_escape_label(node.label)}"]')

    arrow_for = {"depends_on": "-->", "extends": "==>", "related": "-.->"}
    for edge in graph.edges:
        if edge.src not in id_map or edge.dst not in id_map:
            continue
        arrow = arrow_for.get(edge.relation, "-->")
        lines.append(f"  {id_map[edge.src]} {arrow} {id_map[edge.dst]}")

    return "\n".join(lines)


class ConceptGraphGenerator(BlockGenerator):
    block_type = BlockType.CONCEPT_GRAPH

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        raw = ctx.extra.get("concept_graph") or ctx.block.params.get("concept_graph")
        if raw is None:
            raise GenerationFailure("concept_graph payload missing from BlockContext.extra")
        if isinstance(raw, ConceptGraph):
            graph = raw
        elif isinstance(raw, dict):
            try:
                graph = ConceptGraph.model_validate(raw)
            except Exception as exc:
                raise GenerationFailure(f"invalid concept_graph payload: {exc}") from exc
        else:
            raise GenerationFailure(f"unexpected concept_graph payload type: {type(raw).__name__}")

        chapters_index = ctx.extra.get("chapter_index") or []
        if not isinstance(chapters_index, list):
            chapters_index = []

        mermaid_src = render_mermaid(graph)

        # Build a node→chapter lookup for the interactive sidebar.
        node_to_chapter: dict[str, str] = {}
        for n in graph.nodes:
            if n.chapter_id:
                node_to_chapter[n.id] = n.chapter_id

        return (
            {
                "render_type": "concept_graph",
                "code": {"language": "mermaid", "content": mermaid_src},
                "graph": graph.model_dump(),
                "index": {
                    "chapters": chapters_index,
                    "node_to_chapter": node_to_chapter,
                },
            },
            [],
            {
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
            },
        )


__all__ = ["ConceptGraphGenerator", "render_mermaid"]
