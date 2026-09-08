"""AI-assisted frontier discovery for an existing knowledge base.

``rag`` answers questions about material the learner already collected.  This
service closes the next loop in the workflow: use that material to identify the
topics worth following, then search arXiv for recent work.  Discovery is
read-only — adding a result to a KB remains an explicit user action.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
import re
from typing import Any

from deeptutor.tools.paper_search_tool import ArxivSearchTool

DEFAULT_MAX_PAPERS = 5
MAX_PAPERS_LIMIT = 10
DEFAULT_YEARS_LIMIT = 3
MAX_YEARS_LIMIT = 10
MAX_SEARCH_QUERIES = 3
_CONTEXT_CHARS = 3500


async def discover_frontier(
    *,
    kb_name: str,
    manifest: Any,
    focus: str = "",
    max_papers: int = DEFAULT_MAX_PAPERS,
    years_limit: int | None = DEFAULT_YEARS_LIMIT,
    **llm_kwargs: Any,
) -> dict[str, Any]:
    """Summarise a KB, derive arXiv queries, and collect deduplicated papers.

    The caller performs the KB access check and supplies its manifest.  The
    method is deliberately resilient: if query generation fails, document names
    and the user's focus still produce useful fallback searches.
    """
    requested_papers = _clamped_int(max_papers, DEFAULT_MAX_PAPERS, 1, MAX_PAPERS_LIMIT)
    requested_years = (
        None
        if years_limit is None
        else _clamped_int(years_limit, DEFAULT_YEARS_LIMIT, 0, MAX_YEARS_LIMIT)
    )
    focus_text = _one_line(focus, limit=240)
    document_names = [
        str(document.name)
        for document in getattr(manifest, "documents", ())
        if str(getattr(document, "name", "")).strip()
    ]

    rag_result = await _search_kb(kb_name=kb_name, focus=focus_text)
    kb_summary = str(rag_result.get("answer") or rag_result.get("content") or "").strip()
    query_result, queries = await _derive_queries(
        kb_name=kb_name,
        focus=focus_text,
        kb_summary=kb_summary,
        document_names=document_names,
        **llm_kwargs,
    )

    papers, query_errors = await _search_papers(
        queries=queries,
        max_results=requested_papers,
        years_limit=requested_years,
    )
    deduped = _deduplicate(papers)[:requested_papers]
    status = "papers_found" if deduped else "papers_not_found"
    content = _render_report(
        kb_name=kb_name,
        focus=focus_text,
        document_count=getattr(manifest, "total", 0),
        kb_summary=kb_summary,
        queries=queries,
        papers=deduped,
        query_errors=query_errors,
    )

    return {
        "content": content,
        "metadata": {
            "kb_name": str(getattr(manifest, "name", "") or kb_name),
            "kb_documents": getattr(manifest, "total", 0),
            "focus": focus_text,
            "status": status,
            "kb_summary": kb_summary,
            "queries": queries,
            "query_errors": query_errors,
            "papers": deduped,
            "query_plan": query_result,
            "years_limit": requested_years,
        },
        "kb_sources": _kb_sources(rag_result, kb_name=kb_name, focus=focus_text),
    }


async def _search_kb(*, kb_name: str, focus: str) -> dict[str, Any]:
    from deeptutor.tools.rag_tool import rag_search

    query_parts = [
        part
        for part in (
            focus,
            "key concepts, current methods, limitations, open questions, "
            "and future research directions",
        )
        if part
    ]
    return await rag_search(query=" ".join(query_parts), kb_name=kb_name)


async def _derive_queries(
    *,
    kb_name: str,
    focus: str,
    kb_summary: str,
    document_names: list[str],
    **llm_kwargs: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Ask the reasoning model for arXiv queries, with deterministic fallback."""
    context = [
        f"Knowledge base: {kb_name}",
        f"Learner focus: {focus}" if focus else "",
        f"Documents: {', '.join(document_names[:20])}" if document_names else "",
        "Summary of the existing material:",
        kb_summary[:_CONTEXT_CHARS] if kb_summary else "(retrieval returned no summary)",
    ]
    prompt = (
        'Return only a JSON object shaped as {"queries": [string, string, string]}. '
        "Each value must be a concise English arXiv keyword query that follows from the "
        "knowledge base, explores a distinct research direction, and contains no quotes "
        "or Boolean operators."
    )
    from deeptutor.tools.reason import reason

    try:
        result = await reason(
            query=prompt,
            context="\n".join(part for part in context if part),
            max_tokens=512,
            temperature=0.1,
            **llm_kwargs,
        )
        queries = _parse_queries(str(result.get("answer", "")))
        if not queries:
            return {"source": "fallback", "error": "No valid JSON queries"}, _fallback_queries(
                focus=focus, document_names=document_names
            )
        return {"source": "llm", "model": result.get("model", "")}, queries
    except Exception as exc:
        return (
            {"source": "fallback", "error": str(exc)},
            _fallback_queries(focus=focus, document_names=document_names),
        )


