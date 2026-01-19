# -*- coding: utf-8 -*-
"""
Base Chunker
============

Base class for document chunkers.
"""

from typing import List

from ...types import Chunk, Document
from ..base import BaseComponent


class BaseChunker(BaseComponent):
    """
    Base class for document chunkers.

    Chunkers split documents into smaller chunks for processing.
    """

    name = "base_chunker"

    async def process(self, doc: Document, **kwargs) -> List[Chunk]:
        """
        Chunk a document.

        Args:
            doc: Document to chunk
            **kwargs: Additional arguments

        Returns:
            List of Chunks
        """
        raise NotImplementedError("Subclasses must implement process()")
