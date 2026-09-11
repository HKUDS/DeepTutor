"""Runtime orchestration and registry helpers.

Importing a leaf module such as :mod:`deeptutor.runtime.memory_probe` must not
bootstrap the agent, tool, and capability graphs.  ``ChatOrchestrator`` is a
compatibility export, resolved only when a caller asks for it.
"""

from __future__ import annotations

from .mode import RunMode, get_mode, is_cli, is_server, set_mode

__all__ = [
    "ChatOrchestrator",
    "RunMode",
    "get_mode",
    "is_cli",
    "is_server",
    "set_mode",
]


def __getattr__(name: str):
    if name == "ChatOrchestrator":
        from .orchestrator import ChatOrchestrator

        globals()[name] = ChatOrchestrator
        return ChatOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
