"""Merge mode — consolidate footnote references on a single doc.

This mode is a *no-LLM* refactor pass. It loads the L2 or L3 document
and rewrites it through :func:`serialize`, which:

1. Migrates legacy entry-keyed footnotes (``[^m_xxx]: r1, r2``) to the
   new ref-keyed layout (``[^1]: r1``, ``[^2]: r2``).
2. Collapses duplicate footnote definitions — N entries citing the same
   source share one footnote label, so the rendered view stops repeating
   ``notebook:3a563e6f`` once per entry.
3. Re-numbers labels in first-appearance order so the output is stable.

For **L3 docs only**, merge ALSO runs a one-shot data migration: every
legacy ``m_<ULID>`` ref (which used to point at an L2 entry) is resolved
to its owning surface name, so the doc becomes citeable as
``L3 → L2 md → L1 raw traces``. After the next update pass nothing is
left for this migration to do — it's a pure clean-up of pre-pivot docs.

Merge is invoked either:

* automatically after a successful :func:`run_update`, :func:`run_audit`,
  or :func:`run_dedup` (controlled by the three
  ``memory.merge.auto_after_*`` settings), or
* explicitly via the workbench `[Merge]` button → ``mode="merge"``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re

from deeptutor.services.memory import paths
from deeptutor.services.memory.consolidator.modes._runtime import (
    OnEvent,
    emit,
    load_doc,
    write_doc_checkpoint,
)
from deeptutor.services.memory.ids import is_entry_id

logger = logging.getLogger(__name__)

# Cheap pre-write check: count footnote definitions in the on-disk text to
# tell the workbench how many rows the merge collapsed. We do this on the
# *raw* bytes rather than on parsed entries because the parsed model
# already has consolidated refs (`Entry.refs` carries unique refs per
# entry), so the meaningful "before" number is what's in the file.
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^[^\]]+\]:\s*", re.MULTILINE)


@dataclass
class MergeResult:
    layer: str
    key: str
    footnote_rows_before: int
    footnote_rows_after: int
    rewrote: bool
    legacy_l3_refs_migrated: int = 0


async def run_merge(
    layer: str,
    key: str,
    *,
    language: str = "en",
    user_label: str = "anonymous",
    on_event: OnEvent | None = None,
) -> MergeResult:
    """Re-serialize ``layer/key``; collapse duplicate refs into one footnote each.

    Idempotent: re-running on an already-merged doc rewrites the same
    bytes and reports ``rewrote=False`` (no checkpoint is pushed).
    """
    # NOTE: ``language`` / ``user_label`` are accepted for signature symmetry
    # with the other modes; merge itself does no localized work and no LLM
    # calls, so neither is used inside the body.
    del language, user_label

    path = _path_for(layer, key)
    if not path.exists():
        await emit(on_event, {"stage": "done", "no_doc": True, "rewrote": False})
        return MergeResult(
            layer=layer, key=key, footnote_rows_before=0, footnote_rows_after=0, rewrote=False
        )

    raw_before = path.read_text(encoding="utf-8")
    rows_before = len(_FOOTNOTE_DEF_RE.findall(raw_before))
    doc = load_doc(path, default_title=_default_title(layer, key))

    legacy_migrated = 0
    if layer == "L3":
        legacy_migrated = _migrate_l3_legacy_refs(doc)

    # Count unique refs across the doc — this is the "after" footnote-row
    # count once :func:`serialize` consolidates them.
    unique_refs: set[str] = set()
    for entry in doc.all_entries():
        for ref in entry.refs:
            unique_refs.add(ref)
    rows_after = len(unique_refs)

    await emit(
        on_event,
        {
            "stage": "progress",
            "mode": "merge",
            "footnote_rows_before": rows_before,
            "footnote_rows_after": rows_after,
            "legacy_l3_refs_migrated": legacy_migrated,
        },
    )

    # We always rewrite when the doc has any entries — even when
    # before == after, the act of re-serializing renormalizes whitespace
    # and migrates legacy entry-keyed layouts. Skip only when the file is
    # byte-equal to what :func:`serialize` would produce.
    from deeptutor.services.memory.document import serialize

    expected = serialize(doc)
    rewrote = raw_before != expected
    if rewrote:
        await write_doc_checkpoint(
            path,
            doc,
            layer=layer,
            key=key,
            on_event=on_event,
            turn=1,
            label="merge",
            action="merge_footnotes",
        )

    await emit(
        on_event,
        {
            "stage": "done",
            "footnote_rows_before": rows_before,
            "footnote_rows_after": rows_after,
            "rewrote": rewrote,
            "legacy_l3_refs_migrated": legacy_migrated,
        },
    )
    return MergeResult(
        layer=layer,
        key=key,
        footnote_rows_before=rows_before,
        footnote_rows_after=rows_after,
        rewrote=rewrote,
        legacy_l3_refs_migrated=legacy_migrated,
    )


# ── Helpers ─────────────────────────────────────────────────────────────


def _migrate_l3_legacy_refs(doc) -> int:
    """Resolve legacy ``m_<ULID>`` L3 refs to bare surface names.

    Pre-pivot L3 docs cited L2 entries by their entry id. The current
    design wants surface-level provenance only ("which L2 md did this
    synthesize from"). For each ``m_<ULID>`` ref we scan every L2 md
    for the owning entry and substitute the surface name.

    Returns the number of entry refs that were migrated. Unresolvable
    ids (entry deleted, or never existed) are dropped silently — the
    next ``run_update`` round will re-synthesize from current L2 text.
    """
    from deeptutor.services.memory.document import parse

    # Cache L2 entry-id → surface lookups: one scan per L2 md, reused
    # across every L3 ref in the doc.
    l2_owner: dict[str, str] = {}
    for surface in paths.SURFACES:
        l2_path = paths.l2_file(surface)
        if not l2_path.exists():
            continue
        try:
            l2_doc = parse(l2_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — malformed L2 should not block L3 migration
            continue
        for entry in l2_doc.all_entries():
            l2_owner.setdefault(entry.id, surface)

    migrated = 0
    for entry in doc.all_entries():
        if not entry.refs:
            continue
        new_refs: list[str] = []
        seen: set[str] = set()
        for ref in entry.refs:
            if is_entry_id(ref):
                migrated += 1
                resolved = l2_owner.get(ref)
                if resolved is None or resolved in seen:
                    continue
                seen.add(resolved)
                new_refs.append(resolved)
            else:
                if ref in seen:
                    continue
                seen.add(ref)
                new_refs.append(ref)
        entry.refs = new_refs
    return migrated


def _path_for(layer: str, key: str):
    if layer == "L2":
        return paths.l2_file(key)  # type: ignore[arg-type]
    if layer == "L3":
        return paths.l3_file(key)  # type: ignore[arg-type]
    raise ValueError(f"unknown layer {layer!r}")


def _default_title(layer: str, key: str) -> str:
    if layer == "L2":
        return f"{key} memory"
    return {
        "recent": "Recent summary",
        "profile": "User profile",
        "scope": "Knowledge scope",
        "preferences": "Preferences",
    }.get(key, f"{key} memory")


__all__ = ["MergeResult", "run_merge"]
