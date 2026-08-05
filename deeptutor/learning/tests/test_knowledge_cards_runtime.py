"""Knowledge-card generation runtime tests (KB-02 → ASM-01, §7.9.1).

Covers the process runtime's startup recovery, queued execution, post-start
per-user root discovery against the real :class:`PathService` layout, retry
execution, bounded shutdown, unconfigured-provider failure semantics, and
FastAPI lifespan wiring. All offline: executors are injected in-memory and no
provider endpoint is ever touched.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.learning.knowledge_cards.runtime import (
    KnowledgeCardRuntime,
    discover_learning_roots,
    get_knowledge_card_runtime,
    reset_knowledge_card_runtime,
)
from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
from deeptutor.learning.knowledge_cards.worker import DraftOutput
from deeptutor.learning.models import (
    DraftGenerationStatus,
    GenerationAttemptStatus,
    KnowledgeCardStatus,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.knowledge_card_builders import stable_mastery_progress


class FakeExecutor:
    """In-memory DraftExecutor double; tracks inputs and close."""

    def __init__(self, result=None, error=None):
        self.result = result or DraftOutput(title="Generated title", body="Generated body")
        self.error = error
        self.inputs: list[dict] = []
        self.closed = False

    async def generate(self, input_projection: dict):
        self.inputs.append(input_projection)
        if self.error is not None:
            raise self.error
        return self.result

    async def aclose(self):
        self.closed = True


class ManualClock:
    def __init__(self, start: float = 2000.0) -> None:
        self.now_value = start
        self.slept: list[float] = []

    def now(self) -> float:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now_value += seconds
        await asyncio.sleep(0)


class _BlockingExecutor:
    """A provider double that parks each call until a release event fires.

    Tracks ``calls_started`` / ``in_flight`` / ``max_in_flight`` so a test can
    prove *overlap* between concurrent provider calls — a selected-attempt
    count alone cannot distinguish real concurrency from sequential awaits.
    """

    def __init__(self, release: asyncio.Event, result=None):
        self.release = release
        self.result = result or DraftOutput(title="Generated title", body="Generated body")
        self.calls_started = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def generate(self, input_projection: dict):
        self.calls_started += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await self.release.wait()
        finally:
            self.in_flight -= 1
        return self.result

    async def aclose(self):
        pass


def _queued_root(
    tmp_path,
    *,
    book_id: str = "b1",
    kp_id: str = "kp1",
    user_id: str = "owner",
    subdir: str | None = None,
):
    """A learning root with a queued generation attempt on a stable card."""
    root = Path(tmp_path) / (subdir or "learning")
    progress, _, _ = stable_mastery_progress(book_id, kp_id=kp_id)
    service = KnowledgeCardDraftService(LearningStore(root=root))
    result = service.ensure_draft(
        progress, user_id=user_id, path_id=book_id, knowledge_point_id=kp_id
    )
    return root, result


# ── queued execution ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queued_execution_advances(tmp_path):
    """``run_once`` picks the first queued runnable attempt and advances it."""
    root, result = _queued_root(tmp_path)
    attempt_id = result["attempt"].id
    executor = FakeExecutor()
    runtime = KnowledgeCardRuntime(roots=[root], executor_factory=lambda attempt: executor)

    count = await runtime.run_once()
    assert count == 1

    progress = LearningStore(root=root).load("b1")
    card = progress.knowledge_cards[0]
    assert card.draft_generation_status == DraftGenerationStatus.READY
    assert card.status == KnowledgeCardStatus.DRAFT
    attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
    assert attempt.status == GenerationAttemptStatus.SUCCEEDED
    # The executor received the secret-free frozen input projection exactly once.
    assert len(executor.inputs) == 1
    assert executor.inputs[0]["stable_assessment_id"] == "ra1"
    assert "evaluator_snapshot_id" in executor.inputs[0]


@pytest.mark.asyncio
async def test_unconfigured_provider_fails_attempt_without_calling(tmp_path):
    """A runtime with no executor factory (unconfigured provider) fails the
    attempt with a stable ``no_executor`` state and never invokes a provider."""
    root, result = _queued_root(tmp_path)
    attempt_id = result["attempt"].id
    runtime = KnowledgeCardRuntime(roots=[root])  # executor_factory=None

    count = await runtime.run_once()
    assert count == 1

    progress = LearningStore(root=root).load("b1")
    attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
    assert attempt.status == GenerationAttemptStatus.FAILED
    assert attempt.error_code == "no_executor"


@pytest.mark.asyncio
async def test_configured_concurrency_is_real(tmp_path):
    """The configured concurrency actually limits how many queued attempts
    advance per pass: ``concurrency=1`` advances one root, ``concurrency=2``
    advances both in a single ``run_once``."""
    executor = FakeExecutor()

    # Scenario A: concurrency=1 advances only the first root's attempt.
    root1, _ = _queued_root(tmp_path, book_id="b1", subdir="root1")
    root2, _ = _queued_root(tmp_path, book_id="b2", subdir="root2")
    one = KnowledgeCardRuntime(
        roots=[root1, root2],
        executor_factory=lambda attempt: executor,
        concurrency=1,
    )
    count1 = await one.run_once()
    assert count1 == 1
    p1 = LearningStore(root=root1).load("b1")
    p2 = LearningStore(root=root2).load("b2")
    assert p1.knowledge_cards[0].draft_generation_status == DraftGenerationStatus.READY
    assert p2.knowledge_card_generation_attempts[0].status == GenerationAttemptStatus.QUEUED

    # Scenario B: concurrency=2 advances both roots in one pass.
    root3, _ = _queued_root(tmp_path, book_id="b3", subdir="root3")
    root4, _ = _queued_root(tmp_path, book_id="b4", subdir="root4")
    both = KnowledgeCardRuntime(
        roots=[root3, root4],
        executor_factory=lambda attempt: executor,
        concurrency=2,
    )
    count2 = await both.run_once()
    assert count2 == 2
    p3 = LearningStore(root=root3).load("b3")
    p4 = LearningStore(root=root4).load("b4")
    assert p3.knowledge_cards[0].draft_generation_status == DraftGenerationStatus.READY
    assert p4.knowledge_cards[0].draft_generation_status == DraftGenerationStatus.READY


@pytest.mark.asyncio
async def test_concurrency_2_provider_calls_overlap(tmp_path):
    """With ``concurrency=2`` two queued attempts run their provider calls at
    the *same time* — the configured concurrency produces genuine overlap, not
    N sequential awaits of the same executor (finding 1)."""
    root1, _ = _queued_root(tmp_path, book_id="b1", subdir="root1")
    root2, _ = _queued_root(tmp_path, book_id="b2", subdir="root2")
    release = asyncio.Event()
    executor = _BlockingExecutor(release)
    runtime = KnowledgeCardRuntime(
        roots=[root1, root2],
        executor_factory=lambda attempt: executor,
        concurrency=2,
    )

    task = asyncio.create_task(runtime.run_once())
    # Give both provider calls a chance to enter the blocking generate().
    for _ in range(100):
        if executor.calls_started >= 2:
            break
        await asyncio.sleep(0.01)
    # Both calls are in flight simultaneously — real concurrency.
    assert executor.calls_started == 2
    assert executor.in_flight == 2
    assert executor.max_in_flight == 2

    release.set()
    count = await task
    assert count == 2
    assert executor.max_in_flight == 2


@pytest.mark.asyncio
async def test_concurrency_1_provider_calls_do_not_overlap(tmp_path):
    """With ``concurrency=1`` a second root's provider call does not start
    until the first has fully finished — a selected-attempt count is not a
    substitute for proving serialized execution (finding 1)."""
    root1, _ = _queued_root(tmp_path, book_id="b1", subdir="root1")
    root2, _ = _queued_root(tmp_path, book_id="b2", subdir="root2")
    release = asyncio.Event()
    executor = _BlockingExecutor(release)
    runtime = KnowledgeCardRuntime(
        roots=[root1, root2],
        executor_factory=lambda attempt: executor,
        concurrency=1,
    )

    # Pass 1: the first call enters and blocks; the second never starts.
    task1 = asyncio.create_task(runtime.run_once())
    for _ in range(100):
        if executor.calls_started >= 1:
            break
        await asyncio.sleep(0.01)
    assert executor.calls_started == 1
    assert executor.in_flight == 1
    await asyncio.sleep(0.05)
    # Serialized: still only one call in flight; the other root stays queued.
    assert executor.calls_started == 1
    assert executor.max_in_flight == 1
    release.set()
    assert await task1 == 1

    # Pass 2: the second root's attempt advances; still never overlapping.
    task2 = asyncio.create_task(runtime.run_once())
    for _ in range(100):
        if executor.calls_started >= 2:
            break
        await asyncio.sleep(0.01)
    assert executor.calls_started == 2
    assert await task2 == 1
    # At no point did two provider calls overlap.
    assert executor.max_in_flight == 1


# ── retry execution ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_execution_advances_with_frozen_snapshot(tmp_path):
    """An explicit retry attempt (queued) advances on the next run and reuses
    the frozen evaluator snapshot."""
    root, result = _queued_root(tmp_path)
    card_id = result["card"].id
    first_attempt = result["attempt"].id

    progress = LearningStore(root=root).load("b1")
    attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == first_attempt)
    attempt.status = GenerationAttemptStatus.FAILED
    attempt.error_code = "boom"
    attempt.finished_at = 2000.0
    LearningStore(root=root).save(progress)

    service = KnowledgeCardDraftService(LearningStore(root=root))
    progress = service.load("b1")
    retry = service.retry_generation(
        progress,
        card_id=card_id,
        user_id="owner",
        request_id="retry-1",
        expected_card_revision=1,
        latest_generation_attempt_id=first_attempt,
    )
    retry_attempt_id = retry["attempt"].id
    assert retry["attempt"].frozen_model_snapshot is not None

    executor = FakeExecutor()
    runtime = KnowledgeCardRuntime(roots=[root], executor_factory=lambda attempt: executor)
    count = await runtime.run_once()
    assert count == 1

    progress = LearningStore(root=root).load("b1")
    card = progress.knowledge_cards[0]
    assert card.draft_generation_status == DraftGenerationStatus.READY
    retry_attempt = next(
        a for a in progress.knowledge_card_generation_attempts if a.id == retry_attempt_id
    )
    assert retry_attempt.status == GenerationAttemptStatus.SUCCEEDED
    assert retry_attempt.retry_of_generation_attempt_id == first_attempt


# ── startup recovery ───────────────────────────────────────────────────────


def test_startup_recovery_reconciles_running_without_blob(tmp_path):
    """A running attempt with no confirmable output becomes ``unknown`` on
    startup — it is never auto-resubmitted to the provider."""
    root, result = _queued_root(tmp_path)
    attempt_id = result["attempt"].id
    progress = LearningStore(root=root).load("b1")
    attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
    attempt.status = GenerationAttemptStatus.RUNNING
    attempt.lease_owner = "owner1"
    attempt.started_at = 2000.0
    LearningStore(root=root).save(progress)

    runtime = KnowledgeCardRuntime(roots=[root], now=lambda: 2000.0)
    outcomes = runtime.recover()
    assert any(o["attempt_id"] == attempt_id and o["to"] == "unknown" for o in outcomes)
    progress = LearningStore(root=root).load("b1")
    attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
    assert attempt.status == GenerationAttemptStatus.UNKNOWN
    assert attempt.error_code == "restart_no_confirmable_output"


def test_startup_recovery_leaves_queued_runnable(tmp_path):
    """A queued attempt stays queued/runnable after recovery (no provider call
    merely at startup)."""
    root, result = _queued_root(tmp_path)
    attempt_id = result["attempt"].id
    runtime = KnowledgeCardRuntime(roots=[root])
    outcomes = runtime.recover()
    assert not any(o.get("attempt_id") == attempt_id for o in outcomes)
    progress = LearningStore(root=root).load("b1")
    attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
    assert attempt.status == GenerationAttemptStatus.QUEUED


# ── per-user root discovery (real PathService layout) ──────────────────────


@pytest.mark.asyncio
async def test_discover_learning_roots_matches_path_service_layout(tmp_path, monkeypatch):
    """Per-user roots are discovered under the actual PathService layout
    (``data/users/<uid>/user/workspace/learning``), not a guessed sibling."""
    from deeptutor.learning.knowledge_cards import runtime as runtime_mod
    from deeptutor.multi_user import paths as multi_user_paths

    data_root = Path(tmp_path) / "data"
    default_learning = data_root / "user" / "workspace" / "learning"
    default_learning.mkdir(parents=True, exist_ok=True)
    users_root = data_root / "users"

    monkeypatch.setattr(runtime_mod, "default_learning_root", lambda: default_learning)
    monkeypatch.setattr(multi_user_paths, "USERS_ROOT", users_root)

    # Build the per-user root through the real PathService (scoped construction).
    from deeptutor.services.path_service import PathService

    user_workspace = PathService(workspace_root=users_root / "u9").get_workspace_dir()
    user_learning = user_workspace / "learning"
    user_learning.mkdir(parents=True, exist_ok=True)

    roots = discover_learning_roots()
    assert default_learning in roots
    assert user_learning in roots
    # The guessed sibling path is NOT a learning root.
    assert (users_root / "u9" / "workspace" / "learning") not in roots


@pytest.mark.asyncio
async def test_post_start_root_discovery_advances_new_user_attempt(tmp_path, monkeypatch):
    """A per-user learning root created after startup is discovered at the next
    run boundary and its queued attempt advances."""
    from deeptutor.learning.knowledge_cards import runtime as runtime_mod

    default_root = Path(tmp_path) / "default" / "user" / "workspace" / "learning"
    users_root = Path(tmp_path) / "users"

    def fake_discover():
        roots = [default_root]
        if users_root.is_dir():
            for user_dir in sorted(users_root.iterdir()):
                candidate = user_dir / "user" / "workspace" / "learning"
                if candidate.is_dir():
                    roots.append(candidate)
        return roots

    monkeypatch.setattr(runtime_mod, "discover_learning_roots", fake_discover)

    executor = FakeExecutor()
    runtime = KnowledgeCardRuntime(executor_factory=lambda attempt: executor)
    assert runtime.roots == [default_root]

    # The user's learning root is created AFTER the runtime initialized.
    new_root = users_root / "u2" / "user" / "workspace" / "learning"
    progress, _, _ = stable_mastery_progress("u2b", kp_id="kp1")
    KnowledgeCardDraftService(LearningStore(root=new_root)).ensure_draft(
        progress, user_id="u2", path_id="u2b", knowledge_point_id="kp1"
    )

    count = await runtime.run_once()
    assert count == 1
    reloaded = LearningStore(root=new_root).load("u2b")
    assert reloaded.knowledge_cards[0].draft_generation_status == DraftGenerationStatus.READY


@pytest.mark.asyncio
async def test_explicit_roots_manager_never_scans_global_roots(tmp_path, monkeypatch):
    """A manager built with explicit roots never scans the global layout, so
    offline tests are deterministic and unrelated paths are never touched."""
    from deeptutor.learning.knowledge_cards import runtime as runtime_mod

    explicit_root = Path(tmp_path) / "explicit"

    def _explode():
        raise AssertionError("explicit-roots manager must never call discovery")

    monkeypatch.setattr(runtime_mod, "discover_learning_roots", _explode)
    runtime = KnowledgeCardRuntime(roots=[explicit_root])
    assert runtime.roots == [explicit_root]
    # Even a refresh pass must not touch discovery for explicit-roots managers.
    runtime._refresh_roots()
    assert runtime.roots == [explicit_root]


# ── bounded shutdown / lifecycle ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_bounded_shutdown_closes_executors(tmp_path):
    """``stop`` terminates the background loop within a bounded time and closes
    every lazily-built executor."""
    root, _result = _queued_root(tmp_path)
    executor = FakeExecutor()
    clock = ManualClock()
    runtime = KnowledgeCardRuntime(
        roots=[root],
        executor_factory=lambda attempt: executor,
        sleep=clock.sleep,
        now=clock.now,
    )
    # Run once to build the lazily-resolved executor (proves it is tracked).
    count = await runtime.run_once()
    assert count == 1
    assert list(runtime._executors.values()) == [executor]

    task = runtime.start(interval=0.01)
    assert not task.done()
    await runtime.stop()
    assert task.done()
    assert executor.closed is True


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path):
    runtime = KnowledgeCardRuntime(roots=[Path(tmp_path) / "learning"])
    task1 = runtime.start()
    task2 = runtime.start()
    assert task1 is task2
    await runtime.stop()
    # After stop, a fresh start creates a new task.
    task3 = runtime.start()
    assert task3 is not task1
    await runtime.stop()


@pytest.mark.asyncio
async def test_packaged_registration_smoke_lifecycle(tmp_path):
    """The package ``__init__`` exposes the runtime and it drives a real
    start/stop lifecycle — reachability and lifecycle, not construction only
    (requirement 7)."""
    from deeptutor.learning.knowledge_cards import KnowledgeCardRuntime as PackagedRuntime
    from deeptutor.learning.knowledge_cards.runtime import KnowledgeCardRuntime

    assert PackagedRuntime is KnowledgeCardRuntime

    runtime = PackagedRuntime(
        roots=[Path(tmp_path) / "learning"],
        sleep=ManualClock().sleep,
    )
    task = runtime.start(interval=0.01)
    assert not task.done()
    await runtime.stop()
    assert task.done()
    assert runtime._task is None


@pytest.mark.asyncio
async def test_process_singleton_binds_real_executor_factory(tmp_path, monkeypatch):
    """``get_knowledge_card_runtime`` (the FastAPI lifespan singleton) uses the
    production executor factory — an actionable queued attempt receives a real
    :class:`FrozenModelDraftExecutor` instead of terminating as ``no_executor``.
    This proves packaged runtime reachability and lifecycle, not construction
    only (§7.9.1, requirement 7)."""
    from deeptutor.learning.knowledge_cards import runtime as runtime_mod

    root, result = _queued_root(tmp_path)
    attempt_id = result["attempt"].id
    reset_knowledge_card_runtime()
    monkeypatch.setattr(runtime_mod, "discover_learning_roots", lambda: [root])

    # The real FrozenModelDraftExecutor would need a provider; replace the
    # *factory result* with our in-memory executor but keep the exact default
    # construction path (lazy per-attempt resolution through the singleton).
    fake = FakeExecutor()
    monkeypatch.setattr(
        runtime_mod,
        "_default_executor_factory",
        lambda attempt: fake,
    )
    try:
        runtime = get_knowledge_card_runtime()
        assert runtime.roots == [root]
        count = await runtime.run_once()
        assert count == 1
        progress = LearningStore(root=root).load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        assert attempt.status == GenerationAttemptStatus.SUCCEEDED
        assert attempt.error_code != "no_executor"
    finally:
        await runtime_mod.get_knowledge_card_runtime().stop()
        reset_knowledge_card_runtime()


# ── FastAPI lifespan wiring ────────────────────────────────────────────────


def test_lifespan_wires_recover_start_and_stop():
    """The app lifespan recovers, starts, and stops the knowledge-card runtime.

    The full lifespan drives the whole app (event bus, cron, media runtime,
    provider init), so this structural test proves the wiring exists at the
    exact call sites; the runtime's own lifecycle tests prove the semantics of
    ``recover``/``start``/``stop`` are correct (§7.9.1)."""
    import inspect

    from deeptutor.api import main as api_main

    source = inspect.getsource(api_main.lifespan)
    # Startup: get the runtime, recover deterministic nonterminal attempts,
    # then start the background scheduler.
    assert "get_knowledge_card_runtime" in source
    assert ".recover()" in source
    assert "kc_runtime.recover()" in source
    assert "kc_runtime.start()" in source
    # Shutdown: bounded stop releases provider executors.
    assert "await get_knowledge_card_runtime().stop()" in source
    # The knowledge-card runtime block is guarded so an unconfigured provider
    # never prevents app startup.
    assert "Failed to start knowledge-card runtime" in source
