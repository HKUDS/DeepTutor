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

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Any

from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR
from deeptutor.services.web_source.crawler import crawl_and_diff

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

    @property
    def total_changes(self) -> int:
        return self.pages_added + self.pages_updated + self.pages_removed


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _url_to_filename(url: str, base_path_prefix: str) -> str:
    """Stable ``.md`` filename derived from a page URL."""
    from deeptutor.services.web_source.crawler import _to_filename

    return _to_filename(url, base_path_prefix)


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

    Prefer :func:`~orchestrator.sync_kb_sources_safe` for new code —
    it batches bilingual alignment and rebuilds the index once.
    """
    kb_dir = Path(base_dir) / kb_name
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    diff = await crawl_and_diff(
        source, raw_dir,
        max_depth=max_depth, max_pages=max_pages,
    )

    if not diff.ok:
        return WebSyncResult(ok=False, error=diff.error)

    # Index changed files via the standard KB pipeline (legacy per-file).
    indexed = 0
    if diff.changed_paths:
        try:
            from deeptutor.knowledge.add_documents import add_documents

            indexed = await add_documents(
                kb_name=kb_name,
                source_files=diff.changed_paths,
                base_dir=base_dir,
                allow_duplicates=False,
            )
        except Exception as exc:
            logger.warning("Indexing failed for web source files: %s", exc)

    # Remove deleted pages from index (legacy per-file removal).
    removed_count = 0
    for fname in diff.pages_removed:
        target = raw_dir / fname
        if target.exists():
            try:
                from deeptutor.knowledge.add_documents import remove_raw_document

                remove_raw_document(kb_dir, target)
                removed_count += 1
            except Exception as exc:
                logger.warning("Failed to remove %s: %s", fname, exc)

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
    )

    logger.info(
        "Web sync %s: +%d ~%d -%d (%d unchanged), %d indexed",
        diff.url, len(diff.pages_added), len(diff.pages_updated), removed_count,
        len(diff.pages_unchanged), indexed,
    )

    return WebSyncResult(
        ok=True,
        pages_added=len(diff.pages_added),
        pages_updated=len(diff.pages_updated),
        pages_removed=removed_count,
        pages_unchanged=len(diff.pages_unchanged),
    )


# Navigation helpers live in navigation.py now.
# These aliases keep backward compatibility for existing imports/tests.
from deeptutor.services.web_source.navigation import (  # noqa: F401, E402
    build_navigation_manifest as _build_navigation_manifest_impl,
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
