# -*- coding: utf-8 -*-
"""
Base Indexer
============

Base class for document indexers.
"""

from typing import List

from ...types import Document
from ..base import BaseComponent


class BaseIndexer(BaseComponent):
    """
    Base class for document indexers.

    Indexers build searchable indexes from documents.
    """

    name = "base_indexer"

    async def process(self, kb_name: str, documents: List[Document], **kwargs) -> bool:
        """
        Index documents into a knowledge base.

        Args:
            kb_name: Knowledge base name
            documents: List of documents to index
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        raise NotImplementedError("Subclasses must implement process()")