def _parse_queries(answer: str) -> list[str]:
    match = re.search(r"\[[\s\S]*\]", answer)
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = payload.get("queries")
    if not isinstance(payload, list):
        return []
    return _clean_queries(payload)


def _fallback_queries(*, focus: str, document_names: list[str]) -> list[str]:
    seed = focus
    if not seed and document_names:
        first_name = document_names[0].rsplit("/", 1)[-1]
        first_name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", first_name)
        seed = re.sub(r"[-_.]+", " ", first_name)
    seed = _one_line(seed, limit=120)
    if not seed:
        return ["recent research frontiers"]
    return [
        seed,
        f"recent advances {seed}",
        f"open challenges {seed}",
    ]


def _clean_queries(raw_values: Iterable[Any]) -> list[str]:
    cleaned: list[str] = []
    for value in raw_values:
        if not isinstance(value, str):
            continue
        query = _one_line(value, limit=200)
        if len(query.split()) >= 2 and query.lower() not in {item.lower() for item in cleaned}:
            cleaned.append(query)
        if len(cleaned) >= MAX_SEARCH_QUERIES:
            break
    return cleaned


async def _search_papers(
    *, queries: list[str], max_results: int, years_limit: int | None
) -> tuple[list[dict[str, Any]], list[str]]:
    searcher = ArxivSearchTool()
    papers: list[dict[str, Any]] = []
    errors: list[str] = []
    for query in queries:
        try:
            results = await searcher.search_papers(
                query=query,
                max_results=max_results,
                years_limit=years_limit,
                sort_by="relevance",
            )
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            continue
        papers.extend({**paper, "source_query": query} for paper in results)
    return _deduplicate(papers), errors


def _deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        key = (
            str(paper.get("arxiv_id", "")).strip().lower(),
            str(paper.get("title", "")).strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(paper)
    return unique


def _kb_sources(rag_result: dict[str, Any], *, kb_name: str, focus: str) -> list[dict[str, Any]]:
    retrieved = [item for item in (rag_result.get("sources") or []) if isinstance(item, dict)]
    if not retrieved:
        return [
            {
                "type": "rag",
                "query": focus or "knowledge frontier",
                "kb_name": kb_name,
            }
        ]
    return [{"type": "rag", "kb_name": kb_name, **item} for item in retrieved]


def _render_report(
    *,
    kb_name: str,
    focus: str,
    document_count: int,
    kb_summary: str,
    queries: list[str],
    papers: list[dict[str, Any]],
    query_errors: list[str],
) -> str:
    lines = [
        f"**Knowledge frontier for `{kb_name}`**",
        f"Grounded in {document_count} document(s).",
    ]
    if focus:
        lines.append(f"Focus: {focus}")
    if kb_summary:
        lines.extend(["", "Existing material summary:", kb_summary[:1600]])

    lines.extend(["", "arXiv queries used:"])
    lines.extend(f"- {query}" for query in queries)
    if query_errors:
        lines.extend(["", "Query errors:"])
        lines.extend(f"- {error}" for error in query_errors)

    if not papers:
        lines.extend(
            [
                "",
                "No recent arXiv preprints were found for these queries. "
                "Try a narrower focus or a longer year range.",
            ]
        )
        return "\n".join(lines)

    lines.extend(["", "Recent work to consider:"])
    for index, paper in enumerate(papers, start=1):
        authors = ", ".join(str(author) for author in (paper.get("authors") or [])[:4])
        abstract = " ".join(str(paper.get("abstract", "")).split())[:320]
        lines.extend(
            [
                "",
                f"{index}. **{paper.get('title', 'Untitled')}** ({paper.get('year', 'unknown')})",
                f"   Authors: {authors or 'Unknown'}",
                f"   arXiv: {paper.get('arxiv_id', 'unknown')} | URL: {paper.get('url', '')}",
                f"   Matched query: {paper.get('source_query', '')}",
            ]
        )
        if abstract:
            lines.append(f"   Abstract: {abstract}")
    lines.extend(
        [
            "",
            "These papers are recommendations, not knowledge-base contents. "
            "Review them before adding any source.",
        ]
    )
    return "\n".join(lines)


def _one_line(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit].strip()


def _clamped_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(number, maximum))
