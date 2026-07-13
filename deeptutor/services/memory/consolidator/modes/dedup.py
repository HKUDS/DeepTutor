"""Dedup mode — iterative line-level merge / delete over the full doc.

Each iteration:
1. Render the full md as a line-numbered view (footnote-stripped).
2. One LLM call returns ``{"edits": [...]}`` (replace + delete only —
   the dedup prompt forbids inserts).
3. Apply in reverse line order.
4. If the LLM returned zero edits, **stop early** (saves tokens).

The configured ``iterations`` is the *upper bound*, not a quota.

Dedup is invoked either:
- automatically after a successful :func:`run_update` (controlled by
  ``memory.dedup.auto_after_update``), or
- explicitly via the workbench `[Dedup]` button.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from deeptutor.services.memory import paths
from deeptutor.services.memory.consolidator.line_doc import (
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
    today_iso,
    write_doc_checkpoint,
)
from deeptutor.services.memory.settings import load_memory_settings

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    layer: str
    key: str
    iterations_run: int
    edits_applied: int
    converged_early: bool


async def run_dedup(
    layer: str,
    key: str,
    *,
    language: str = "en",
    user_label: str = "anonymous",
    iterations: int | None = None,
    llm_selection: dict | None = None,
    on_event: OnEvent | None = None,
) -> DedupResult:
    from deeptutor.services.model_selection.runtime import (
        activate_llm_selection,
        reset_llm_selection,
    )

    settings = load_memory_settings()
    iters = iterations if iterations is not None else settings.dedup.iterations

    token = None
    if llm_selection:
        try:
            _config, token = activate_llm_selection(llm_selection)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory dedup: ignoring unresolvable llm_selection %s: %s", llm_selection, exc
            )
            token = None
    try:
        return await _run_dedup_inner(
            layer, key, iters=iters, language=language, user_label=user_label, on_event=on_event
        )
    finally:
        reset_llm_selection(token)


async def _run_dedup_inner(
    layer: str,
    key: str,
    *,
    iters: int,
    language: str,
    user_label: str,
    on_event: OnEvent | None,
) -> DedupResult:
    path = _path_for(layer, key)
    if not path.exists():
        await emit(on_event, {"stage": "done", "no_doc": True, "edits_applied": 0})
        return DedupResult(
            layer=layer, key=key, iterations_run=0, edits_applied=0, converged_early=True
        )

    doc = load_doc(path, default_title=_default_title(layer, key))
    if not doc.all_entries():
        await emit(on_event, {"stage": "done", "no_doc": True, "edits_applied": 0})
        return DedupResult(
            layer=layer, key=key, iterations_run=0, edits_applied=0, converged_early=True
        )

    prompt = load_prompt("dedup", language)
    total_applied = 0
    converged = False

    for i in range(iters):
        view = render_view(doc)
        await emit(
            on_event,
            {
                "stage": "progress",
                "mode": "dedup",
                "turn": i + 1,
                "total": iters,
                "lines": len(view.lines),
            },
        )
        system = prompt["system"].format(user_label=user_label, today=today_iso())
        user = prompt["user"].format(
            doc=_render_with_numbers(view),
            iteration=i + 1,
            iterations_total=iters,
        )
        raw = await call_llm(
            system_prompt=system,
            user_prompt=user,
            on_event=on_event,
            turn=i + 1,
            label="dedup",
        )
        edits = parse_edits_payload(raw, layer=layer)
        if not edits:
            converged = True
            await emit(on_event, {"stage": "facts_extracted", "turn": i + 1, "edits": 0})
            break

        doc, report = apply_edits(doc, edits)
        total_applied += len(report.applied)
        if report.applied:
            await write_doc_checkpoint(
                path,
                doc,
                layer=layer,
                key=key,
                on_event=on_event,
                turn=i + 1,
                label="dedup",
                action="apply_edits",
            )
        await emit(
            on_event,
            {
                "stage": "op_applied",
                "turn": i + 1,
                "applied": len(report.applied),
                "rejected": len(report.rejected),
            },
        )
        if not report.applied and not report.rejected:
            converged = True
            break

    await emit(
        on_event,
        {
            "stage": "done",
            "edits_applied": total_applied,
            "iterations_run": min(iters, i + 1 if iters else 0),
            "converged_early": converged,
        },
    )

    if load_memory_settings().merge.auto_after_dedup:
        from deeptutor.services.memory.consolidator.modes.merge import run_merge

        await run_merge(
            layer,
            key,
            language=language,
            user_label=user_label,
            on_event=on_event,
        )

    return DedupResult(
        layer=layer,
        key=key,
        iterations_run=min(iters, (i + 1) if iters else 0),
        edits_applied=total_applied,
        converged_early=converged,
    )


# ── Helpers ─────────────────────────────────────────────────────────────


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


def _render_with_numbers(view) -> str:
    width = max(2, len(str(len(view.lines))))
    return "\n".join(f"{line.number:>{width}}: {line.text}" for line in view.lines)


__all__ = ["DedupResult", "run_dedup"]
