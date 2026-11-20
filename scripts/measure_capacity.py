#!/usr/bin/env python3
"""Measure what the media pipeline actually does under concurrency.

Gate 8's capacity column asks for a number, so this produces one from this host
rather than from a guess: N concurrent jobs, wall time, per-kind latency, and
the resident memory the worker holds while doing it.

    python scripts/measure_capacity.py --jobs 24 --concurrency 6

Writes JSON to stdout so the result can be committed as evidence.

What it does *not* measure: provider rate limits, network latency, or GPU
throughput. The renderers here are Pillow and the stand-in video/audio
encoders, so these are the pipeline's own costs -- submission, accounting,
queueing, rendering, storage, settlement -- which is what the phase controls.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _rss_mb() -> float:
    """Resident memory of this process, without psutil."""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--tokens", type=int, default=200_000)
    args = parser.parse_args()

    from deeptutor.db.config import DatabaseSettings
    from deeptutor.db.connection import Database
    from deeptutor.db.jobs.queue import JobQueue
    from deeptutor.db.migrate import apply_pending
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.db.repositories.wallets import WalletRepository
    from deeptutor.services.studio import jobs as S

    tmp = tempfile.mkdtemp(prefix="capacity-")
    dsn = f"sqlite:///{tmp}/capacity.db"
    settings = DatabaseSettings(app_url=dsn, migration_url=dsn, backend="sqlite")
    db = Database(settings)
    apply_pending(db)

    objects = Path(tmp) / "objects"
    objects.mkdir()
    os.environ["DEEPTUTOR_STUDIO_OBJECTS"] = str(objects)

    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    WalletRepository(db).grant("u1", tokens=args.tokens)

    queue = JobQueue(db, worker_id="capacity")
    kinds = list(S.MEDIA_KINDS)
    text = "مشتق نرخ تغییر لحظه‌ای است. مشتق سرعت نسبت به زمان است. " * 3

    baseline_rss = _rss_mb()
    peak_rss = baseline_rss
    lock = threading.Lock()

    def render(kind: str, payload: dict) -> S.RenderResult:
        """The real render path, exactly what the worker calls."""
        from deeptutor.services.studio import render
        from deeptutor.services.studio import script as script_mod

        built = script_mod.build_script(
            script_mod.ScriptRequest(
                kind=kind,
                source_text=payload["script"],
                source_id=payload.get("source_id", ""),
                chapter_title=payload.get("chapter_title", ""),
            )
        )
        data, mime = render.render_local(
            kind, built, title=payload.get("chapter_title", ""),
            attribution=payload.get("attribution", ""),
        )
        path = objects / f"{kind}-{time.time_ns()}.bin"
        path.write_bytes(data)
        return S.RenderResult(
            storage_path=str(path), mime_type=mime, size_bytes=len(data),
            actual_tokens=0, provider="local",
        )

    started = time.perf_counter()
    latencies: dict[str, list[float]] = {kind: [] for kind in kinds}
    errors: list[str] = []

    def one(index: int) -> None:
        nonlocal peak_rss
        kind = kinds[index % len(kinds)]
        t0 = time.perf_counter()
        try:
            submitted = S.submit(
                db,
                queue=queue,
                request=S.JobRequest(
                    user_id="u1",
                    kind=kind,
                    script=text,
                    source_id="",
                    licence_code="cc-by",
                    chapter_title="اندازه‌گیری ظرفیت",
                ),
            )
            queue.run_once({S.job_kind(kind): lambda job: S.run_job(
                db, queue=queue, job=job, renderer=render
            )})
            elapsed = time.perf_counter() - t0
            with lock:
                latencies[kind].append(elapsed)
        except Exception as exc:  # noqa: BLE001 - recorded, then reported
            with lock:
                errors.append(f"{kind} #{index}: {type(exc).__name__}: {exc}")
        with lock:
            peak_rss = max(peak_rss, _rss_mb())

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(one, range(args.jobs)))

    wall = time.perf_counter() - started
    completed = sum(len(v) for v in latencies.values())

    report = {
        "host": {
            "cpu_count": os.cpu_count(),
            "python": sys.version.split()[0],
            "backend": "sqlite",
            "renderers": "Pillow (real) + labelled stand-ins for video/audio",
        },
        "configuration": {
            "jobs": args.jobs,
            "concurrency": args.concurrency,
            "kinds": kinds,
        },
        "results": {
            "completed": completed,
            "errors": len(errors),
            "error_samples": errors[:5],
            "wall_seconds": round(wall, 3),
            "throughput_jobs_per_second": round(completed / wall, 2)
            if wall else 0.0,
        },
        "latency_seconds": {
            kind: {
                "count": len(values),
                "mean": round(statistics.fmean(values), 3) if values else None,
                "p50": round(statistics.median(values), 3) if values else None,
                "max": round(max(values), 3) if values else None,
            }
            for kind, values in latencies.items()
        },
        "memory_mb": {
            "baseline_rss": round(baseline_rss, 1),
            "peak_rss": round(peak_rss, 1),
            "growth": round(peak_rss - baseline_rss, 1),
        },
        "what_this_does_not_measure": (
            "provider rate limits, network latency and GPU throughput: the "
            "renderers are local, so these figures are the pipeline's own cost "
            "(submit, account, queue, render, store, settle)"
        ),
    }
    db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
