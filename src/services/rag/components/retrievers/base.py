# -*- coding: utf-8 -*-
"""
Base Retriever
==============

Base class for document retrievers.
"""

from typing import Any, Dict

from ..base import BaseComponent


class BaseRetriever(BaseComponent):
    """
    Base class for document retrievers.

    Retrievers search indexed documents and return relevant results.
    """

    name = "base_retriever"

    async def process(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        """
        Search for documents matching a query.

        Args:
            query: Search query
            kb_name: Knowledge base name
            **kwargs: Additional arguments

        Returns:
            Search results dictionary
        """
        raise NotImplementedError("Subclasses must implement process()")
