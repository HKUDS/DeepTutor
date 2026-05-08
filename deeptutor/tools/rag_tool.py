#!/usr/bin/env python
"""
RAG Query Tool - Pure tool wrapper for RAG operations

This module provides simple function wrappers for RAG operations.
All logic is delegated to RAGService in deeptutor/services/rag/service.py.
"""

import asyncio
from typing import Dict, List, Optional

# Import RAGService as the single entry point
from deeptutor.services.rag.service import DEFAULT_KB_BASE_DIR, RAGService

DEFAULT_KB_ALIASES = {"", "default", "current", "selected", "默认", "默认知识库", "当前知识库"}


def _resolve_kb_name(kb_name: Optional[str], kb_base_dir: Optional[str] = None) -> Optional[str]:
    """Resolve generic/default KB aliases to the configured default KB."""
    requested = str(kb_name or "").strip()
    try:
        from deeptutor.knowledge.manager import KnowledgeBaseManager

        manager = KnowledgeBaseManager(base_dir=kb_base_dir or DEFAULT_KB_BASE_DIR)
        kb_names = manager.list_knowledge_bases()
        if requested and requested in kb_names:
            return requested
        if requested.lower() in DEFAULT_KB_ALIASES:
            default_kb = manager.get_default()
            if default_kb:
                return default_kb
    except Exception:
        # Keep tool startup lightweight; the service will surface a concrete
        # retrieval error if the KB cannot be resolved from disk.
        pass
    return requested or None


async def rag_search(
    query: str,
    kb_name: Optional[str] = None,
    provider: Optional[str] = None,
    kb_base_dir: Optional[str] = None,
    event_sink=None,
    **kwargs,
) -> dict:
    """
    Query knowledge base using LlamaIndex RAG pipeline.

    Args:
        query: Query question
        kb_name: Knowledge base name (optional, defaults to default knowledge base)
        provider: RAG pipeline to use (defaults to configured provider or "llamaindex")
        kb_base_dir: Base directory for knowledge bases (for testing)
        **kwargs: Additional parameters passed to the RAG pipeline

    Returns:
        dict: Dictionary containing query results
            {
                "query": str,
                "answer": str,
                "content": str,
                "sources": list,
                "provider": str
            }
    """
    query = str(query or "").strip()
    if not query:
        raise ValueError("RAG query must be a non-empty string.")

    if kb_base_dir is None:
        try:
            from deeptutor.multi_user.context import get_current_user
            from deeptutor.multi_user.knowledge_access import resolve_for_rag

            resource = resolve_for_rag(kb_name)
            if resource is not None:
                kb_base_dir = str(resource.base_dir)
                kb_name = resource.name
            elif not get_current_user().is_admin:
                # Non-admin users must never silently fall back to admin's KB
                # directory. ``resolve_for_rag`` returning ``None`` means the
                # caller passed no kb_name at all — surface that as a
                # configuration error instead of leaking admin KBs.
                raise ValueError(
                    "No knowledge base selected. Pass kb_name explicitly or set a default."
                )
        except ValueError:
            raise
        except Exception as exc:
            if getattr(exc, "status_code", None) in {403, 404}:
                raise
            # Fall back to the legacy resolver so CLI/local single-user remains
            # tolerant when no request context exists. This branch only runs
            # for admin / single-user mode (the non-admin path raised above).
            pass

    service = RAGService(kb_base_dir=kb_base_dir, provider=provider)
    resolved_kb_name = _resolve_kb_name(kb_name, kb_base_dir=kb_base_dir)
    if not resolved_kb_name:
        raise ValueError("No knowledge base selected and no default knowledge base is configured.")

    try:
        return await service.search(
            query=query,
            kb_name=resolved_kb_name,
            event_sink=event_sink,
            **kwargs,
        )
    except Exception as e:
        raise Exception(f"RAG search failed: {e}")


async def initialize_rag(
    kb_name: str,
    documents: List[str],
    provider: Optional[str] = None,
    kb_base_dir: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    Initialize RAG with documents.

    Args:
        kb_name: Knowledge base name
        documents: List of document file paths to index
        provider: RAG pipeline to use (defaults to configured provider)
        kb_base_dir: Base directory for knowledge bases (for testing)
        **kwargs: Additional arguments passed to pipeline

    Returns:
        True if successful

    Example:
        documents = ["doc1.pdf", "doc2.txt"]
        success = await initialize_rag("my_kb", documents)
    """
    service = RAGService(kb_base_dir=kb_base_dir, provider=provider)
    return await service.initialize(kb_name=kb_name, file_paths=documents, **kwargs)


async def delete_rag(
    kb_name: str,
    provider: Optional[str] = None,
    kb_base_dir: Optional[str] = None,
) -> bool:
    """
    Delete a knowledge base.

    Args:
        kb_name: Knowledge base name
        provider: RAG pipeline to use (defaults to configured provider)
        kb_base_dir: Base directory for knowledge bases (for testing)

    Returns:
        True if successful

    Example:
        success = await delete_rag("old_kb")
    """
    service = RAGService(kb_base_dir=kb_base_dir, provider=provider)
    return await service.delete(kb_name=kb_name)


def get_available_providers() -> List[Dict]:
    """
    Get list of available RAG pipelines.

    Returns:
        List of pipeline information dictionaries

    Example:
        providers = get_available_providers()
        for p in providers:
            print(f"{p['name']}: {p['description']}")
    """
    return RAGService.list_providers()


def get_current_provider() -> str:
    """Get the currently configured RAG provider"""
    return RAGService.get_current_provider()


# Backward compatibility aliases
get_available_plugins = get_available_providers
list_providers = RAGService.list_providers


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # List available providers
    print("Available RAG Pipelines:")
    for provider in get_available_providers():
        print(f"  - {provider['id']}: {provider['description']}")
    print(f"\nCurrent provider: {get_current_provider()}\n")

    # Test search (requires existing knowledge base)
    result = asyncio.run(
        rag_search(
            "What is the lookup table (LUT) in FPGA?",
            kb_name="DE-all",
        )
    )

    print(f"Query: {result['query']}")
    print(f"Answer: {result['answer']}")
    print(f"Provider: {result.get('provider', 'unknown')}")
