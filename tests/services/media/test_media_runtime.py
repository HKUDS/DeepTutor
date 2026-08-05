"""MED-03 focused tests: media runtime lifecycle wiring (spec §11.3/§11.5).

Covers restart recovery across roots, the background scheduler advancing
queued/polling/cancel jobs, and clean startup/shutdown of the executor
resources — all offline with injected executors and clocks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import uuid

import pytest

from deeptutor.services.media.models import (
    BackgroundSubmit,
    ImageGenerationJob,
    ImageJobStatus,
    MediaInput,
    PollOutcome,
)
from deeptutor.services.media.runtime import (
    MediaRuntimeManager,
    discover_media_roots,
    get_media_runtime,
    reset_media_runtime,
)
from deeptutor.services.media.store import MediaStore
from tests.services.media._media_helpers import FakeExecutor, make_media_input


class ManualClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now_value = start
        self.slept: list[float] = []

    def now(self) -> float:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now_value += seconds
        # Yield control to the event loop so a background scheduler loop can be
        # stopped/interleaved by the test coroutine (production uses
        # ``asyncio.sleep`` which yields naturally).
        await asyncio.sleep(0)


def _raw_job(
    store: MediaStore,
    *,
    status: ImageJobStatus,
    remote_response_id: str = "",
    user_id: str = "u1",
) -> ImageGenerationJob:
    job = ImageGenerationJob(
        id=uuid.uuid4().hex,
        user_id=user_id,
        original_prompt="a red fox",
        request_hash="h",
        status=status,
        remote_response_id=remote_response_id,
    )
    return store.save_job(job)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def runtime(tmp_path: Path, clock: ManualClock) -> MediaRuntimeManager:
    root = Path(tmp_path) / "media"
    manager = MediaRuntimeManager(
        roots=[root],
        sleep=clock.sleep,
        now=clock.now,
    )
    return manager


# ── recovery ─────────────────────────────────────────────────────────────────


def test_recover_marks_no_remote_id_running_as_unknown(runtime: MediaRuntimeManager) -> None:
    store = MediaStore(root=runtime.roots[0])
    job = _raw_job(store, status=ImageJobStatus.RUNNING)
    outcomes = runtime.recover()
    assert any(item["job_id"] == job.id and item["to"] == "unknown" for item in outcomes)


def test_recover_preserves_queued_and_terminal(runtime: MediaRuntimeManager) -> None:
    store = MediaStore(root=runtime.roots[0])
    queued = _raw_job(store, status=ImageJobStatus.QUEUED)
    succeeded = _raw_job(store, status=ImageJobStatus.SUCCEEDED)
    outcomes = runtime.recover()
    assert not any(item["job_id"] == queued.id for item in outcomes)
    assert not any(item["job_id"] == succeeded.id for item in outcomes)


def test_recover_keeps_remote_id_polling_resumable(runtime: MediaRuntimeManager) -> None:
    store = MediaStore(root=runtime.roots[0])
    job = _raw_job(store, status=ImageJobStatus.POLLING, remote_response_id="resp_1")
    outcomes = runtime.recover()
    assert not any(item["job_id"] == job.id for item in outcomes)


def test_recover_keeps_cancel_requested_for_confirmation(
    runtime: MediaRuntimeManager,
) -> None:
    store = MediaStore(root=runtime.roots[0])
    job = _raw_job(store, status=ImageJobStatus.CANCEL_REQUESTED)
    outcomes = runtime.recover()
    assert not any(item["job_id"] == job.id for item in outcomes)


# ── execution ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_once_executes_queued_job(
    runtime: MediaRuntimeManager, clock: ManualClock
) -> None:
    store = MediaStore(root=runtime.roots[0])
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="u1",
            original_prompt="a red fox",
            request_hash="h",
            status=ImageJobStatus.QUEUED,
        )
    )

    class ImmediateExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__(inputs=[make_media_input()])

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    captured: dict[str, object] = {}

    def factory(worker):
        captured["worker"] = worker
        return ImmediateExecutor()

    runtime._executor_factory = factory
    count = await runtime.run_once()
    assert count == 1
    reloaded = store.load_job(job.id)
    assert reloaded is not None
    assert reloaded.status == ImageJobStatus.SUCCEEDED
    assert reloaded.artifact_ids


@pytest.mark.asyncio
async def test_run_once_advances_cancel_requested(
    runtime: MediaRuntimeManager,
) -> None:
    store = MediaStore(root=runtime.roots[0])
    job = _raw_job(store, status=ImageJobStatus.CANCEL_REQUESTED)

    class NoCancelExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__()

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    runtime._executor_factory = lambda worker: NoCancelExecutor()
    await runtime.run_once()
    reloaded = store.load_job(job.id)
    assert reloaded is not None
    assert reloaded.status == ImageJobStatus.CANCELLED_UNCONFIRMED


@pytest.mark.asyncio
async def test_run_once_polls_background_job(
    runtime: MediaRuntimeManager, clock: ManualClock
) -> None:
    store = MediaStore(root=runtime.roots[0])
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="u1",
            original_prompt="a red fox",
            request_hash="h",
            status=ImageJobStatus.POLLING,
            remote_response_id="resp_1",
            poll_after=clock.now_value - 1,
        )
    )

    class PollExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__(inputs=[make_media_input()])

        async def poll(self, job: ImageGenerationJob) -> PollOutcome:
            return PollOutcome(media=[make_media_input()])

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    runtime._executor_factory = lambda worker: PollExecutor()
    await runtime.run_once()
    reloaded = store.load_job(job.id)
    assert reloaded is not None
    assert reloaded.status == ImageJobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_run_once_skips_polling_before_poll_after(
    runtime: MediaRuntimeManager, clock: ManualClock
) -> None:
    store = MediaStore(root=runtime.roots[0])
    job = _raw_job(store, status=ImageJobStatus.POLLING, remote_response_id="resp_1")
    # No poll_after set -> defaults to 0, treated as ready. Set it in the future.
    job = store.update_job(job.id, poll_after=clock.now_value + 100)
    count = await runtime.run_once()
    assert count == 0
    reloaded = store.load_job(job.id)
    assert reloaded is not None and reloaded.status == ImageJobStatus.POLLING


# ── lifecycle ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_stop_runs_background_loop(tmp_path: Path, clock: ManualClock) -> None:
    store = MediaStore(root=Path(tmp_path) / "media")
    _raw_job(store, status=ImageJobStatus.CANCEL_REQUESTED)

    class NoCancelExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__()

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    manager = MediaRuntimeManager(
        roots=[Path(tmp_path) / "media"],
        sleep=clock.sleep,
        now=clock.now,
        executor_factory=lambda worker: NoCancelExecutor(),
    )
    task = manager.start(interval=0.01)
    # Let the loop advance the cancel job a few times.
    for _ in range(5):
        await clock.sleep(0.01)
        await asyncio.sleep(0)
    await manager.stop()
    assert task.done()
    reloaded = store.load_job(store.list_jobs()[0].id)
    assert reloaded is not None
    assert reloaded.status in (ImageJobStatus.CANCELLED, ImageJobStatus.CANCELLED_UNCONFIRMED)


@pytest.mark.asyncio
async def test_aclose_releases_executors(tmp_path: Path) -> None:
    closed: list[str] = []

    class ClosingExecutor(FakeExecutor):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

        async def aclose(self) -> None:
            closed.append(self.name)

    def factory(worker):
        return ClosingExecutor(worker.store.root.name)

    manager = MediaRuntimeManager(
        roots=[Path(tmp_path) / "media-a", Path(tmp_path) / "media-b"],
        executor_factory=factory,
    )
    manager._ensure_executor(Path(tmp_path) / "media-a")
    manager._ensure_executor(Path(tmp_path) / "media-b")
    await manager.aclose()
    assert sorted(closed) == ["media-a", "media-b"]


def test_discover_media_roots_includes_default() -> None:
    roots = discover_media_roots()
    assert roots
    assert isinstance(roots[0], Path)


# ── default executor binding (finding: production never bound the real one) ──


@pytest.mark.asyncio
async def test_get_media_runtime_binds_default_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process singleton uses ``_default_executor_factory``.

    Exercises the exact default construction path used by ``get_media_runtime``
    (no injected executor) and proves an actionable queued job receives the
    factory-built executor instead of terminally failing as ``no_executor``.
    """
    from deeptutor.services.media import runtime as runtime_mod

    default_root = Path(tmp_path) / "media"
    reset_media_runtime()
    monkeypatch.setattr(runtime_mod, "discover_media_roots", lambda: [default_root])

    store = MediaStore(root=default_root)
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="u1",
            original_prompt="a red fox",
            request_hash="h",
            status=ImageJobStatus.QUEUED,
        )
    )

    class ImmediateExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__(inputs=[make_media_input()])

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    monkeypatch.setattr(
        runtime_mod, "_default_executor_factory", lambda worker: ImmediateExecutor()
    )
    try:
        manager = get_media_runtime()
        count = await manager.run_once()
        assert count == 1
        reloaded = store.load_job(job.id)
        assert reloaded is not None
        assert reloaded.status == ImageJobStatus.SUCCEEDED
        assert reloaded.artifact_ids
        assert reloaded.error_code != "no_executor"
    finally:
        await runtime_mod.get_media_runtime().aclose()
        reset_media_runtime()


