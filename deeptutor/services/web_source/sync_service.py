"""Background service that periodically syncs web sources into KBs."""

from __future__ import annotations

import logging

from deeptutor.services.base_sync import BaseSourceSyncService, is_stale
from deeptutor.services.web_source.jobs import WebSyncConflictError, submit_web_sync
from deeptutor.services.web_source.orchestrator import WEB_SYNC_INTERVAL_HOURS

logger = logging.getLogger(__name__)


class WebSourceSyncService(BaseSourceSyncService):
    """Periodically syncs all web sources, grouped by KB for bilingual pairing."""

    @property
    def task_name(self) -> str:
        return "web-source-sync"

    async def _sync_one_cycle(self) -> None:
        from deeptutor.knowledge.manager import KnowledgeBaseManager

        base_dir = self.effective_base_dir
        manager = KnowledgeBaseManager(base_dir=base_dir)

        # Group all web sources by KB so we can sync each KB as a unit
        # (bilingual pairing requires seeing all sources together).
        all_sources = manager.get_all_web_sources()
        kb_sources: dict[str, list[dict]] = {}
        for kb_name, source in all_sources:
            kb_sources.setdefault(kb_name, []).append(source)

        for kb_name, sources in kb_sources.items():
            enabled = [s for s in sources if s.get("enabled", True)]
            if not enabled:
                continue
            if not any(
                is_stale(
                    s, stale_hours=float(s.get("sync_interval_hours") or WEB_SYNC_INTERVAL_HOURS)
                )
                for s in enabled
            ):
                continue
            logger.info(
                "Queueing scheduled sync for %d web source(s) in KB '%s'", len(enabled), kb_name
            )
            try:
                submit_web_sync(
                    kb_name=kb_name,
                    sources=enabled,
                    kb_base_dir=base_dir,
                    trigger="scheduled",
                )
            except WebSyncConflictError as exc:
                logger.info(
                    "Scheduled web sync skipped for KB '%s'; job '%s' is active",
                    kb_name,
                    exc.job.get("job_id", ""),
                )
            except Exception:
                logger.exception("Failed to queue scheduled web sync for KB '%s'", kb_name)


_web_sync_service = None


def get_web_sync_service():
    global _web_sync_service
    if _web_sync_service is None:
        _web_sync_service = WebSourceSyncService()
    return _web_sync_service


# Backward-compatible alias for tests that import _is_stale directly.
def _is_stale(source: dict) -> bool:
    return is_stale(source, stale_hours=WEB_SYNC_INTERVAL_HOURS)
