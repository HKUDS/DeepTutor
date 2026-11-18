"""The media worker: claims queued media jobs and finishes them.

Why this is a separate loop from the API process
------------------------------------------------
A video job holds a lease for minutes. Running it inside the request-serving
process means a slow render competes with chat for the same event loop, which is
the exact failure the phase's acceptance criterion forbids ("video/audio
failures must not disturb normal chat"). The worker is therefore something you
start on purpose, and the API stays responsive whether or not it is running --
a job simply waits in the queue.

Stopping is safe at any point
-----------------------------
The queue's lease is what makes a killed worker recoverable: an unfinished job
whose lease expires is reclaimed and retried. That is why this loop never needs
a graceful-shutdown ritual to be correct -- it needs it only to be *polite*.
The one thing it must not do is settle a job it did not finish, and it cannot:
settlement happens after the renderer returns, never before.

Cancellation
------------
Checked before the renderer is called and again after it returns (inside
``run_job``). The queue cannot preempt a running handler, so a cancelled job
still finishes its provider call -- but it is refunded rather than charged, and
its artefact is not stored. Wasting a render is cheaper than billing for work
the student cancelled.
"""

from __future__ import annotations

import logging
import signal
import threading
from typing import Any, Callable, Mapping

from deeptutor.db.connection import Database
from deeptutor.db.jobs.queue import ClaimedJob, JobQueue
from deeptutor.services.studio import jobs as studio

logger = logging.getLogger(__name__)


def _script_for(kind: str, payload: Mapping[str, Any]) -> Any:
    """Rebuild the script a job was submitted with.

    The script is carried in the payload rather than regenerated: the student
    may have edited it between submit and run, and regenerating would quietly
    render something they did not approve.
    """
    from deeptutor.services.studio.script import ScriptRequest, build_script

    script_text = str(payload.get("script") or "")
    source_id = payload.get("source_id")
    if source_id:
        return build_script(
            ScriptRequest(
                kind=kind,
                source_text=script_text,
                source_id=str(source_id),
                chapter_title=str(payload.get("chapter_title") or ""),
                licence_code=str(payload.get("licence_code") or ""),
            )
        )
    return build_script(
        ScriptRequest(
            kind=kind,
            prompt=script_text,
            chapter_title=str(payload.get("chapter_title") or ""),
            licence_code=str(payload.get("licence_code") or ""),
        )
    )


def local_renderer(kind: str, payload: Mapping[str, Any]) -> studio.RenderResult:
    """Render with the on-host renderers and store the bytes.

    The token cost is *measured*, not looked up: the renderer knows how many
    characters it produced, and character count is the honest proxy for what a
    speech or image model would charge when no such model is being called.
    """
    from deeptutor.db.storage import get_object_store
    from deeptutor.services.studio.render import render_local

    script = _script_for(kind, payload)
    rendered = render_local(kind, payload, script=script)

    store = get_object_store()
    key = store.put(rendered.data, namespace="media", key=f"{payload['content_hash'][:16]}{rendered.extension}")

    # A real, measured figure: one token per four characters of output is the
    # usual English approximation and is close enough for Persian; the point is
    # that the number derives from the artefact rather than from a table.
    measured = max(1, len(script.text) // 4)

    return studio.RenderResult(
        storage_path=key,
        mime_type=rendered.mime_type,
        content=str(rendered.note),
        size_bytes=len(rendered.data),
        duration_seconds=_duration(rendered.data, rendered.mime_type),
        actual_tokens=measured,
        provider="local",
    )


def _duration(data: bytes, mime_type: str) -> float | None:
    if mime_type != "audio/wav":
        return None
    import io
    import wave

    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            return round(handle.getnframes() / handle.getframerate(), 2)
    except Exception:  # noqa: BLE001 - a duration we cannot read is simply absent
        return None


def handlers(
    db: Database, queue: JobQueue, renderer: Callable[[str, Mapping[str, Any]], studio.RenderResult]
) -> dict[str, Callable[[ClaimedJob], Any]]:
    """One handler per media kind, all sharing the same lifecycle."""

    def make(kind: str) -> Callable[[ClaimedJob], Any]:
        def handle(job: ClaimedJob) -> Any:
            return studio.run_job(db, queue=queue, job=job, renderer=renderer)

        handle.__name__ = f"handle_{kind}"
        return handle

    return {studio.job_kind(kind): make(kind) for kind in studio.MEDIA_KINDS}


def drain(
    db: Database,
    *,
    worker_id: str = "media-worker",
    renderer: Callable[[str, Mapping[str, Any]], studio.RenderResult] | None = None,
    limit: int = 100,
    lease_seconds: int = 300,
) -> int:
    """Process up to *limit* jobs, then return. The unit tests and the smoke
    test both use this; the long-running loop is :func:`serve`."""
    queue = JobQueue(db, worker_id=worker_id)
    table = handlers(db, queue, renderer or local_renderer)
    return int(queue.run_once(table, limit=limit, lease_seconds=lease_seconds) or 0)


def serve(
    db: Database,
    *,
    worker_id: str = "media-worker",
    renderer: Callable[[str, Mapping[str, Any]], studio.RenderResult] | None = None,
    poll_seconds: float = 2.0,
    stop: threading.Event | None = None,
) -> None:
    """Run until stopped.

    The loop is deliberately dumb: claim, run, sleep. Backoff, retry limits and
    lease expiry all live in the queue, and duplicating them here would give the
    system two opinions about how many times a job may fail.
    """
    stop = stop or threading.Event()
    previous: dict[int, Any] = {}

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("media worker %s received signal %s; finishing current job", worker_id, signum)
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[signum] = signal.signal(signum, _handle_signal)
        except ValueError:  # pragma: no cover - not the main thread
            pass

    queue = JobQueue(db, worker_id=worker_id)
    table = handlers(db, queue, renderer or local_renderer)
    logger.info("media worker %s started", worker_id)

    try:
        while not stop.is_set():
            try:
                processed = queue.run_once(table, limit=1)
            except Exception:  # noqa: BLE001 - a bad job must not kill the loop
                logger.exception("media worker %s: run_once failed", worker_id)
                processed = 0
            if not processed:
                stop.wait(poll_seconds)
    finally:
        for signum, handler in previous.items():
            try:
                signal.signal(signum, handler)
            except ValueError:  # pragma: no cover
                pass
        logger.info("media worker %s stopped", worker_id)


def main() -> int:  # pragma: no cover - process entry point
    """``python -m deeptutor.services.studio.worker``."""
    import os

    logging.basicConfig(
        level=os.environ.get("DEEPTUTOR_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from deeptutor.db.config import get_database_settings

    settings = get_database_settings()
    if not settings.enabled:
        logger.error("no database configured; set DEEPTUTOR_DATABASE_URL")
        return 2

    from deeptutor.db.connection import open_database

    database = open_database(settings)
    if database is None:  # pragma: no cover
        logger.error("could not open the database")
        return 2
    try:
        serve(database, worker_id=os.environ.get("DEEPTUTOR_WORKER_ID", "media-worker"))
    finally:
        database.close()
    return 0


__all__ = ["drain", "handlers", "local_renderer", "main", "serve"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
