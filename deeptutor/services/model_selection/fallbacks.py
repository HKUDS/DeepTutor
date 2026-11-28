"""Read-only view of the deployment's fallback providers (issue #2693, P0).

P0 is visibility only: DeepTutor still runs the one active model. This module
answers "how many alternatives are already configured?" so a failed turn can
say so instead of a bare "please retry".

The real failover (ordered candidates, cooldown, failback) is a later phase and
does not use anything here beyond the same catalog key.
"""

from __future__ import annotations

from typing import Any

#: ``services.llm`` key holding the ordered fallback list. Bounded here too:
#: a hand-edited file must not be able to make this scan unbounded.
FALLBACKS_KEY = "fallbacks"

#: Mirrors the planned chain cap. Visibility never needs more than this.
MAX_FALLBACKS = 4


def _entry(value: Any) -> dict[str, str] | None:
    """One well-formed ``{profile_id, model_id}`` entry, or ``None``."""
    if not isinstance(value, dict):
        return None
    profile_id = str(value.get("profile_id") or "").strip()
    model_id = str(value.get("model_id") or "").strip()
    if not profile_id or not model_id:
        return None
    return {"profile_id": profile_id, "model_id": model_id}


def configured_fallbacks(catalog: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """The fallback entries the catalog declares, de-duplicated and bounded.

    Tolerant on purpose: this runs on an error path, so an unreadable catalog or
    a half-written entry must never turn "the provider is down" into a second
    exception.
    """
    if catalog is None:
        try:
            from deeptutor.services.config import get_model_catalog_service

            catalog = get_model_catalog_service().load()
        except Exception:  # pragma: no cover - settings must not break an error path
            return []

    services = catalog.get("services") if isinstance(catalog, dict) else None
    llm = services.get("llm") if isinstance(services, dict) else None
    declared = llm.get(FALLBACKS_KEY) if isinstance(llm, dict) else None
    if not isinstance(declared, list):
        return []

    entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in declared:
        entry = _entry(raw)
        if entry is None:
            continue
        key = (entry["profile_id"], entry["model_id"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
        if len(entries) >= MAX_FALLBACKS:
            break
    return entries


def fallback_count(catalog: dict[str, Any] | None = None) -> int:
    """How many fallback candidates are configured (0 when the key is absent)."""
    return len(configured_fallbacks(catalog))


__all__ = [
    "FALLBACKS_KEY",
    "MAX_FALLBACKS",
    "configured_fallbacks",
    "fallback_count",
]
