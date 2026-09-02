"""
Book Engine
===========

Independent runtime engine that compiles user inputs (chat history, notebooks,
knowledge bases, intent) into structured, block-based, interactive "living
books". Sits parallel to ``ChatOrchestrator`` and reuses the existing
``ToolRegistry`` / ``CapabilityRegistry`` / ``StreamBus`` plumbing.
"""

from .engine import BookEngine, BookPausedError, get_book_engine
from .models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookInputs,
    BookProposal,
    BookStatus,
    Chapter,
    Page,
    PageStatus,
    Progress,
    Spine,
)

__all__ = [
    "BookEngine",
    "BookPausedError",
    "get_book_engine",
    "Book",
    "BookInputs",
    "BookProposal",
    "BookStatus",
    "Spine",
    "Chapter",
    "Page",
    "PageStatus",
    "Block",
    "BlockType",
    "BlockStatus",
    "Progress",
]
