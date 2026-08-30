"""Single-flight background subtitle fetches using an opted-in host Chrome."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from deeptutor.video_learning.service import (
    TimedMediaStore,
    build_segments,
    download_ytdlp_subtitle,
)
from deeptutor.video_learning.youtube_session import HostChromeSessionStore

RETRY_DELAYS = (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6), timedelta(days=1), timedelta(days=3))


def _fetch_state(material: dict[str, Any]) -> dict[str, Any]:
    transcript = material.setdefault("transcript", {})
    fetch = transcript.setdefault("fetch", {}) if isinstance(transcript, dict) else {}
    return fetch if isinstance(fetch, dict) else {}


def _set_fetch(
    material: dict[str, Any],
    status: str,
    *,
    error_code: str | None = None,
    attempts: int | None = None,
    next_retry_at: str | None = None,
) -> dict[str, Any]:
    fetch = _fetch_state(material)
    fetch.update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), "error_code": error_code})
    if attempts is not None:
        fetch["attempts"] = attempts
    if status != "retry_wait" or next_retry_at is not None:
        fetch["next_retry_at"] = next_retry_at
    return fetch


def _retry_deadline(fetch: dict[str, Any]) -> datetime | None:
    raw = fetch.get("next_retry_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class SubtitlePrefetchService:
    """One global worker so a shared YouTube egress is not burst concurrently."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: set[tuple[str, str]] = set()

    async def enqueue(self, owner_id: str, material_id: str, store: TimedMediaStore, *, manual: bool = False) -> dict[str, Any]:
        key = (owner_id, material_id)
        with store.lock(material_id):
            material = store.get(material_id)
            if (material.get("transcript") or {}).get("cues"):
                return _fetch_state(material)
            existing = _fetch_state(material)
            status = str(existing.get("status") or "not_requested")
            if status in {"queued", "fetching"} and key in self._pending:
                return existing
            if status == "retry_wait":
                deadline = _retry_deadline(existing)
                if deadline and deadline > datetime.now(timezone.utc):
                    return existing
            if status in {"auth_required", "unavailable", "error"} and not manual:
                return existing
            if not HostChromeSessionStore.enabled(owner_id):
                state = _set_fetch(
                    material,
                    "auth_required",
                    error_code="auth_required",
                    attempts=int(existing.get("attempts") or 0),
                    next_retry_at=None,
                )
                store.save(material)
                return state
            state = _set_fetch(
                material,
                "queued",
                attempts=int(existing.get("attempts") or 0),
                next_retry_at=None,
            )
            store.save(material)
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
                    previous = _fetch_state(material)
                    attempts = int(previous.get("attempts") or 0) + 1
                    _set_fetch(material, "fetching", attempts=attempts, next_retry_at=None)
                    store.save(material)
                    video_id = str((material.get("source") or {}).get("video_id") or "")
                    preferred = str((material.get("transcript") or {}).get("language") or "")
                cues, language, code = await download_ytdlp_subtitle(video_id, preferred_language=preferred)
                with store.lock(material_id):
                    latest = store.get(material_id)
                    if (latest.get("transcript") or {}).get("cues"):
                        return
                    if cues:
                        fetch = _set_fetch(latest, "ready", attempts=attempts, next_retry_at=None)
                        latest["transcript"] = {
                            "language": language or preferred or "en",
                            "source": "youtube-chrome",
                            "cues": cues,
                            "fetch": fetch,
                        }
                        latest["segments"] = build_segments(cues)
                    else:
                        if code in {"rate_limited", "temporary_error"}:
                            delay = RETRY_DELAYS[min(max(attempts - 1, 0), len(RETRY_DELAYS) - 1)]
                            retry_at = (datetime.now(timezone.utc) + delay).isoformat()
                            _set_fetch(
                                latest,
                                "retry_wait",
                                error_code=code,
                                attempts=attempts,
                                next_retry_at=retry_at,
                            )
                        else:
                            _set_fetch(
                                latest,
                                "auth_required" if code == "auth_required" else "unavailable",
                                error_code=code,
                                attempts=attempts,
                                next_retry_at=None,
                            )
                    store.save(latest)
        finally:
            self._pending.discard(key)


_service = SubtitlePrefetchService()


def get_subtitle_prefetch_service() -> SubtitlePrefetchService:
    return _service
