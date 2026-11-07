# -*- coding: utf-8 -*-
"""
Document Chunkers
=================

Chunkers for splitting documents into smaller pieces.
"""

from .base import BaseChunker
from .fixed import FixedSizeChunker
from .numbered_item import NumberedItemExtractor
from .semantic import SemanticChunker

__all__ = [
    "BaseChunker",
    "SemanticChunker",
    "FixedSizeChunker",
    "NumberedItemExtractor",
]
