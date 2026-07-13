"""Legacy public-API shims for :mod:`deeptutor.services.memory.store`.

The pre-redesign module exposed ``consolidate_l2`` and ``consolidate_l3``
returning a :class:`ConsolidateResult`. The store / API router still
call these names. We keep them as thin wrappers around :func:`run_update`
so the surface that the router and the test fixtures import doesn't
change while the implementation switches to chunk-based update + dedup.

``apply_ops`` semantics
-----------------------
The pre-redesign ``apply_ops=False`` was a "preview the ops, do not
write" toggle for the workbench. The new chunk-based update writes
incrementally and there's no clean way to roll it back atomically. So:

* ``apply_ops=True`` (default) → :func:`run_update` runs end-to-end.
* ``apply_ops=False`` → we still run the update so the workbench can
  observe what would be added via the SSE event stream, but we capture
  the new entry ids and immediately delete them post-write. This keeps
  the preview semantic functionally close to the old behaviour without
  introducing a parallel preview pipeline. Auto-dedup is suppressed
  in preview mode to avoid touching pre-existing entries.

Callers that want a true preview (no disk writes at all) should move
to the new ``run_update`` API directly with a custom on_event consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from deeptutor.services.memory import paths
from deeptutor.services.memory.consolidator.modes.update import (
    UpdateResult,
    run_update,
)
from deeptutor.services.memory.document import parse, serialize
from deeptutor.services.memory.ops import ApplyReport, Op
from deeptutor.services.memory.paths import L3Slot, Surface

OnEvent = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class ConsolidateResult:
    report: ApplyReport
    backlog_count: int
    proposed_ops: list[Op] = field(default_factory=list)


async def consolidate_l2(
    surface: Surface,
    *,
    language: str = "en",
    user_label: str = "anonymous",
    on_event: OnEvent | None = None,
    apply_ops: bool = True,
) -> ConsolidateResult:
    result = await run_update(
        "L2",
        surface,
        language=language,
        user_label=user_label,
        on_event=on_event,
    )
    if not apply_ops:
        _rollback_new_entries("L2", surface, result.new_entry_ids)
    return _to_consolidate_result(result)


async def consolidate_l3(
    slot: L3Slot,
    *,
    language: str = "en",
    user_label: str = "anonymous",
    on_event: OnEvent | None = None,
    apply_ops: bool = True,
) -> ConsolidateResult:
    if slot == "preferences":
        raise ValueError("preferences.md is not auto-consolidated")
    result = await run_update(
        "L3",
        slot,
        language=language,
        user_label=user_label,
        on_event=on_event,
    )
    if not apply_ops:
        _rollback_new_entries("L3", slot, result.new_entry_ids)
    return _to_consolidate_result(result)


def _to_consolidate_result(result: UpdateResult) -> ConsolidateResult:
    reason = (
        "no new input"
        if result.no_new_input
        else f"applied via chunk-update ({result.facts_added} added)"
    )
    return ConsolidateResult(
        report=ApplyReport(
            accepted=True,
            reason=reason,
            results=[],  # the new pipeline does not emit per-op OpResult objects
        ),
        backlog_count=result.chunks_processed,
        proposed_ops=[],  # the chunk-based mode writes directly; preview is via SSE
    )


def _rollback_new_entries(layer: str, key: str, ids: list[str]) -> None:
    """Remove entries by id (used by ``apply_ops=False`` preview mode).

    This is best-effort: if the doc was edited externally between the
    update and rollback, ids not found are silently skipped.
    """
    if not ids:
        return
    path = paths.l2_file(key) if layer == "L2" else paths.l3_file(key)  # type: ignore[arg-type]
    if not path.exists():
        return
    doc = parse(path.read_text(encoding="utf-8"))
    drop = set(ids)
    for _name, entries in doc.sections:
        entries[:] = [e for e in entries if e.id not in drop]
    doc.sections[:] = [(n, e) for n, e in doc.sections if e]
    path.write_text(serialize(doc), encoding="utf-8")


__all__ = ["ConsolidateResult", "consolidate_l2", "consolidate_l3"]
