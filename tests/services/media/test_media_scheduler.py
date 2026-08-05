"""MED-02 scheduler + worker lifecycle tests (offline).

Covers the background submit → poll → succeed loop, cancel confirmation,
restart with/without a remote id, explicit retry lineage, deadline enforcement,
and the deterministic rule that automatic terminal states are never replayed.
An injected clock/sleep keeps every timing assertion exact.
"""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

import pytest

from deeptutor.services.media.models import (
    BackgroundSubmit,
    ImageGenerationJob,
    ImageJobStatus,
    MediaInput,
    PollOutcome,
)
from deeptutor.services.media.scheduler import MediaScheduler
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.worker import ImageGenerationJobWorker
from tests.services.media._media_helpers import FakeExecutor, make_media_input, make_png


class BackgroundExecutor(FakeExecutor):
    """Fake that acknowledges a background submit, then completes on poll."""

    def __init__(
        self,
        *,
        remote_response_id: str = "resp_1",
        done_on_poll: int = 1,
        poll_after: float = 2.0,
        fail_poll: Exception | None = None,
    ) -> None:
        super().__init__(inputs=[make_media_input()])
        self.remote_response_id = remote_response_id
        self.done_on_poll = done_on_poll
        self.poll_after = poll_after
        self.fail_poll = fail_poll
        self.poll_calls = 0

    async def run(self, job: ImageGenerationJob) -> list[MediaInput] | BackgroundSubmit:
        self.runs += 1
        return BackgroundSubmit(
            remote_response_id=self.remote_response_id, poll_after=self.poll_after
        )

    async def poll(self, job: ImageGenerationJob) -> PollOutcome:
        self.poll_calls += 1
        if self.fail_poll is not None:
            raise self.fail_poll
        if self.poll_calls >= self.done_on_poll:
            return PollOutcome(media=[make_media_input()])
        return PollOutcome(poll_after=self.poll_after)


class ManualClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now_value = start
        self.slept: list[float] = []

    def now(self) -> float:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now_value += seconds


def _job_args(**overrides: Any) -> dict[str, Any]:
    args = dict(
        user_id="u1",
        prompt="a red fox",
        session_id="sess-1",
        turn_id="turn-1",
        tool_call_id="tool-1",
        provider="openai",
        profile="p1",
        protocol="openai_responses",
        model="gpt-5.6",
    )
    args.update(overrides)
    return args


def _raw_job(
    store: MediaStore,
    *,
    status: ImageJobStatus,
    remote_response_id: str = "",
    deadline_at: float = 0.0,
    poll_after: float = 0.0,
    user_id: str = "u1",
) -> ImageGenerationJob:
    job = ImageGenerationJob(
        id=uuid.uuid4().hex,
        user_id=user_id,
        original_prompt="a red fox",
        request_hash="h",
        status=status,
        remote_response_id=remote_response_id,
        deadline_at=deadline_at,
        poll_after=poll_after,
    )
    return store.save_job(job)


# ── next_actionable selection ───────────────────────────────────────────────


def test_next_actionable_prefers_cancel_then_queued_then_ready_poll(
    media_store: MediaStore,
) -> None:
    ready_poll = _raw_job(
        media_store, status=ImageJobStatus.POLLING, remote_response_id="r1", poll_after=1001.0
    )
    cancel = _raw_job(media_store, status=ImageJobStatus.CANCEL_REQUESTED)
    queued = _raw_job(media_store, status=ImageJobStatus.QUEUED)
    worker = ImageGenerationJobWorker(store=media_store)
    scheduler = MediaScheduler(worker, now=lambda: 1002.0)

    assert scheduler.next_actionable().id == cancel.id

    store = media_store
    store.transition_job(
        cancel.id,
        from_status=ImageJobStatus.CANCEL_REQUESTED,
        to_status=ImageJobStatus.CANCELLED_UNCONFIRMED,
    )
    assert scheduler.next_actionable().id == queued.id

    store.transition_job(
        queued.id, from_status=ImageJobStatus.QUEUED, to_status=ImageJobStatus.SUCCEEDED
    )
    assert scheduler.next_actionable().id == ready_poll.id


def test_polling_job_before_poll_after_is_not_selected(media_store: MediaStore) -> None:
    _raw_job(media_store, status=ImageJobStatus.POLLING, remote_response_id="r1", poll_after=1005.0)
    worker = ImageGenerationJobWorker(store=media_store)
    scheduler = MediaScheduler(worker, now=lambda: 1000.0)
    assert scheduler.next_actionable() is None


