#!/usr/bin/env python
"""Knowledge base package exports (lazy-loaded)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "DocumentAdder",
    "KbBusyError",
    "KbWriteCoordinator",
    "KnowledgeBaseInitializer",
    "KnowledgeBaseManager",
]


def __getattr__(name: str) -> Any:
    if name == "DocumentAdder":
        from .add_documents import DocumentAdder

        return DocumentAdder
    if name == "KbBusyError":
        from .write_coordinator import KbBusyError

        return KbBusyError
    if name == "KbWriteCoordinator":
        from .write_coordinator import KbWriteCoordinator

        return KbWriteCoordinator
    if name == "KnowledgeBaseInitializer":
        from .initializer import KnowledgeBaseInitializer

        return KnowledgeBaseInitializer
    if name == "KnowledgeBaseManager":
        from .manager import KnowledgeBaseManager

        return KnowledgeBaseManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
