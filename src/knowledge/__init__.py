#!/usr/bin/env python
"""
Knowledge Base Initialization Module

Includes:
- init_knowledge_base: Knowledge base initializer
- add_documents: Incremental document addition (new feature)
- kb_manager: Knowledge base manager
- extract_numbered_items: Extract numbered items
- config: Path configuration
"""

from . import config
from .add_documents import DocumentAdder
from .initializer import KnowledgeBaseInitializer
from .manager import KnowledgeBaseManager

__all__ = [
    "DocumentAdder",
    "KnowledgeBaseInitializer",
    "KnowledgeBaseManager",
    "config",
]
