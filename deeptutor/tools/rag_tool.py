"""RAG query tool — thin wrapper around :class:`RAGService`.

The chat pipeline always passes an explicit ``kb_name`` selected by the user;
this module therefore never resolves aliases or falls back to a default KB.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from deeptutor.services.rag.service import RAGService


async def rag_search(
    query: str,
    kb_name: str,
    provider: Optional[str] = None,
    kb_base_dir: Optional[str] = None,
    event_sink=None,
    **kwargs,
) -> dict:
    """Retrieve passages from ``kb_name`` and synthesise an answer.

    ``kb_name`` must match a knowledge base the current user can access;
    multi-user routing is delegated to :func:`resolve_for_rag` when no
    explicit ``kb_base_dir`` is given.
    """
    query = query.strip() if isinstance(query, str) else ""
    kb_name = kb_name.strip() if isinstance(kb_name, str) else ""
    if not query:
        raise ValueError("RAG query must be a non-empty string.")
    if not kb_name:
        raise ValueError("RAG requires an explicit kb_name.")

    if kb_base_dir is None:
        from deeptutor.multi_user.knowledge_access import resolve_for_rag

        resource = resolve_for_rag(kb_name)
        if resource is None:
            raise ValueError(f"Knowledge base '{kb_name}' is not accessible.")
        kb_base_dir = str(resource.base_dir)
        kb_name = resource.name

    service = RAGService(kb_base_dir=kb_base_dir, provider=provider)
    return await service.search(
        query=query,
        kb_name=kb_name,
        event_sink=event_sink,
        **kwargs,
    )


async def initialize_rag(
    kb_name: str,
    documents: List[str],
    provider: Optional[str] = None,
    kb_base_dir: Optional[str] = None,
    **kwargs,
) -> bool:
    """Index ``documents`` into ``kb_name`` using the configured RAG pipeline."""
    service = RAGService(kb_base_dir=kb_base_dir, provider=provider)
    return await service.initialize(kb_name=kb_name, file_paths=documents, **kwargs)


async def delete_rag(
    kb_name: str,
    provider: Optional[str] = None,
    kb_base_dir: Optional[str] = None,
) -> bool:
    """Delete the knowledge base ``kb_name``."""
    service = RAGService(kb_base_dir=kb_base_dir, provider=provider)
    return await service.delete(kb_name=kb_name)


def get_available_providers() -> List[Dict]:
    return RAGService.list_providers()


def get_current_provider() -> str:
    return RAGService.get_current_provider()


# Backward-compat aliases used by a few callers / tests
get_available_plugins = get_available_providers
list_providers = RAGService.list_providers


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("Available RAG Pipelines:")
    for provider in get_available_providers():
        print(f"  - {provider['id']}: {provider['description']}")
    print(f"\nCurrent provider: {get_current_provider()}\n")

    result = asyncio.run(
        rag_search(
            "What is the lookup table (LUT) in FPGA?",
            kb_name="DE-all",
        )
    )
    print(f"Query: {result['query']}")
    print(f"Answer: {result['answer']}")
    print(f"Provider: {result.get('provider', 'unknown')}")
