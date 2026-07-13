"""Path resolution for the three-layer memory subsystem.

Layout under the per-user memory root::

    trace/<surface>/<YYYY-MM-DD>.jsonl    (L1, append-only)
    L2/<surface>.md                       (L2, per-surface summaries)
    L3/<recent|profile|scope|preferences>.md  (L3, cross-surface)
    backup/<timestamp>/...                (v1 migration archive)

The root itself is resolved via :class:`PathService` so the multi-user
context (workspace_root) is picked up at call time, not import time.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Literal, get_args

from deeptutor.services.path_service import get_path_service

if TYPE_CHECKING:
    from deeptutor.services.path_service import PathService

# When set, memory paths resolve through this PathService instead of the active
# user's. A partner runtime installs the *owner's* (admin) service for the
# duration of a turn so the chat agent's ``read_memory`` / ``write_memory``
# tools see the owner's memory — not the partner's own (empty) scope — while
# every *other* service (rag / skills / notebooks) stays on the partner scope.
_memory_path_service: ContextVar[PathService | None] = ContextVar(
    "memory_path_service", default=None
)


@contextlib.contextmanager
def memory_path_service_override(service: PathService) -> Iterator[None]:
    """Resolve memory paths through *service* within this context."""
    token = _memory_path_service.set(service)
    try:
        yield
    finally:
        _memory_path_service.reset(token)


Surface = Literal[
    "chat",
    "notebook",
    "quiz",
    "kb",
    "book",
    "partner",
    "cowriter",
]
L3Slot = Literal["recent", "profile", "scope", "preferences"]

SURFACES: tuple[Surface, ...] = get_args(Surface)
L3_SLOTS: tuple[L3Slot, ...] = get_args(L3Slot)


def memory_root() -> Path:
    override = _memory_path_service.get()
    service = override if override is not None else get_path_service()
    return service.get_memory_dir()


def trace_dir(surface: Surface) -> Path:
    return memory_root() / "trace" / surface


def trace_file(surface: Surface, day: date) -> Path:
    return trace_dir(surface) / f"{day.isoformat()}.jsonl"


def l2_dir() -> Path:
    return memory_root() / "L2"


def l2_file(surface: Surface) -> Path:
    return l2_dir() / f"{surface}.md"


def l3_dir() -> Path:
    return memory_root() / "L3"


def l3_file(slot: L3Slot) -> Path:
    return l3_dir() / f"{slot}.md"


def backup_root() -> Path:
    return memory_root() / "backup"


def ensure_dirs() -> None:
    """Create the directory skeleton. Idempotent."""
    root = memory_root()
    root.mkdir(parents=True, exist_ok=True)
    l2_dir().mkdir(parents=True, exist_ok=True)
    l3_dir().mkdir(parents=True, exist_ok=True)
    for surface in SURFACES:
        trace_dir(surface).mkdir(parents=True, exist_ok=True)
