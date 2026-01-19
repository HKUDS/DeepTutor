# -*- coding: utf-8 -*-
"""
Pre-configured Pipelines
========================

Ready-to-use RAG pipelines for common use cases.
"""

from .academic import AcademicPipeline
from .lightrag import LightRAGPipeline
from .llamaindex import LlamaIndexPipeline
from .raganything import RAGAnythingPipeline
from .raganything_docling import RAGAnythingDoclingPipeline

__all__ = [
    "RAGAnythingPipeline",
    "RAGAnythingDoclingPipeline",
    "LightRAGPipeline",
    "LlamaIndexPipeline",
    "AcademicPipeline",
]
