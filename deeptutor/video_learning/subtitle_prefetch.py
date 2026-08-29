"""Single-flight background subtitle fetches using an opted-in host Chrome."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from deeptutor.video_learning.service import (
    TimedMediaStore,
    build_segments,
    download_ytdlp_subtitle,
)
from deeptutor.video_learning.youtube_session import HostChromeSessionStore


def _fetch_state(material: dict[str, Any]) -> dict[str, Any]:
    transcript = material.setdefault("transcript", {})
    fetch = transcript.setdefault("fetch", {}) if isinstance(transcript, dict) else {}
    return fetch if isinstance(fetch, dict) else {}


def _set_fetch(material: dict[str, Any], status: str, *, error_code: str | None = None) -> dict[str, Any]:
    fetch = _fetch_state(material)
    fetch.update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), "error_code": error_code})
    return fetch


class SubtitlePrefetchService:
    """One global worker so a shared YouTube egress is not burst concurrently."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: set[tuple[str, str]] = set()

    async def enqueue(self, owner_id: str, material_id: str, store: TimedMediaStore, *, manual: bool = False) -> dict[str, Any]:
        with store.lock(material_id):
            material = store.get(material_id)
            if (material.get("transcript") or {}).get("cues"):
                return _fetch_state(material)
            if not HostChromeSessionStore.enabled(owner_id):
                state = _set_fetch(material, "auth_required", error_code="auth_required")
                store.save(material)
                return state
            state = _set_fetch(material, "queued")
            store.save(material)
        key = (owner_id, material_id)
        if key not in self._pending:
            self._pending.add(key)
            asyncio.create_task(self._fetch(owner_id, material_id, store, key), name=f"youtube-subtitles-{material_id}")
        return state

    async def _fetch(self, owner_id: str, material_id: str, store: TimedMediaStore, key: tuple[str, str]) -> None:
        try:
            async with self._lock:
                with store.lock(material_id):
                    material = store.get(material_id)
                    if (material.get("transcript") or {}).get("cues") or not HostChromeSessionStore.enabled(owner_id):
                        return
                    _set_fetch(material, "fetching")
                    store.save(material)
                    video_id = str((material.get("source") or {}).get("video_id") or "")
                    preferred = str((material.get("transcript") or {}).get("language") or "")
                cues, language, code = await download_ytdlp_subtitle(video_id, preferred_language=preferred)
                with store.lock(material_id):
                    latest = store.get(material_id)
                    if (latest.get("transcript") or {}).get("cues"):
                        return
                    if cues:
                        latest["transcript"] = {
                            "language": language or preferred or "en",
                            "source": "youtube-chrome",
                            "cues": cues,
                            "fetch": _set_fetch(latest, "ready"),
                        }
                        latest["segments"] = build_segments(cues)
                    else:
                        _set_fetch(latest, "auth_required" if code == "auth_required" else "unavailable", error_code=code)
                    store.save(latest)
        finally:
            self._pending.discard(key)


_service = SubtitlePrefetchService()


def get_subtitle_prefetch_service() -> SubtitlePrefetchService:
    return _service
