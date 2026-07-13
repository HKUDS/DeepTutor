"""Audit mode — line-level edits checked against raw evidence.

Algorithm
---------
1. Render the target md as a line-numbered, footnote-stripped view
   (:func:`line_doc.render_view`).
2. Chunk the rendered view into ≤ budget pieces; each chunk is a
   contiguous slice of lines whose bullet entries get **annotated with
   their full source content** (no truncation).
3. Per chunk: LLM call → parse edits → apply against the in-memory doc
   in reverse line order. Across chunks, edits stack — but because we
   slice on whole-line boundaries and apply per-chunk before the next
   chunk runs, the line numbers the next chunk sees are still the ones
   the LLM was given.
4. Atomic flush.

The chunker is deliberately char-based (same as update) so chunk size
behaves predictably alongside the annotation block (which can be much
larger than the bare md). The annotated block fed to the LLM is what
gets counted against the budget.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from deeptutor.services.memory import paths
from deeptutor.services.memory import snapshot as snap
from deeptutor.services.memory.consolidator.chunker import (
    chunk_with_boundary,
)
from deeptutor.services.memory.consolidator.line_doc import (
    LineView,
    apply_edits,
    parse_edits_payload,
    render_view,
)
from deeptutor.services.memory.consolidator.modes._runtime import (
    OnEvent,
    call_llm,
    emit,
    load_doc,
    load_prompt,
    slot_focus,
    surface_focus,
    today_iso,
    write_doc_checkpoint,
)
from deeptutor.services.memory.consolidator.references import (
    annotate_l2_line_with_evidence,
    annotate_l3_line_with_evidence,
)
from deeptutor.services.memory.document import Document, Entry
from deeptutor.services.memory.paths import L3Slot, Surface
from deeptutor.services.memory.settings import load_memory_settings
from deeptutor.services.memory.snapshot.entity import Entity

logger = logging.getLogger(__name__)


@dataclass
class AuditResult:
    layer: str
    key: str
    chunks_processed: int
    edits_applied: int = 0
    edits_rejected: int = 0
    no_doc: bool = False


# ── Public entry ────────────────────────────────────────────────────────


async def run_audit(
    layer: str,
    key: str,
    *,
    language: str = "en",
    user_label: str = "anonymous",
    budget: int | None = None,
    llm_selection: dict | None = None,
    on_event: OnEvent | None = None,
) -> AuditResult:
    from deeptutor.services.model_selection.runtime import (
        activate_llm_selection,
        reset_llm_selection,
    )

    settings = load_memory_settings()
    token = None
    if llm_selection:
        try:
            _config, token = activate_llm_selection(llm_selection)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory audit: ignoring unresolvable llm_selection %s: %s", llm_selection, exc
            )
            token = None
    try:
        if layer == "L2":
            return await _run_audit_l2(
                key,  # type: ignore[arg-type]
                language=language,
                user_label=user_label,
                budget=budget if budget is not None else settings.audit.l2_budget,
                llm_selection=llm_selection,
                on_event=on_event,
                settings=settings,
            )
        if layer == "L3":
            return await _run_audit_l3(
                key,  # type: ignore[arg-type]
                language=language,
                user_label=user_label,
                budget=budget if budget is not None else settings.audit.l3_budget,
                llm_selection=llm_selection,
                on_event=on_event,
                settings=settings,
            )
        raise ValueError(f"unknown layer {layer!r}")
    finally:
        reset_llm_selection(token)


# ── L2 ──────────────────────────────────────────────────────────────────


async def _run_audit_l2(
    surface: Surface,
    *,
    language: str,
    user_label: str,
    budget: int,
    llm_selection: dict | None,
    on_event: OnEvent | None,
    settings,
) -> AuditResult:
    l2_path = paths.l2_file(surface)
    if not l2_path.exists():
        await emit(on_event, {"stage": "done", "no_doc": True})
        return AuditResult(layer="L2", key=surface, chunks_processed=0, no_doc=True)

    doc = load_doc(l2_path, default_title=f"{surface} memory")
    entity_lookup = {ent.id: ent for ent in snap.read_snapshot(surface)}
    prompt = load_prompt("audit_l2", language)
    focus, _sections = surface_focus(language, surface)

    annotated_text, line_ranges = _build_annotated_l2(doc, surface, entity_lookup)
    chunks = chunk_with_boundary(
        annotated_text,
        budget=budget,
        overlap_ratio=settings.chunking.overlap_ratio,
        min_chunk_chars=settings.chunking.min_chunk_chars,
        max_chunk_chars=settings.chunking.max_chunk_chars,
        boundary=settings.chunking.boundary,
    )
    await emit(
        on_event,
        {"stage": "chunked", "chunks": len(chunks), "budget": budget, "chars": len(annotated_text)},
    )

    edits_applied = 0
    edits_rejected = 0
    for chunk in chunks:
        await emit(
            on_event,
            {
                "stage": "progress",
                "mode": "audit",
                "turn": chunk.index + 1,
                "total": len(chunks),
            },
        )
        system = prompt["system"].format(
            user_label=user_label,
            surface=surface,
            focus=focus,
            today=today_iso(),
        )
        user = prompt["user"].format(surface=surface, chunk=chunk.text)
        raw = await call_llm(
            system_prompt=system,
            user_prompt=user,
            on_event=on_event,
            turn=chunk.index + 1,
            chunk_index=chunk.index,
            label="audit",
        )
        edits = parse_edits_payload(raw, layer="L2")
        if not edits:
            await emit(
                on_event,
                {"stage": "facts_extracted", "turn": chunk.index + 1, "edits": 0},
            )
            continue
        doc, report = apply_edits(doc, edits)
        edits_applied += len(report.applied)
        edits_rejected += len(report.rejected)
        if report.applied:
            await write_doc_checkpoint(
                l2_path,
                doc,
                layer="L2",
                key=surface,
                on_event=on_event,
                turn=chunk.index + 1,
                label="audit",
                action="apply_edits",
            )
        for res in report.applied:
            await emit(
                on_event,
                {
                    "stage": "op_applied",
                    "turn": chunk.index + 1,
                    "op": res.op.op,
                    "detail": res.detail,
                },
            )
        for res in report.rejected:
            await emit(
                on_event,
                {
                    "stage": "op_rejected",
                    "turn": chunk.index + 1,
                    "op": res.op.op,
                    "detail": res.detail,
                },
            )
        # Refresh annotation for the next chunk — line numbers shifted.
        annotated_text, line_ranges = _build_annotated_l2(doc, surface, entity_lookup)

    await emit(
        on_event,
        {
            "stage": "done",
            "edits_applied": edits_applied,
            "edits_rejected": edits_rejected,
            "chunks_processed": len(chunks),
        },
    )

    if load_memory_settings().merge.auto_after_audit:
        from deeptutor.services.memory.consolidator.modes.merge import run_merge

        await run_merge(
            "L2",
            surface,
            language=language,
            user_label=user_label,
            on_event=on_event,
        )

    return AuditResult(
        layer="L2",
        key=surface,
        chunks_processed=len(chunks),
        edits_applied=edits_applied,
        edits_rejected=edits_rejected,
    )


# ── L3 ──────────────────────────────────────────────────────────────────


async def _run_audit_l3(
    slot: L3Slot,
    *,
    language: str,
    user_label: str,
    budget: int,
    llm_selection: dict | None,
    on_event: OnEvent | None,
    settings,
) -> AuditResult:
    if slot == "preferences":
        raise ValueError("preferences.md is not audited automatically")

    l3_path = paths.l3_file(slot)
    if not l3_path.exists():
        await emit(on_event, {"stage": "done", "no_doc": True})
        return AuditResult(layer="L3", key=slot, chunks_processed=0, no_doc=True)

    doc = load_doc(l3_path, default_title=f"{slot} memory")
    l2_lookup = _build_l2_entry_lookup()
    prompt = load_prompt("audit_l3", language)
    focus, _sections = slot_focus(language, slot)

    annotated_text, _ranges = _build_annotated_l3(doc, l2_lookup)
    chunks = chunk_with_boundary(
        annotated_text,
        budget=budget,
        overlap_ratio=settings.chunking.overlap_ratio,
        min_chunk_chars=settings.chunking.min_chunk_chars,
        max_chunk_chars=settings.chunking.max_chunk_chars,
        boundary=settings.chunking.boundary,
    )
    await emit(
        on_event,
        {"stage": "chunked", "chunks": len(chunks), "budget": budget, "chars": len(annotated_text)},
    )

    edits_applied = 0
    edits_rejected = 0
    for chunk in chunks:
        await emit(
            on_event,
            {
                "stage": "progress",
                "mode": "audit",
                "turn": chunk.index + 1,
                "total": len(chunks),
            },
        )
        system = prompt["system"].format(
            user_label=user_label,
            slot=slot,
            focus=focus,
            today=today_iso(),
        )
        user = prompt["user"].format(slot=slot, chunk=chunk.text)
        raw = await call_llm(
            system_prompt=system,
            user_prompt=user,
            on_event=on_event,
            turn=chunk.index + 1,
            chunk_index=chunk.index,
            label="audit",
        )
        edits = parse_edits_payload(raw, layer="L3")
        if not edits:
            await emit(
                on_event,
                {"stage": "facts_extracted", "turn": chunk.index + 1, "edits": 0},
            )
            continue
        doc, report = apply_edits(doc, edits)
        edits_applied += len(report.applied)
        edits_rejected += len(report.rejected)
        if report.applied:
            await write_doc_checkpoint(
                l3_path,
                doc,
                layer="L3",
                key=slot,
                on_event=on_event,
                turn=chunk.index + 1,
                label="audit",
                action="apply_edits",
            )
        for res in report.applied:
            await emit(
                on_event,
                {
                    "stage": "op_applied",
                    "turn": chunk.index + 1,
                    "op": res.op.op,
                    "detail": res.detail,
                },
            )
        for res in report.rejected:
            await emit(
                on_event,
                {
                    "stage": "op_rejected",
                    "turn": chunk.index + 1,
                    "op": res.op.op,
                    "detail": res.detail,
                },
            )
        annotated_text, _ranges = _build_annotated_l3(doc, l2_lookup)

    await emit(
        on_event,
        {
            "stage": "done",
            "edits_applied": edits_applied,
            "edits_rejected": edits_rejected,
            "chunks_processed": len(chunks),
        },
    )

    if load_memory_settings().merge.auto_after_audit:
        from deeptutor.services.memory.consolidator.modes.merge import run_merge

        await run_merge(
            "L3",
            slot,
            language=language,
            user_label=user_label,
            on_event=on_event,
        )

    return AuditResult(
        layer="L3",
        key=slot,
        chunks_processed=len(chunks),
        edits_applied=edits_applied,
        edits_rejected=edits_rejected,
    )


# ── Annotation builders ────────────────────────────────────────────────


def _build_annotated_l2(
    doc: Document, surface: str, entity_lookup: dict[str, Entity]
) -> tuple[str, list[tuple[int, int]]]:
    """Render the doc as `line N: ... ` + per-bullet source dumps.

    Returns ``(text, ranges)`` where ``ranges`` is per-bullet
    ``(start_char, end_char)`` for future fine-grained linking. Not
    consumed by the LLM directly; reserved for the UI's diff view.
    """
    view = render_view(doc)
    pieces: list[str] = [_render_line_index(view)]
    ranges: list[tuple[int, int]] = []
    cursor = len(pieces[0])
    for line in view.lines:
        if line.kind != "bullet" or not line.entry_id:
            continue
        entry = view.entry_by_id.get(line.entry_id)
        if entry is None:
            continue
        block = annotate_l2_line_with_evidence(
            line.number, entry, surface=surface, entity_lookup=entity_lookup
        )
        # Two newlines separate annotation blocks.
        prefix = "\n\n"
        start = cursor + len(prefix)
        pieces.append(prefix + block)
        cursor = start + len(block)
        ranges.append((start, cursor))
    return "".join(pieces), ranges


def _build_annotated_l3(
    doc: Document, l2_lookup: dict[str, Entry]
) -> tuple[str, list[tuple[int, int]]]:
    view = render_view(doc)
    pieces: list[str] = [_render_line_index(view)]
    ranges: list[tuple[int, int]] = []
    cursor = len(pieces[0])
    for line in view.lines:
        if line.kind != "bullet" or not line.entry_id:
            continue
        entry = view.entry_by_id.get(line.entry_id)
        if entry is None:
            continue
        block = annotate_l3_line_with_evidence(line.number, entry, l2_entry_lookup=l2_lookup)
        prefix = "\n\n"
        start = cursor + len(prefix)
        pieces.append(prefix + block)
        cursor = start + len(block)
        ranges.append((start, cursor))
    return "".join(pieces), ranges


def _render_line_index(view: LineView) -> str:
    width = max(2, len(str(len(view.lines))))
    head = "# Line-numbered view (LLM-facing):\n"
    body = "\n".join(f"{line.number:>{width}}: {line.text}" for line in view.lines)
    return head + body


def _build_l2_entry_lookup() -> dict[str, Entry]:
    from deeptutor.services.memory.document import parse

    out: dict[str, Entry] = {}
    for surface in paths.SURFACES:
        path = paths.l2_file(surface)
        if not path.exists():
            continue
        try:
            doc = parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in doc.all_entries():
            out[entry.id] = entry
    return out


__all__ = ["AuditResult", "run_audit"]
