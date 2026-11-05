"""Higher-level multi-query retrieval helpers built on top of RAGService."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import re
from typing import Any, Dict, List, Optional

SearchFunc = Callable[..., Awaitable[Dict[str, Any]]]

# A leading ordered ("1. ", "2) ") or unordered ("- ", "* ") list marker.
_LIST_MARKER_RE = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+")


class SmartRetriever:
    """Generate query variants, retrieve passages, and aggregate them."""

    def __init__(self, search: SearchFunc):
        self._search = search

    async def retrieve(
        self,
        context: str,
        kb_name: str,
        query_hints: Optional[List[str]] = None,
        max_queries: int = 3,
    ) -> Dict[str, Any]:
        queries = query_hints if query_hints else await self._generate_queries(context, max_queries)
        results = await asyncio.gather(
            *(self._search(query=q, kb_name=kb_name) for q in queries),
            return_exceptions=True,
        )

        passages: list[str] = []
        all_sources: list[dict] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            content = result.get("content") or result.get("answer") or ""
            if content:
                passages.append(content)
                all_sources.append(
                    {"query": result.get("query", ""), "provider": result.get("provider", "")}
                )

        if not passages:
            return {"answer": "", "sources": []}

        aggregated = await self._aggregate(context, passages)
        return {"answer": aggregated, "sources": all_sources}

    async def _generate_queries(self, context: str, n: int) -> list[str]:
        try:
            from deeptutor.services.llm import complete

            prompt = (
                f"Generate {n} diverse search queries to retrieve information relevant "
                f"to the following context. Return ONLY the queries, one per line.\n\n"
                f"Context:\n{context[:2000]}"
            )
            raw = await complete(prompt, system_prompt="You are a search query generator.")
            lines = [
                _LIST_MARKER_RE.sub("", line.strip())
                for line in raw.strip().split("\n")
                if line.strip()
            ]
            return lines[:n] if lines else [context[:200]]
        except Exception:
            return [context[:200]]

    async def _aggregate(self, context: str, passages: list[str]) -> str:
        try:
            from deeptutor.services.llm import complete

            combined = "\n---\n".join(passages)
            prompt = (
                "Synthesise the following retrieved passages into a concise, "
                "relevant summary for the given context.\n\n"
                f"Context:\n{context[:1000]}\n\n"
                f"Passages:\n{combined[:6000]}"
            )
            return await complete(prompt, system_prompt="You are a knowledge synthesiser.")
        except Exception:
            return "\n\n".join(passages)
