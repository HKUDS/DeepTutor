# -*- coding: utf-8 -*-
"""
RAG Types
=========

Data types for the RAG pipeline.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Chunk:
    """
    Document chunk.

    Represents a portion of a document with optional metadata and embedding.
    """

    content: str
    chunk_type: str = "text"  # text, definition, theorem, equation, figure, table...
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class Document:
    """
    Parsed document.

    Contains the full document content, metadata, and chunks.
    """

    content: str
    file_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunks: List[Chunk] = field(default_factory=list)
    content_items: List[Dict] = field(default_factory=list)  # MinerU format

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.chunks is None:
            self.chunks = []
        if self.content_items is None:
            self.content_items = []

    def add_chunk(self, chunk: Chunk):
        """Add a chunk to the document."""
        self.chunks.append(chunk)

    def get_chunks_by_type(self, chunk_type: str) -> List[Chunk]:
        """Get all chunks of a specific type."""
        return [c for c in self.chunks if c.chunk_type == chunk_type]


@dataclass
class SearchResult:
    """
    Search result from RAG query.
    """

    query: str
    answer: str
    content: str
    mode: str = "hybrid"
    provider: str = "raganything"
    chunks: List[Chunk] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
