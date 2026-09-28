"""Batch re-extraction for already-ingested reading materials.

Materials ingested before embedded-figure extraction existed still say
``media_count == 0`` in their ``manifest.json`` and have no ``media.json`` beside
it. Fixing that one material at a time used to mean deleting and re-importing,
which throws away the reader's annotations, bookmarks and position. This module
drives the in-place ``ReadingStore.refresh_document`` (extract the raw bytes
again, keep user-owned state) over a set of materials and optionally backfills
image captions.

Re-extraction is **serial on purpose**: each write goes through the store's
per-material lock and a refresh stages a whole directory, so parallel refreshes
only fight for disk against no measurable win.

The CLI wrapper lives in ``scripts/reading_refresh_figures.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from deeptutor.reading.models import ReadingError
from deeptutor.reading.store import ReadingStore

logger = logging.getLogger(__name__)


def _load_manifests(
    store: ReadingStore, material_ids: Sequence[str] | None
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Return (manifests, missing). *missing* rows carry id + reason."""
    if material_ids is None:
        return list(store.list_materials()), []
    manifests: list[Any] = []
    missing: list[dict[str, Any]] = []
    for material_id in material_ids:
        try:
            manifests.append(store.manifest(material_id))
        except ReadingError as exc:
            missing.append({"material_id": str(material_id), "error": str(exc)})
    return manifests, missing


def _has_raw_pdf(store: ReadingStore, material_id: str) -> bool:
    """Whether the original PDF bytes are still on disk to re-extract from."""
    raw = store.raw_path(material_id)
    return raw is not None and raw.suffix.lower() == ".pdf"


def _select(
    store: ReadingStore, material_ids: Sequence[str] | None
) -> tuple[list[tuple[str, str, int]], int, list[dict[str, Any]]]:
    """Split candidates into (eligible rows, skipped count, missing rows)."""
    manifests, missing = _load_manifests(store, material_ids)
    eligible: list[tuple[str, str, int]] = []
    skipped = 0
    for manifest in manifests:
        if manifest.extractor != "pymupdf" or not _has_raw_pdf(store, manifest.material_id):
            skipped += 1
            continue
        eligible.append((manifest.material_id, manifest.filename, manifest.media_count))
    return eligible, skipped, missing


def pdf_materials(
    store: ReadingStore, *, material_ids: Sequence[str] | None = None
) -> list[tuple[str, str, int]]:
    """PDF materials worth re-extracting: ``(material_id, filename, old_media)``.

    Only ``pymupdf``-extracted materials whose original bytes are still on disk
    qualify; anything else (DOCX/PPTX/EPUB/OCR text) is skipped and counted
    internally. Pass *material_ids* to restrict the set to specific ids.
    """
    eligible, _, _ = _select(store, material_ids)
    return eligible


def _refresh_document(store: ReadingStore, material_id: str) -> Any:
    """Call the in-place re-extraction, failing clearly when it is missing."""
    refresh = getattr(store, "refresh_document", None)
    if refresh is None:
        raise ReadingError(
            "ReadingStore.refresh_document is not available in this build; "
            "cannot re-extract (use --dry-run to inspect without writing)."
        )
    return refresh(material_id)


async def _caption_material_media(store: ReadingStore, material_id: str, *, force: bool) -> int:
    """Caption one material's media, importing the captions module lazily.

    Deferred so ``--dry-run`` keeps working before ``captions.py`` lands.
    """
    try:
        from deeptutor.reading.captions import caption_material_media
    except ImportError as exc:  # pragma: no cover - depends on build state
        raise ReadingError(
            "captioning is unavailable: deeptutor.reading.captions is not importable"
        ) from exc
    return int(await caption_material_media(material_id, store=store, force=force, limit=None))


async def refresh_materials(
    store: ReadingStore,
    material_ids: Sequence[str] | None,
    *,
    dry_run: bool,
    caption: bool,
    caption_force: bool,
    limit: int | None,
) -> dict[str, Any]:
    """Re-extract eligible PDFs in place and optionally caption their media.

    One material's failure is recorded and the loop continues. Returns a summary
    dict: ``processed`` / ``skipped`` / ``media_added`` / ``captions`` /
    ``failures`` plus per-material ``rows`` for the caller's table. *dry_run*
    only reads: it prints each material's filename, media count and unit count
    without importing or calling any write path.
    """
    eligible, skipped, missing = _select(store, material_ids)
    selected = eligible if limit is None else eligible[: max(0, int(limit))]

    summary: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "processed": 0,
        "skipped": skipped,
        "media_added": 0,
        "captions": 0,
        "failures": list(missing),
        "rows": [],
    }
    total = len(selected)
    for index, (material_id, filename, old_media) in enumerate(selected, start=1):
        label = f"[{index}/{total}] {material_id} {filename}"
        try:
            if dry_run:
                manifest = store.manifest(material_id)
                suffix = " + captions" if caption else ""
                print(
                    f"{label}: would re-extract — media={old_media} "
                    f"units={manifest.unit_count}{suffix}",
                    flush=True,
                )
                summary["rows"].append(
                    {
                        "material_id": material_id,
                        "filename": filename,
                        "old_media": old_media,
                        "new_media": None,
                        "captions": None,
                    }
                )
            else:
                _refresh_document(store, material_id)
                new_media = len(store.media_items(material_id))
                caption_count = 0
                if caption:
                    caption_count = await _caption_material_media(
                        store, material_id, force=caption_force
                    )
                gained = max(0, new_media - old_media)
                summary["media_added"] += gained
                summary["captions"] += caption_count
                print(
                    f"{label}: media {old_media} -> {new_media} (+{gained}), "
                    f"captions {caption_count}",
                    flush=True,
                )
                summary["rows"].append(
                    {
                        "material_id": material_id,
                        "filename": filename,
                        "old_media": old_media,
                        "new_media": new_media,
                        "captions": caption_count,
                    }
                )
            summary["processed"] = len(summary["rows"])
        except Exception as exc:  # noqa: BLE001 - one bad material must not stop the batch
            print(f"{label}: FAILED — {exc}", flush=True)
            summary["failures"].append(
                {"material_id": material_id, "filename": filename, "error": str(exc)}
            )
    return summary
