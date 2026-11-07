# -*- coding: utf-8 -*-
"""
Semantic Chunker
================

Chunker that splits documents based on semantic boundaries.
"""

from typing import List

from ...types import Chunk, Document
from ..base import BaseComponent


class SemanticChunker(BaseComponent):
    """
    Semantic chunker.

    Splits documents based on semantic boundaries like paragraphs,
    sections, or natural breakpoints.
    """

    name = "semantic_chunker"

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: List[str] = None,
    ):
        """
        Initialize semantic chunker.

        Args:
            chunk_size: Target chunk size in characters
            chunk_overlap: Overlap between chunks
            separators: List of separators to split on
        """
        super().__init__()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " "]

    async def process(self, doc: Document, **kwargs) -> List[Chunk]:
        """
        Chunk a document semantically.

        Args:
            doc: Document to chunk
            **kwargs: Additional arguments

        Returns:
            List of semantic Chunks
        """
        self.logger.info(f"Chunking document: {doc.file_path or 'inline'}")

        text = doc.content
        if not text:
            return []

        chunks = []
        current_pos = 0

        while current_pos < len(text):
            # Find chunk end
            end_pos = min(current_pos + self.chunk_size, len(text))

            # Try to find a natural break point
            if end_pos < len(text):
                for sep in self.separators:
                    # Look for separator in the last portion of the chunk
                    search_start = max(current_pos + self.chunk_size - 200, current_pos)
                    sep_pos = text.rfind(sep, search_start, end_pos)
                    if sep_pos > current_pos:
                        end_pos = sep_pos + len(sep)
                        break

            chunk_text = text[current_pos:end_pos].strip()
            if chunk_text:
                chunks.append(
                    Chunk(
                        content=chunk_text,
                        chunk_type="text",
                        metadata={
                            "start_pos": current_pos,
                            "end_pos": end_pos,
                            "source": doc.file_path,
                        },
                    )
                )

            # Move to next position with overlap
            current_pos = end_pos - self.chunk_overlap
            if current_pos >= len(text) - self.chunk_overlap:
                break

        self.logger.info(f"Created {len(chunks)} chunks")
        return chunks
