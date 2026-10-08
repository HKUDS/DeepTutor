"""Sync logic: crawl a doc site and ingest pages into a KB.

``sync_source()`` mirrors the GitHub-source sync flow:
1. Crawl the site from the configured base URL.
2. Compare page hashes with those stored in metadata.
3. Write new/changed pages to the KB ``raw/`` directory as ``.md`` files.
4. Remove pages that were present before but are no longer on the site.
5. Feed changed files through ``add_documents()`` for indexing.
6. Persist updated page hashes + sync status to ``metadata.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR
from deeptutor.services.web_source.crawler import _contained_path, crawl_and_diff

logger = logging.getLogger(__name__)

WEB_SYNC_INTERVAL_HOURS = 24


@dataclass
class WebSyncResult:
    """Outcome of a single ``sync_source()`` invocation."""

    ok: bool
    pages_added: int = 0
    pages_updated: int = 0
    pages_removed: int = 0
    pages_unchanged: int = 0
    error: str = ""
    bilingual_pairs_count: int = 0

    @property
    def total_changes(self) -> int:
        return self.pages_added + self.pages_updated + self.pages_removed


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _url_to_filename(url: str, base_path_prefix: str) -> str:
    """Stable ``.md`` filename derived from a page URL."""
    from deeptutor.services.web_source.crawler import _to_filename

    return _to_filename(url, base_path_prefix)


def _record_sync_failure(
    kb_name: str,
    source_id: str,
    base_dir: str,
    error: str,
) -> None:
    """Persist a visible error without advancing hashes past failed indexing."""
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    try:
        KnowledgeBaseManager(base_dir=base_dir).update_web_source_state(
            kb_name=kb_name,
            source_id=source_id,
            last_synced_at=_utcnow_iso(),
            last_sync_status="error",
            last_sync_error=error,
        )
    except Exception:
        logger.exception("Failed to persist web-source sync failure state")


async def _rebuild_index_after_removal(
    kb_name: str,
    raw_dir: Path,
    base_dir: str,
) -> int:
    """Rebuild the bound provider so removed pages cannot remain retrievable."""
    from deeptutor.services.rag.file_routing import FileTypeRouter
    from deeptutor.services.rag.service import RAGService

    files = FileTypeRouter.collect_supported_files(raw_dir, recursive=True)
    if not files:
        raise RuntimeError("No source files remain after removing deleted web pages")
    success = await RAGService(kb_base_dir=base_dir).initialize(
        kb_name=kb_name,
        file_paths=[str(path) for path in files],
    )
    if not success:
        raise RuntimeError("The knowledge-base index rebuild produced no documents")
    return len(files)


async def sync_source(
    kb_name: str,
    source: dict[str, Any],
    *,
    base_dir: str = DEFAULT_BASE_DIR,
    max_depth: int | None = None,
    max_pages: int | None = None,
) -> WebSyncResult:
    """Crawl and sync one web source into the named KB (legacy per-file path).

    Uses :func:`crawl_and_diff` for the shared crawl-write-diff pipeline,
    then indexes changed files individually via ``add_documents``.

    This is the bounded, on-demand sync path used by the API and CLI.
    """
    kb_dir = Path(base_dir) / kb_name
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        diff = await crawl_and_diff(
            source,
            raw_dir,
            max_depth=max_depth,
            max_pages=max_pages,
        )
    except Exception as exc:
        logger.exception("Crawl failed for %s", source["url"])
        error = str(exc)
        _record_sync_failure(kb_name, source["id"], base_dir, error)
        return WebSyncResult(ok=False, error=error)
    if not diff.ok:
        _record_sync_failure(kb_name, source["id"], base_dir, diff.error)
        return WebSyncResult(ok=False, error=diff.error)

    # Remove deleted raw pages and their file-hash records first. A full
    # provider rebuild below is required because most providers do not expose
    # a reliable per-document vector deletion operation.
    removed_count = 0
    removal_errors: list[str] = []
    for fname in diff.pages_removed:
        target = _contained_path(raw_dir, fname)
        if target is None:
            removal_errors.append(f"{fname}: path escapes the knowledge base")
            continue
        try:
            from deeptutor.knowledge.add_documents import remove_raw_document

            remove_raw_document(kb_dir, target)
            removed_count += 1
        except Exception as exc:
            logger.warning("Failed to remove %s: %s", fname, exc)
            removal_errors.append(f"{fname}: {exc}")

    if removal_errors:
        error = "Failed to remove deleted pages: " + "; ".join(removal_errors)
        _record_sync_failure(kb_name, source["id"], base_dir, error)
        return WebSyncResult(ok=False, error=error)

    indexed = 0
    try:
        if diff.pages_removed:
            indexed = await _rebuild_index_after_removal(kb_name, raw_dir, base_dir)
        elif diff.changed_paths:
            from deeptutor.knowledge.add_documents import add_documents

            indexed = await add_documents(
                kb_name=kb_name,
                source_files=diff.changed_paths,
                base_dir=base_dir,
                allow_duplicates=False,
            )
    except Exception as exc:
        logger.warning("Indexing failed for web source files: %s", exc)
        error = f"Indexing failed: {exc}"
        _record_sync_failure(kb_name, source["id"], base_dir, error)
        return WebSyncResult(ok=False, error=error)

    # Persist sync state.
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    manager.update_web_source_state(
        kb_name=kb_name,
        source_id=source["id"],
        page_hashes=diff.page_hashes,
        page_count=diff.page_count,
        last_synced_at=_utcnow_iso(),
        last_sync_status="success",
        last_sync_error=None,
        navigation=diff.navigation,
        bilingual_pairings=diff.pairings,
    )

    try:
        from deeptutor.multi_user.context import get_current_user
        from deeptutor.services.web_source.scheduler import get_web_source_sync_scheduler

        user = get_current_user()
        scheduler = get_web_source_sync_scheduler()
        scheduler.repo.record_pairings(
            owner_id=user.id,
            kb_name=kb_name,
            source_id=source["id"],
            pairings=diff.pairings,
        )
    except Exception:
        logger.debug("Failed to record pairings in SQLite repo", exc_info=True)

    logger.info(
        "Web sync %s: +%d ~%d -%d (%d unchanged), %d indexed, %d bilingual pairs",
        diff.url,
        len(diff.pages_added),
        len(diff.pages_updated),
        removed_count,
        len(diff.pages_unchanged),
        indexed,
        len(diff.pairings),
    )

    return WebSyncResult(
        ok=True,
        pages_added=len(diff.pages_added),
        pages_updated=len(diff.pages_updated),
        pages_removed=removed_count,
        pages_unchanged=len(diff.pages_unchanged),
        bilingual_pairs_count=len(diff.pairings),
    )


# Navigation helpers live in navigation.py now.
# These aliases keep backward compatibility for existing imports/tests.
from deeptutor.services.web_source.navigation import (  # noqa: F401, E402
    build_navigation_manifest as _build_navigation_manifest_impl,
)
from deeptutor.services.web_source.navigation import (
    flat_to_tree as _flat_to_tree_impl,
)


def _build_navigation_manifest(
    nav_links: list[dict],
    nav_kind: str,
    page_urls: dict[str, str],
    base_path_prefix: str = "",
) -> dict:
    """Backward-compatible wrapper around navigation.build_navigation_manifest."""
    return _build_navigation_manifest_impl(nav_links, nav_kind, page_urls)


def _flat_to_tree(
    links: list[dict],
    url_to_file: dict[str, str],
) -> list[dict]:
    """Backward-compatible alias for navigation.flat_to_tree."""
    return _flat_to_tree_impl(links, url_to_file)
