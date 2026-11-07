# -*- coding: utf-8 -*-
"""
RAG Service
===========

Unified RAG pipeline service for DeepTutor.

Provides:
- RAGService: Unified entry point for all RAG operations
- Composable RAG pipelines
- Pre-configured pipelines (RAGAnything, LightRAG, LlamaIndex)
- Modular components (parsers, chunkers, embedders, indexers, retrievers)
- Factory for pipeline creation

Usage:
    # Recommended: Use RAGService for all operations
    from src.services.rag import RAGService

    service = RAGService(provider="llamaindex")
    await service.initialize("kb_name", ["doc1.txt", "doc2.txt"])
    result = await service.search("query", "kb_name")

    # Alternative: Use factory directly
    from src.services.rag import get_pipeline

    pipeline = get_pipeline("raganything")
    await pipeline.initialize("kb_name", ["doc1.pdf"])
    result = await pipeline.search("query", "kb_name")

    # Or build custom pipeline
    from src.services.rag import RAGPipeline
    from src.services.rag.components import TextParser, SemanticChunker

    custom = (
        RAGPipeline("custom")
        .parser(TextParser())
        .chunker(SemanticChunker())
    )
"""

from .factory import get_pipeline, has_pipeline, list_pipelines, register_pipeline
from .pipeline import RAGPipeline
from .service import RAGService
from .types import Chunk, Document, SearchResult


# Lazy import for RAGAnythingPipeline to avoid importing heavy dependencies at module load time
def __getattr__(name: str):
    """Lazy import for pipeline classes that depend on heavy libraries."""
    if name == "RAGAnythingPipeline":
        from .pipelines.raganything import RAGAnythingPipeline

        return RAGAnythingPipeline
    if name == "RAGAnythingDoclingPipeline":
        from .pipelines.raganything_docling import RAGAnythingDoclingPipeline

        return RAGAnythingDoclingPipeline
    if name == "LlamaIndexPipeline":
        # Optional dependency: llama_index
        from .pipelines.llamaindex import LlamaIndexPipeline

        return LlamaIndexPipeline
    if name == "LightRAGPipeline":
        from .pipelines.lightrag import LightRAGPipeline

        return LightRAGPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Service (recommended entry point)
    "RAGService",
    # Types
    "Document",
    "Chunk",
    "SearchResult",
    # Pipeline
    "RAGPipeline",
    # Factory
    "get_pipeline",
    "list_pipelines",
    "register_pipeline",
    "has_pipeline",
    # Pipeline implementations (lazy loaded)
    "RAGAnythingPipeline",
]
