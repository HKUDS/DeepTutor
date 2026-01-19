# -*- coding: utf-8 -*-
"""
Base Embedder
=============

Base class for document embedders.
"""

from ...types import Document
from ..base import BaseComponent


class BaseEmbedder(BaseComponent):
    """
    Base class for document embedders.

    Embedders generate vector representations for document chunks.
    """

    name = "base_embedder"

    async def process(self, doc: Document, **kwargs) -> Document:
        """
        Embed a document's chunks.

        Args:
            doc: Document with chunks to embed
            **kwargs: Additional arguments

        Returns:
            Document with embedded chunks
        """
        raise NotImplementedError("Subclasses must implement process()")
