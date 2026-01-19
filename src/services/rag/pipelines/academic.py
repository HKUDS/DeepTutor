# -*- coding: utf-8 -*-
"""
Academic Pipeline
=================

Pipeline optimized for academic documents with numbered item extraction.
"""

from typing import Optional

from ..components.chunkers import NumberedItemExtractor, SemanticChunker
from ..components.embedders import OpenAIEmbedder
from ..components.indexers import GraphIndexer
from ..components.parsers import TextParser
from ..components.retrievers import HybridRetriever
from ..pipeline import RAGPipeline


def AcademicPipeline(kb_base_dir: Optional[str] = None) -> RAGPipeline:
    """
    Create an academic document pipeline.

    This pipeline uses:
    - TextParser for document parsing (supports txt, md files)
    - SemanticChunker for text chunking
    - NumberedItemExtractor for extracting definitions, theorems, etc.
    - OpenAIEmbedder for embedding generation
    - GraphIndexer for knowledge graph indexing
    - HybridRetriever for hybrid retrieval

    Args:
        kb_base_dir: Base directory for knowledge bases

    Returns:
        Configured RAGPipeline
    """
    return (
        RAGPipeline("academic", kb_base_dir=kb_base_dir)
        .parser(TextParser())
        .chunker(SemanticChunker())
        .chunker(NumberedItemExtractor())
        .embedder(OpenAIEmbedder())
        .indexer(GraphIndexer(kb_base_dir=kb_base_dir))
        .retriever(HybridRetriever(kb_base_dir=kb_base_dir))
    )