def test_terminal_states_are_never_selected(media_store: MediaStore) -> None:
    for status in (
        ImageJobStatus.SUCCEEDED,
        ImageJobStatus.FAILED,
        ImageJobStatus.CANCELLED,
        ImageJobStatus.CANCELLED_UNCONFIRMED,
        ImageJobStatus.TIMED_OUT,
        ImageJobStatus.UNKNOWN,
    ):
        _raw_job(media_store, status=status)
    worker = ImageGenerationJobWorker(store=media_store)
    scheduler = MediaScheduler(worker)
    assert scheduler.next_actionable() is None


# ── run_once advances exactly one job ───────────────────────────────────────


@pytest.mark.asyncio
async def test_run_once_executes_queued_job(media_store: MediaStore) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(FakeExecutor(inputs=[make_media_input()]))
    job = worker.create_job(**_job_args())

    processed = await MediaScheduler(worker).run_once()

    assert processed == job.id
    assert media_store.load_job(job.id).status == ImageJobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_run_once_cancel_requested_resolves_unconfirmed(media_store: MediaStore) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(FakeExecutor(cancel_confirmed=None))
    job = worker.create_job(**_job_args())
    media_store.transition_job(
        job.id, from_status=ImageJobStatus.QUEUED, to_status=ImageJobStatus.CANCEL_REQUESTED
    )

    processed = await MediaScheduler(worker).run_once()

    assert processed == job.id
    assert media_store.load_job(job.id).status == ImageJobStatus.CANCELLED_UNCONFIRMED


@pytest.mark.asyncio
async def test_run_once_idle_returns_none(media_store: MediaStore) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    assert await MediaScheduler(worker).run_once() is None


# ── background loop: submit → poll → succeed ────────────────────────────────


@pytest.mark.asyncio
async def test_background_loop_advances_through_polling_to_succeeded(
    media_store: MediaStore,
) -> None:
    clock = ManualClock()
    executor = BackgroundExecutor(remote_response_id="resp_1", done_on_poll=1)
    worker = ImageGenerationJobWorker(store=media_store, now=clock.now)
    worker.set_executor(executor)
    job = worker.create_job(**_job_args())
    scheduler = MediaScheduler(worker, sleep=clock.sleep, now=clock.now)

    # Submit.
    await scheduler.run_once()
    stored = media_store.load_job(job.id)
    assert stored.status == ImageJobStatus.POLLING
    assert stored.remote_response_id == "resp_1"
    assert stored.poll_after > 1000.0  # absolute time, not a relative delay

    # The polling job is not due until poll_after passes.
    assert scheduler.next_actionable() is None
    clock.now_value = stored.poll_after + 1
    assert scheduler.next_actionable().id == job.id

    # Poll completes.
    await scheduler.run_once()
    final = media_store.load_job(job.id)
    assert final.status == ImageJobStatus.SUCCEEDED
    assert executor.runs == 1
    assert executor.poll_calls == 1


@pytest.mark.asyncio
async def test_background_poll_backs_off_until_complete(media_store: MediaStore) -> None:
    clock = ManualClock()
    executor = BackgroundExecutor(remote_response_id="resp_1", done_on_poll=3)
    worker = ImageGenerationJobWorker(store=media_store, now=clock.now)
    worker.set_executor(executor)
    job = worker.create_job(**_job_args())
    scheduler = MediaScheduler(worker, sleep=clock.sleep, now=clock.now)

    await scheduler.run_once()  # submit
    delays: list[float] = []
    stored = media_store.load_job(job.id)
    assert stored.poll_delay_seconds == 2.0  # first poll due after 2s
    for _ in range(3):
        clock.now_value = stored.poll_after + 1
        await scheduler.run_once()
        stored = media_store.load_job(job.id)
        delays.append(stored.poll_delay_seconds)
        if stored.status == ImageJobStatus.SUCCEEDED:
            break
    assert stored.status == ImageJobStatus.SUCCEEDED
    assert executor.poll_calls == 3
    # Backoff grows 2s -> 4s -> 8s, capped at 15s (§11.4).
    assert delays == [4.0, 8.0, 8.0]


@pytest.mark.asyncio
async def test_poll_deadline_exceeded_becomes_timed_out(media_store: MediaStore) -> None:
    clock = ManualClock()
    executor = BackgroundExecutor(remote_response_id="resp_1", done_on_poll=10)
    worker = ImageGenerationJobWorker(store=media_store, now=clock.now)
    worker.set_executor(executor)
    job = worker.create_job(**_job_args(deadline_at=1050.0))
    scheduler = MediaScheduler(worker, sleep=clock.sleep, now=clock.now)

    await scheduler.run_once()  # submit -> polling
    stored = media_store.load_job(job.id)
    assert stored.status == ImageJobStatus.POLLING

    # Time marches past the deadline before the poll completes.
    clock.now_value = 2000.0
    await scheduler.run_once()

    final = media_store.load_job(job.id)
    assert final.status == ImageJobStatus.TIMED_OUT
    assert executor.poll_calls == 0


