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
from importlib.metadata import EntryPoint, entry_points
import logging
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _module_entry_points(group: str) -> dict[tuple[str, str], bool]:
    from deeptutor.modules.catalog import manifests, module_enabled

    return {
        (name, target): module_enabled(module)
        for module, manifest in manifests().items()
        for name, target in manifest.get("entry_points", {}).get(group, {}).items()
    }


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

    from deeptutor.modules.catalog import source_checkout

    official = _module_entry_points(group)
    if source_checkout():
        # Editable core installs do not own optional modules' wheel metadata.
        # Add their declared entries without duplicating installed module wheels.
        packaged = {(ep.name, getattr(ep, "value", None)) for ep in discovered}
        discovered.extend(
            EntryPoint(name=name, value=target, group=group)
            for (name, target), enabled in official.items()
            if enabled and (name, target) not in packaged
        )

    for ep in discovered:
        name = getattr(ep, "name", str(ep))
        try:
            identity = (name, getattr(ep, "value", None))
            if identity in official:
                # Official code is governed by module selection, while external
                # distributions retain the plugin approval/revocation checks.
                if official[identity]:
                    value = coerce(name, ep.load())
                    if value is not None:
                        out.append(value)
                continue
            from deeptutor.plugins.runtime import entry_point_can_load, guard_entry_point_loaded

            if not entry_point_can_load(ep, group):
                emit.warning(
                    "Plugin entry point %r is disabled, incompatible or unapproved; skipping import.",
                    name,
                )
                continue
            value = coerce(name, guard_entry_point_loaded(ep, group, ep.load()))
        except Exception:
            emit.warning("Failed to load %s entry point %r; skipping.", group, name, exc_info=True)
            continue
        if value is not None:
            out.append(value)
    return out


__all__ = ["load_entry_point_group"]
