#!/usr/bin/env python
"""
RAG Query Tool - Pure tool wrapper for RAG operations

This module provides simple function wrappers for RAG operations.
All logic is delegated to RAGService in src/services/rag/service.py.
"""

import asyncio
from pathlib import Path
import sys
from typing import Dict, List, Optional

from dotenv import load_dotenv

# Load environment variables
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
load_dotenv(project_root / "DeepTutor.env", override=False)
load_dotenv(project_root / ".env", override=False)

# Import RAGService as the single entry point
from src.services.rag.service import RAGService


async def rag_search(
    query: str,
    kb_name: Optional[str] = None,
    mode: str = "hybrid",
    provider: Optional[str] = None,
    kb_base_dir: Optional[str] = None,
    **kwargs,
) -> dict:
    """
    Query knowledge base using configurable RAG pipeline.

    Args:
        query: Query question
        kb_name: Knowledge base name (optional, defaults to default knowledge base)
        mode: Query mode (e.g., "hybrid", "local", "global", "naive")
        provider: RAG pipeline to use (defaults to RAG_PROVIDER env var or "raganything")
        kb_base_dir: Base directory for knowledge bases (for testing)
        **kwargs: Additional parameters passed to the RAG pipeline

    Returns:
        dict: Dictionary containing query results
            {
                "query": str,
                "answer": str,
                "content": str,
                "mode": str,
                "provider": str
            }

    Raises:
        ValueError: If the specified RAG pipeline is not found
        Exception: If the query fails

    Example:
        # Use default provider (from .env)
        result = await rag_search("What is machine learning?", kb_name="textbook")

        # Override provider
        result = await rag_search("What is ML?", kb_name="textbook", provider="lightrag")
    """
    service = RAGService(kb_base_dir=kb_base_dir, provider=provider)

    try:
        return await service.search(query=query, kb_name=kb_name, mode=mode, **kwargs)
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
        provider: RAG pipeline to use (defaults to RAG_PROVIDER env var)
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
        provider: RAG pipeline to use (defaults to RAG_PROVIDER env var)
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
    import argparse
    import sys
    import time

    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="RAG tool quick test")
    parser.add_argument(
        "--kb-name",
        default="DE-all",
        help="Knowledge base name for test query (default: DE-all)",
    )
    parser.add_argument(
        "--query",
        default="What is this knowledge base about?",
        help="Test query text",
    )
    parser.add_argument(
        "--mode",
        default="hybrid",
        help="RAG mode: naive/hybrid/local/global (default: hybrid)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override RAG provider id (optional)",
    )
    parser.add_argument(
        "--kb-base-dir",
        default=None,
        help="Override KB base directory (optional)",
    )
    args = parser.parse_args()
    started = time.perf_counter()

    # List available providers
    provider_started = time.perf_counter()
    print("Available RAG Pipelines:")
    for provider in get_available_providers():
        print(f"  - {provider['id']}: {provider['description']}")
    print(f"\nCurrent provider: {get_current_provider()}\n")
    print(f"[Timing] list_providers={(time.perf_counter() - provider_started):.2f}s")

    # Test search (requires existing knowledge base)
    search_started = time.perf_counter()
    result = asyncio.run(
        rag_search(
            args.query,
            kb_name=args.kb_name,
            mode=args.mode,
            provider=args.provider,
            kb_base_dir=args.kb_base_dir,
        )
    )
    print(f"[Timing] rag_search={(time.perf_counter() - search_started):.2f}s")

    print(f"Query: {result['query']}")
    print(f"Answer: {result['answer']}")
    print(f"Provider: {result.get('provider', 'unknown')}")
    print(f"[Timing] total={(time.perf_counter() - started):.2f}s")
