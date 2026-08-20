"""Load an entry-point group without letting one bad plugin take the app down.

DeepTutor exposes two plugin groups — ``deeptutor.plugins`` for capabilities the
registry can run, ``deeptutor.loop_capabilities`` for chat-loop capabilities —
and both need the same plumbing: read the group, import each target, hand it to
a group-specific coercer, and skip whatever fails with a warning naming the
entry point. Only the coercer differs, so only the coercer lives at the call
site.

Third-party code runs at import time here, which is what an entry point is; the
guarantee this module makes is narrower and worth stating plainly: a plugin that
raises cannot stop the others from loading.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
import logging
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def load_entry_point_group(
    group: str,
    coerce: Callable[[str, Any], T | None],
    *,
    log: logging.Logger | None = None,
) -> list[T]:
    """Return every ``group`` entry point that imports and coerces cleanly.

    ``coerce`` receives ``(entry_point_name, loaded_object)`` and returns the
    value to keep, or ``None`` to reject it — a rejection is the coercer's own
    judgement, so it is expected to say why. Anything raised while importing or
    coercing is logged against that entry point's name and skipped.
    """
    out: list[T] = []
    emit = log or logger
    try:
        discovered = list(entry_points(group=group))
    except Exception:
        emit.warning("Failed to read %s entry points; no plugins loaded.", group, exc_info=True)
        return out

    for ep in discovered:
        name = getattr(ep, "name", str(ep))
        try:
            value = coerce(name, ep.load())
        except Exception:
            emit.warning("Failed to load %s entry point %r; skipping.", group, name, exc_info=True)
            continue
        if value is not None:
            out.append(value)
    return out


__all__ = ["load_entry_point_group"]
