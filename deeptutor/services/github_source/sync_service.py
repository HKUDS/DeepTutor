"""Background service that periodically syncs GitHub sources into KBs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from deeptutor.services.base_sync import BaseSourceSyncService, is_stale
from deeptutor.services.github_source.sync import SYNC_INTERVAL_HOURS

logger = logging.getLogger(__name__)


class GitHubSourceSyncService(BaseSourceSyncService):
    """Periodically syncs all GitHub sources."""

    def __init__(self, *, base_dir=None, client=None, check_interval_s=3600):
        super().__init__(base_dir=base_dir, check_interval_s=check_interval_s)
        self._client = client

    @property
    def task_name(self) -> str:
        return "github-source-sync"

    async def _sync_one_cycle(self) -> None:
        from deeptutor.knowledge.manager import KnowledgeBaseManager
        from deeptutor.services.github_source.sync import sync_source

        base_dir = self.effective_base_dir
        manager = KnowledgeBaseManager(base_dir=base_dir)

        all_sources = manager.get_all_github_sources()
        for kb_name, source in all_sources:
            if not source.get("enabled", True):
                continue
            if not is_stale(source, stale_hours=SYNC_INTERVAL_HOURS):
                continue
            sid = source.get("id", "?")
            try:
                result = await sync_source(
                    kb_name=kb_name,
                    source=source,
                    base_dir=base_dir,
                    client=self._client,
                )
                if not result.ok:
                    manager.update_github_source_state(
                        kb_name=kb_name,
                        source_id=sid,
                        last_sync_status="error",
                        last_sync_error=result.error,
                        last_synced_at=datetime.now(timezone.utc).isoformat(),
                    )
            except Exception as exc:
                manager.update_github_source_state(
                    kb_name=kb_name,
                    source_id=sid,
                    last_sync_status="error",
                    last_sync_error=str(exc),
                    last_synced_at=datetime.now(timezone.utc).isoformat(),
                )


_sync_service = None


def get_sync_service():
    global _sync_service
    if _sync_service is None:
        _sync_service = GitHubSourceSyncService()
    return _sync_service