@pytest.mark.asyncio
async def test_poll_failure_fails_job(media_store: MediaStore) -> None:
    clock = ManualClock()
    executor = BackgroundExecutor(
        remote_response_id="resp_1", fail_poll=RuntimeError("sk-transient-secret-123456")
    )
    worker = ImageGenerationJobWorker(store=media_store, now=clock.now)
    worker.set_executor(executor)
    job = worker.create_job(**_job_args())
    scheduler = MediaScheduler(worker, sleep=clock.sleep, now=clock.now)

    await scheduler.run_once()  # submit
    stored = media_store.load_job(job.id)
    clock.now_value = stored.poll_after + 1
    await scheduler.run_once()

    final = media_store.load_job(job.id)
    assert final.status == ImageJobStatus.FAILED
    assert "sk-transient-secret" not in final.sanitized_error


# ── restart recovery interplay ──────────────────────────────────────────────


def test_restart_remote_id_polling_job_stays_polling(media_store: MediaStore) -> None:
    _raw_job(media_store, status=ImageJobStatus.POLLING, remote_response_id="resp_1")
    worker = ImageGenerationJobWorker(store=media_store)
    assert worker.recover() == []


def test_restart_no_remote_id_polling_job_becomes_unknown(media_store: MediaStore) -> None:
    job = _raw_job(media_store, status=ImageJobStatus.POLLING)
    worker = ImageGenerationJobWorker(store=media_store)
    transitions = worker.recover()
    assert [row["to"] for row in transitions] == [ImageJobStatus.UNKNOWN.value]
    assert media_store.load_job(job.id).status == ImageJobStatus.UNKNOWN


@pytest.mark.asyncio
async def test_restart_remote_id_job_polls_after_recover(media_store: MediaStore) -> None:
    """A fresh process over the same store resumes a remote-id polling job and
    never re-submits it."""
    executor = BackgroundExecutor(remote_response_id="resp_1", done_on_poll=1)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(executor)
    job = worker.create_job(**_job_args())
    await worker.run_job(job.id)
    assert media_store.load_job(job.id).status == ImageJobStatus.POLLING

    # Fresh worker over the same durable store; a fresh executor that only
    # records polls (any resubmit would be a bug).
    fresh_executor = BackgroundExecutor(remote_response_id="resp_1", done_on_poll=1)
    fresh_worker = ImageGenerationJobWorker(store=media_store)
    fresh_worker.set_executor(fresh_executor)
    assert fresh_worker.recover() == []
    assert fresh_executor.runs == 0

    await fresh_worker.poll_job(job.id)
    assert media_store.load_job(job.id).status == ImageJobStatus.SUCCEEDED
    assert fresh_executor.poll_calls == 1
    assert fresh_executor.runs == 0, "restart must never resubmit"


# ── explicit retry lineage ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_retry_creates_linked_new_job(media_store: MediaStore) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(FakeExecutor(error=RuntimeError("boom")))
    first = worker.create_job(**_job_args(idempotency_key="k1"))
    await worker.run_job(first.id)
    assert media_store.load_job(first.id).status == ImageJobStatus.FAILED

    # User explicitly retries: a brand-new job linked to the old one.
    worker.set_executor(FakeExecutor(inputs=[make_media_input()]))
    retry = worker.create_job(**_job_args(idempotency_key="k2", retry_of_job_id=first.id))
    assert retry.id != first.id
    assert retry.retry_of_job_id == first.id

    await worker.run_job(retry.id)
    assert media_store.load_job(retry.id).status == ImageJobStatus.SUCCEEDED
    # The old job keeps its failed terminal state; nothing is replayed.
    assert media_store.load_job(first.id).status == ImageJobStatus.FAILED


def test_retry_rejects_cross_user_prior(media_store: MediaStore) -> None:
    prior = _raw_job(media_store, status=ImageJobStatus.FAILED, user_id="u2")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(Exception, match="retried job"):
        worker.create_job(**_job_args(user_id="u1", retry_of_job_id=prior.id))


# ── run_forever stops on the stop event ─────────────────────────────────────


@pytest.mark.asyncio
async def test_run_forever_processes_jobs_then_stops(media_store: MediaStore) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(FakeExecutor(inputs=[make_media_input()]))
    job = worker.create_job(**_job_args())
    stop = asyncio.Event()

    async def sleep_until_stop(_seconds: float) -> None:
        if media_store.load_job(job.id).status == ImageJobStatus.SUCCEEDED:
            stop.set()

    scheduler = MediaScheduler(worker, sleep=sleep_until_stop)
    await scheduler.run_forever(interval=0.0, stop=stop)

    assert media_store.load_job(job.id).status == ImageJobStatus.SUCCEEDED
