# -*- coding: utf-8 -*-
"""
LightRAG Pipeline
=================

Pure LightRAG pipeline (text-only, no multimodal processing).
Faster than RAGAnything for text-heavy documents.
"""

from typing import Optional

from ..components.indexers import LightRAGIndexer
from ..components.parsers import PDFParser
from ..components.retrievers import LightRAGRetriever
from ..pipeline import RAGPipeline


def LightRAGPipeline(kb_base_dir: Optional[str] = None) -> RAGPipeline:
    """
    Create a pure LightRAG pipeline (text-only, no multimodal).

    This pipeline uses:
    - PDFParser for document parsing (extracts raw text from PDF/txt/md)
    - LightRAGIndexer for knowledge graph indexing (text-only, fast)
      * LightRAG handles chunking, entity extraction, and embedding internally
      * No separate chunker/embedder needed - LightRAG does it all
    - LightRAGRetriever for retrieval (uses LightRAG.aquery() directly)

    Performance: Medium speed (~10-15s per document)
    Use for: Business docs, text-heavy PDFs, when you need knowledge graph

    Args:
        kb_base_dir: Base directory for knowledge bases

    Returns:
        Configured RAGPipeline
    """
    return (
        RAGPipeline("lightrag", kb_base_dir=kb_base_dir)
        .parser(PDFParser())
        # No chunker/embedder - LightRAG does everything internally
        .indexer(LightRAGIndexer(kb_base_dir=kb_base_dir))
        .retriever(LightRAGRetriever(kb_base_dir=kb_base_dir))
    )
