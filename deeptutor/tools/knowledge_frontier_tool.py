"""Knowledge-base frontier discovery tool.

Analyses one knowledge base with several targeted RAG probes and returns an
evidence-backed frontier report the active turn's LLM can synthesize into
themes, gaps, and follow-up questions. Nothing is written back to the KB.
"""

from __future__ import annotations

from typing import Any

from deeptutor.tools.rag_tool import rag_search

_MAX_PROBE_QUERIES = 5
_MAX_SOURCES = 12

_PROBE_QUERIES: tuple[tuple[str, str], ...] = (
    ("Core Topics", "What are the main topics and key concepts in this knowledge base?"),
    (
        "Emerging Trends",
        "What recent developments, emerging trends, or new directions are discussed?",
    ),
    ("Coverage Gaps", "What topics are mentioned but lack detailed coverage, evidence, or depth?"),
    (
        "Open Debates",
        "What contradictions, open debates, or unresolved claims appear in the material?",
    ),
    (
        "Future Directions",
        "What future directions, open problems, or follow-up research are suggested?",
    ),
)


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for src in sources:
        key = str(src.get("source_id", "") or src.get("url", "") or src.get("title", ""))[:200]
        if key and key not in seen:
            seen.add(key)
            result.append(src)
    return result[:_MAX_SOURCES]


async def discover_frontier(
    kb_name: str,
    event_sink: Any = None,
) -> dict:
    """Run multiple RAG probes against ``kb_name`` and aggregate their
    answers and source references into a single structured payload."""
    kb_name = (kb_name or "").strip()
    if not kb_name:
        raise ValueError("knowledge_frontier requires an explicit kb_name.")

    sections: list[str] = []
    all_sources: list[dict] = []
    for label, query in _PROBE_QUERIES:
        try:
            result = await rag_search(
                query=query,
                kb_name=kb_name,
                event_sink=event_sink,
            )
        except Exception:
            continue
        content = (result.get("answer") or result.get("content") or "").strip()
        if not content:
            continue
        sections.append(f"## {label}\n\n{content}")
        probe_sources = result.get("sources", [])
        if isinstance(probe_sources, list):
            for src in probe_sources:
                if isinstance(src, dict):
                    all_sources.append(src)

    sources = _dedupe_sources(all_sources)
    summary = "\n\n---\n\n".join(sections)
    return {"summary": summary, "sources": sources}