# ── per-user root refresh (finding: roots only discovered once) ──────────────


@pytest.mark.asyncio
async def test_production_discovery_refreshes_new_user_roots(
    tmp_path: Path,
    clock: ManualClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-user media root created after startup is discovered without restart.

    The manager is built in production-discovery mode (no explicit roots).  A
    user's root that appears *after* initialization must be picked up at the
    next ``run_once`` boundary and that user's queued job must advance.
    """
    from deeptutor.services.media import runtime as runtime_mod

    default_root = Path(tmp_path) / "default" / "workspace" / "media"
    users_root = Path(tmp_path) / "users"

    def fake_discover() -> list[Path]:
        roots = [default_root]
        if users_root.is_dir():
            for user_dir in sorted(users_root.iterdir()):
                candidate = user_dir / "workspace" / "media"
                if candidate.is_dir():
                    roots.append(candidate)
        return roots

    monkeypatch.setattr(runtime_mod, "discover_media_roots", fake_discover)

    class ImmediateExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__(inputs=[make_media_input()])

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    manager = MediaRuntimeManager(
        sleep=clock.sleep,
        now=clock.now,
        executor_factory=lambda worker: ImmediateExecutor(),
    )
    assert manager.roots == [default_root]

    # The user's media root is created AFTER the manager initialized.
    new_root = users_root / "u2" / "workspace" / "media"
    store = MediaStore(root=new_root)
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="u2",
            original_prompt="a red fox",
            request_hash="h",
            status=ImageJobStatus.QUEUED,
        )
    )

    count = await manager.run_once()
    assert count == 1
    assert new_root in manager.roots
    reloaded = store.load_job(job.id)
    assert reloaded is not None
    assert reloaded.status == ImageJobStatus.SUCCEEDED
    # The root was added exactly once.
    assert manager.roots.count(new_root) == 1


@pytest.mark.asyncio
async def test_explicit_roots_manager_never_scans_global_roots(
    tmp_path: Path,
    clock: ManualClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Managers built with explicit ``roots=[...]`` stay fixed and deterministic."""
    from deeptutor.services.media import runtime as runtime_mod

    explicit_root = Path(tmp_path) / "explicit" / "media"
    store = MediaStore(root=explicit_root)
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="u1",
            original_prompt="a red fox",
            request_hash="h",
            status=ImageJobStatus.QUEUED,
        )
    )

    class ImmediateExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__(inputs=[make_media_input()])

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    # Unrelated global roots that appear later must never be scanned.
    monkeypatch.setattr(
        runtime_mod, "discover_media_roots", lambda: [Path(tmp_path) / "global" / "media"]
    )

    manager = MediaRuntimeManager(
        roots=[explicit_root],
        sleep=clock.sleep,
        now=clock.now,
        executor_factory=lambda worker: ImmediateExecutor(),
    )
    count = await manager.run_once()
    assert count == 1
    assert manager.roots == [explicit_root]
    reloaded = store.load_job(job.id)
    assert reloaded is not None and reloaded.status == ImageJobStatus.SUCCEEDED


# ── multi-root ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_once_advances_all_roots(tmp_path: Path) -> None:
    roots = [Path(tmp_path) / "media-a", Path(tmp_path) / "media-b"]
    for root in roots:
        store = MediaStore(root=root)
        _raw_job(store, status=ImageJobStatus.QUEUED)

    class ImmediateExecutor(FakeExecutor):
        def __init__(self) -> None:
            super().__init__(inputs=[make_media_input()])

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return False

    manager = MediaRuntimeManager(
        roots=roots,
        executor_factory=lambda worker: ImmediateExecutor(),
    )
    count = await manager.run_once()
    assert count == 2
    for root in roots:
        store = MediaStore(root=root)
        assert store.list_jobs()[0].status == ImageJobStatus.SUCCEEDED
