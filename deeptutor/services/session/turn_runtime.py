"""Compatibility facade for the decomposed v2 turn services."""

from __future__ import annotations

from . import _turn_runtime_shared as _shared
from .turns import (
    LearningTurnAdapter,
    SessionTitleService,
    TurnContextAssembler,
    TurnExecutor,
    TurnLifecycle,
    TurnRequestPreparer,
)


# Preserve direct imports of normalization helpers during the v2 transition.
# PEP 562 forwards private helpers without copying the 1,200-line value layer
# back into this compatibility module.
def __getattr__(name: str):
    try:
        return getattr(_shared, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


class TurnRuntimeManager(
    TurnRequestPreparer,
    TurnContextAssembler,
    LearningTurnAdapter,
    TurnExecutor,
    TurnLifecycle,
    SessionTitleService,
):
    """Backward-compatible composition of the focused v2 turn services."""


import threading

_runtime_lock = threading.Lock()
_runtime_instances: dict[str, TurnRuntimeManager] = {}


def get_turn_runtime_manager() -> TurnRuntimeManager:
    from deeptutor.services.session import get_session_store
    from deeptutor.services.session.scope import store_scope

    store = get_session_store()
    key = store_scope(store).cache_key
    with _runtime_lock:
        if key not in _runtime_instances:
            _runtime_instances[key] = TurnRuntimeManager(store=store)
        return _runtime_instances[key]


__all__ = ["TurnRuntimeManager", "get_turn_runtime_manager"]
