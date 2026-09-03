"""
Book Engine
===========

Independent runtime engine that compiles user inputs (chat history, notebooks,
knowledge bases, intent) into structured, block-based, interactive "living
books". Sits parallel to ``ChatOrchestrator`` and reuses the existing
``ToolRegistry`` / ``CapabilityRegistry`` / ``StreamBus`` plumbing.
"""

from importlib import import_module

_MODEL_EXPORTS = {
    "Block",
    "BlockStatus",
    "BlockType",
    "Book",
    "BookInputs",
    "BookProposal",
    "BookStatus",
    "Chapter",
    "Page",
    "PageStatus",
    "Progress",
    "Spine",
}
_ENGINE_EXPORTS = {"BookEngine", "get_book_engine"}


def __getattr__(name: str):
    if name in _MODEL_EXPORTS:
        value = getattr(import_module(f"{__name__}.models"), name)
    elif name in _ENGINE_EXPORTS:
        value = getattr(import_module(f"{__name__}.engine"), name)
    elif name == "BookPausedError":
        value = getattr(import_module(f"{__name__}.errors"), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


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
