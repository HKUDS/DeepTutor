# -*- coding: utf-8 -*-
"""
Fixed Size Chunker
==================

Chunker that splits documents into fixed-size pieces.
"""

from typing import List

from ...types import Chunk, Document
from ..base import BaseComponent


class FixedSizeChunker(BaseComponent):
    """
    Fixed-size chunker.

    Splits documents into chunks of a fixed size with optional overlap.
    """

    name = "fixed_size_chunker"

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100):
        """
        Initialize fixed-size chunker.

        Args:
            chunk_size: Size of each chunk in characters
            chunk_overlap: Overlap between chunks
        """
        super().__init__()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def process(self, doc: Document, **kwargs) -> List[Chunk]:
        """
        Chunk a document into fixed-size pieces.

        Args:
            doc: Document to chunk
            **kwargs: Additional arguments

        Returns:
            List of fixed-size Chunks
        """
        self.logger.info(f"Chunking document: {doc.file_path or 'inline'}")

        text = doc.content
        if not text:
            return []

        chunks = []
        step = self.chunk_size - self.chunk_overlap

        for i in range(0, len(text), step):
            chunk_text = text[i : i + self.chunk_size].strip()
            if chunk_text:
                chunks.append(
                    Chunk(
                        content=chunk_text,
                        chunk_type="text",
                        metadata={
                            "start_pos": i,
                            "end_pos": min(i + self.chunk_size, len(text)),
                            "source": doc.file_path,
                        },
                    )
                )

        self.logger.info(f"Created {len(chunks)} chunks")
        return chunks
