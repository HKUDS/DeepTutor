"""KB-level bilingual sync orchestrator.

Coordinates the full bilingual web-source sync pipeline:

1. Group web sources into language pairs by origin.
2. Crawl every source (EN and ZH concurrently).
3. Write pages to ``raw/`` preserving both languages.
4. Align paired pages and persist structured sidecars.
5. Merge EN/ZH navigation trees into one English-primary tree.
6. Rebuild the index once atomically after all sources are processed.

Navigation building lives in :mod:`navigation`, index rebuilding in
:mod:`index_rebuild`, and alignment in :mod:`md_align`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Any, Callable

from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR
from deeptutor.services.web_source import bilingual_store, index_rebuild
from deeptutor.services.web_source.crawler import crawl_and_diff
from deeptutor.services.web_source.md_align import (
    align_markdown,
    align_markdown_en_only,
)
from deeptutor.services.web_source.navigation import merge_navigation
from deeptutor.services.web_source.pairing import (
    LanguagePair,
    compute_pair_status,
    group_sources_by_origin,
    pair_file_paths,
    strip_lang_prefix_from_path,
)

logger = logging.getLogger(__name__)

WEB_SYNC_INTERVAL_HOURS = 24


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── result dataclasses ───────────────────────────────────────────────


@dataclass
class PairSyncResult:
    """Outcome of syncing one language pair."""

    pair_key: str
    origin: str
    status: str = "pending"
    en_pages: int = 0
    zh_pages: int = 0
    paired_pages: int = 0
    en_only_pages: int = 0
    zh_only_pages: int = 0
    low_confidence: int = 0
    error: str = ""
    source_results: list[dict] = field(default_factory=list)


@dataclass
class KBSyncResult:
    """Outcome of syncing all web sources in a KB."""

    ok: bool = True
    pair_results: list[PairSyncResult] = field(default_factory=list)
    index_rebuilt: bool = False
    index_error: str = ""
    total_pages: int = 0
    error: str = ""


# ── public entry points ──────────────────────────────────────────────


async def sync_kb_sources(
    kb_name: str,
    sources: list[dict[str, Any]],
    *,
    base_dir: str = DEFAULT_BASE_DIR,
    max_depth: int | None = None,
    max_pages: int | None = None,
) -> KBSyncResult:
    """Sync all web sources for a KB with bilingual coordination.

    Thin delegate to :func:`sync_kb_sources_safe`.  Kept for API
    compatibility.
    """
    return await sync_kb_sources_safe(
        kb_name,
        sources,
        base_dir=base_dir,
        max_depth=max_depth,
        max_pages=max_pages,
    )


async def sync_kb_sources_safe(
    kb_name: str,
    sources: list[dict[str, Any]],
    *,
    base_dir: str = DEFAULT_BASE_DIR,
    max_depth: int | None = None,
    max_pages: int | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> KBSyncResult:
    """Sync all web sources for a KB using async-safe index rebuild."""
    kb_dir = Path(base_dir) / kb_name
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    result = KBSyncResult()
    pairs = group_sources_by_origin(sources)

    any_pages_changed = False
    if progress:
        progress(5, f"Preparing {len(pairs)} language pair(s)")

    for index, pair in enumerate(pairs):
        if progress:
            progress(
                10 + int(75 * index / max(len(pairs), 1)),
                f"Syncing language pair {index + 1}/{len(pairs)}",
            )
        pair_result = await _sync_pair(
            kb_name,
            kb_dir,
            raw_dir,
            pair,
            max_depth=max_depth,
            max_pages=max_pages,
        )
        result.pair_results.append(pair_result)
        if pair_result.error:
            result.ok = False
        for sr in pair_result.source_results:
            if sr.get("pages_added", 0) or sr.get("pages_updated", 0) or sr.get("pages_removed", 0):
                any_pages_changed = True
        if progress:
            progress(
                10 + int(75 * (index + 1) / max(len(pairs), 1)),
                f"Completed language pair {index + 1}/{len(pairs)}",
            )

    result.total_pages = sum(pr.en_pages + pr.zh_pages for pr in result.pair_results)

    # Rebuild index once if any pages changed.
    if any_pages_changed or index_rebuild.needs_initial_index(kb_dir):
        if progress:
            progress(88, "Rebuilding knowledge base index")
        try:
            await index_rebuild.rebuild_index_async(kb_name, base_dir, raw_dir)
            result.index_rebuilt = True
        except Exception as exc:
            logger.exception("Index rebuild failed for KB '%s'", kb_name)
            result.index_error = str(exc)

    _persist_sync_state(kb_name, base_dir, sources, pairs, result)
    if progress:
        progress(100, "Web source sync complete")
    return result


# ── per-pair sync ────────────────────────────────────────────────────


async def _sync_pair(
    kb_name: str,
    kb_dir: Path,
    raw_dir: Path,
    pair: LanguagePair,
    *,
    max_depth: int | None,
    max_pages: int | None,
) -> PairSyncResult:
    """Sync one language pair: crawl both sources, align, store sidecars."""
    pair_status = compute_pair_status(pair)
    pr = PairSyncResult(
        pair_key=pair_status.pair_key,
        origin=pair.origin,
    )

    # Crawl EN and ZH sources concurrently (they're independent).
    crawl_tasks: dict[str, asyncio.Task] = {}
    if pair.en_source:
        crawl_tasks["en"] = asyncio.ensure_future(
            _crawl_and_write(
                kb_name,
                pair.en_source,
                raw_dir,
                max_depth=max_depth,
                max_pages=max_pages,
            )
        )
    if pair.zh_source:
        crawl_tasks["zh"] = asyncio.ensure_future(
            _crawl_and_write(
                kb_name,
                pair.zh_source,
                raw_dir,
                max_depth=max_depth,
                max_pages=max_pages,
            )
        )

    crawl_outcomes = await asyncio.gather(*crawl_tasks.values())
    crawl_by_lang = dict(zip(crawl_tasks.keys(), crawl_outcomes))

    en_crawl = None
    zh_crawl = None

    if "en" in crawl_by_lang:
        en_crawl, en_changed = crawl_by_lang["en"]
        pr.source_results.append(
            {
                "source_id": pair.en_source.get("id", ""),
                "url": pair.en_source.get("url", ""),
                "language": "en",
                **(en_crawl or {}),
                "changed_files": en_changed,
            }
        )
        if en_crawl and en_crawl.get("ok"):
            pr.en_pages = en_crawl.get("page_count", 0)

    if "zh" in crawl_by_lang:
        zh_crawl, zh_changed = crawl_by_lang["zh"]
        pr.source_results.append(
            {
                "source_id": pair.zh_source.get("id", ""),
                "url": pair.zh_source.get("url", ""),
                "language": "zh",
                **(zh_crawl or {}),
                "changed_files": zh_changed,
            }
        )
        if zh_crawl and zh_crawl.get("ok"):
            pr.zh_pages = zh_crawl.get("page_count", 0)

    # Check for errors.
    if pair.en_source and (not en_crawl or not en_crawl.get("ok")):
        pr.status = "error"
        pr.error = (en_crawl or {}).get("error", "EN crawl failed")
        return pr

    # Align paired pages.
    if pair.is_pair and en_crawl and zh_crawl:
        _sync_bilingual_pair(kb_dir, raw_dir, pair, pair_status, pr, en_crawl, zh_crawl)
    elif pair.en_source and en_crawl:
        _sync_en_only_pair(kb_dir, raw_dir, pair, pair_status, pr, en_crawl)

    return pr


def _sync_bilingual_pair(
    kb_dir: Path,
    raw_dir: Path,
    pair: LanguagePair,
    pair_status: Any,
    pr: PairSyncResult,
    en_crawl: dict,
    zh_crawl: dict,
) -> None:
    """Align and store sidecars for a bilingual EN+ZH pair."""
    pr.status = "bilingual"
    en_pages = en_crawl.get("page_files", [])
    zh_pages = zh_crawl.get("page_files", [])
    file_pairs = pair_file_paths(
        en_pages,
        zh_pages,
        pair.zh_lang_prefix,
        pair.manual_path_pairs,
    )
    paired_zh_files = {zh_file for _, zh_file in file_pairs if zh_file}

    # Build set of changed file names for incremental alignment.
    changed_names: set[str] = set()
    for sr in pr.source_results:
        changed_names.update(sr.get("changed_names", []))

    for en_file, zh_file in file_pairs:
        file_changed = en_file in changed_names or (zh_file and zh_file in changed_names)
        if not file_changed:
            existing = bilingual_store.load_alignment(kb_dir, pr.pair_key, en_file)
            manual_pair_changed = en_file in pair.manual_path_pairs and existing.get(
                "page_class"
            ) != "bilingual"
            if existing and not manual_pair_changed:
                pr.paired_pages += 1
                pr.low_confidence += existing.get("review_count", 0)
                continue

        en_path = raw_dir / en_file
        zh_path = raw_dir / zh_file if zh_file else None

        if not en_path.exists():
            continue

        en_text = en_path.read_text(encoding="utf-8")
        if zh_path and zh_path.exists():
            zh_text = zh_path.read_text(encoding="utf-8")
            alignment = align_markdown(en_text, zh_text)
            pr.paired_pages += 1
        else:
            alignment = align_markdown_en_only(en_text)
            pr.en_only_pages += 1

        pr.low_confidence += alignment.get("review_count", 0)
        bilingual_store.save_alignment(kb_dir, pr.pair_key, en_file, alignment)

    # Handle ZH-only pages.
    en_set = set(en_pages)
    for zf in zh_pages:
        if zf in paired_zh_files:
            continue
        base = strip_lang_prefix_from_path(zf, pair.zh_lang_prefix)
        if base not in en_set:
            zh_path = raw_dir / zf
            if zh_path.exists():
                alignment = {
                    "page_class": "zh_only",
                    "groups": [],
                    "review_count": 0,
                    "en_hash": "",
                    "zh_hash": _content_hash(zh_path.read_text(encoding="utf-8")),
                }
                bilingual_store.save_alignment(kb_dir, pr.pair_key, zf, alignment)
                pr.zh_only_pages += 1

    # Remove stale sidecars for pages no longer on the site.
    canonical_current = set(en_pages) | (set(zh_pages) - paired_zh_files)
    stale = bilingual_store.cleanup_stale_sidecars(kb_dir, pr.pair_key, canonical_current)
    if stale:
        logger.info("Cleaned up %d stale sidecar(s) for pair %s", stale, pr.pair_key)

    # Build and save merged navigation.
    merged_nav = merge_navigation(
        en_crawl.get("navigation", {}),
        zh_crawl.get("navigation", {}),
        pair.zh_lang_prefix,
        pr.pair_key,
    )
    bilingual_store.save_pair_index(
        kb_dir,
        pr.pair_key,
        {
            "pair_key": pr.pair_key,
            "origin": pr.origin,
            "status": "bilingual",
            "en_source_id": pair_status.en_source_id,
            "zh_source_id": pair_status.zh_source_id,
            "en_url": pair_status.en_url,
            "zh_url": pair_status.zh_url,
            "en_pages": pr.en_pages,
            "zh_pages": pr.zh_pages,
            "paired_pages": pr.paired_pages,
            "en_only_pages": pr.en_only_pages,
            "zh_only_pages": pr.zh_only_pages,
            "low_confidence": pr.low_confidence,
            "synced_at": _utcnow_iso(),
            "navigation": merged_nav,
        },
    )


def _sync_en_only_pair(
    kb_dir: Path,
    raw_dir: Path,
    pair: LanguagePair,
    pair_status: Any,
    pr: PairSyncResult,
    en_crawl: dict,
) -> None:
    """Generate en_only alignments for a source without a ZH counterpart."""
    pr.status = "en_only"

    changed_names: set[str] = set()
    for sr in pr.source_results:
        changed_names.update(sr.get("changed_names", []))

    current_en = set(en_crawl.get("page_files", []))
    stale = bilingual_store.cleanup_stale_sidecars(kb_dir, pr.pair_key, current_en)
    if stale:
        logger.info("Cleaned up %d stale sidecar(s) for pair %s", stale, pr.pair_key)

    for en_file in en_crawl.get("page_files", []):
        if en_file not in changed_names:
            existing = bilingual_store.load_alignment(kb_dir, pr.pair_key, en_file)
            if existing:
                continue
        en_path = raw_dir / en_file
        if en_path.exists():
            alignment = align_markdown_en_only(en_path.read_text(encoding="utf-8"))
            bilingual_store.save_alignment(kb_dir, pr.pair_key, en_file, alignment)

    bilingual_store.save_pair_index(
        kb_dir,
        pr.pair_key,
        {
            "pair_key": pr.pair_key,
            "origin": pr.origin,
            "status": "en_only",
            "en_source_id": pair_status.en_source_id,
            "en_url": pair_status.en_url,
            "en_pages": pr.en_pages,
            "synced_at": _utcnow_iso(),
            "navigation": en_crawl.get("navigation", {}),
        },
    )


# ── crawl + write ────────────────────────────────────────────────────


async def _crawl_and_write(
    kb_name: str,
    source: dict,
    raw_dir: Path,
    *,
    max_depth: int | None,
    max_pages: int | None,
) -> tuple[dict, list[str]]:
    """Crawl one source and write changed pages to ``raw/``.

    Thin wrapper around :func:`crawl_and_diff` that returns
    ``(crawl_summary_dict, changed_file_paths)``.
    """
    diff = await crawl_and_diff(
        source,
        raw_dir,
        max_depth=max_depth,
        max_pages=max_pages,
    )
    summary = {
        "ok": diff.ok,
        "error": diff.error,
        "page_count": diff.page_count,
        "page_files": diff.page_files,
        "pages_added": len(diff.pages_added),
        "pages_updated": len(diff.pages_updated),
        "pages_removed": len(diff.pages_removed),
        "pages_unchanged": len(diff.pages_unchanged),
        "changed_names": diff.changed_names,
        "page_hashes": diff.page_hashes,
        "navigation": diff.navigation,
    }
    return (summary, diff.changed_paths)


# ── state persistence ────────────────────────────────────────────────


def _persist_sync_state(
    kb_name: str,
    base_dir: str,
    sources: list[dict],
    pairs: list[LanguagePair],
    result: KBSyncResult,
) -> None:
    """Persist per-source sync state into metadata.json."""
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    now = _utcnow_iso()

    for pair, pr in zip(pairs, result.pair_results):
        for sr in pr.source_results:
            sid = sr.get("source_id", "")
            if not sid:
                continue
            manager.update_web_source_state(
                kb_name=kb_name,
                source_id=sid,
                page_hashes=sr.get("page_hashes", {}),
                page_count=sr.get("page_count", 0),
                last_synced_at=now,
                last_sync_status="success" if sr.get("ok") else "error",
                last_sync_error=sr.get("error") or None,
                language=sr.get("language", ""),
                pair_key=pr.pair_key,
                pair_status=pr.status,
                paired_pages=pr.paired_pages,
                coverage=round(min(pr.paired_pages / sr.get("page_count", 1), 1.0), 4)
                if sr.get("page_count")
                else None,
            )
