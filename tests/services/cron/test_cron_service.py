"""CronService: scheduling math, persistence, scheduler loop, owner scoping."""

from __future__ import annotations

import asyncio
import time

import pytest

from deeptutor.services.cron.service import (
    CronOwner,
    CronSchedule,
    CronService,
    compute_next_run,
    validate_schedule,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _chat_owner(user_id: str = "local-admin") -> CronOwner:
    return CronOwner(kind="chat", user_id=user_id, session_id="s1")


class TestComputeNextRun:
    def test_at_future_and_expired(self):
        now = _now_ms()
        assert compute_next_run(CronSchedule(kind="at", at_ms=now + 5000), now) == now + 5000
        assert compute_next_run(CronSchedule(kind="at", at_ms=now - 5000), now) is None

    def test_every(self):
        now = _now_ms()
        assert compute_next_run(CronSchedule(kind="every", every_seconds=60), now) == now + 60_000
        assert compute_next_run(CronSchedule(kind="every", every_seconds=0), now) is None

    def test_cron_expression(self):
        pytest.importorskip("croniter")
        now = _now_ms()
        result = compute_next_run(CronSchedule(kind="cron", expr="0 9 * * *"), now)
        assert result is not None and result > now

    def test_bad_cron_expression_raises(self):
        pytest.importorskip("croniter")
        with pytest.raises(ValueError):
            compute_next_run(CronSchedule(kind="cron", expr="not a cron"), _now_ms())


class TestValidateSchedule:
    def test_rejects_past_at(self):
        with pytest.raises(ValueError):
            validate_schedule(CronSchedule(kind="at", at_ms=_now_ms() - 1000))

    def test_rejects_tiny_interval(self):
        with pytest.raises(ValueError):
            validate_schedule(CronSchedule(kind="every", every_seconds=5))

    def test_rejects_unknown_tz(self):
        pytest.importorskip("croniter")
        with pytest.raises(ValueError):
            validate_schedule(CronSchedule(kind="cron", expr="0 9 * * *", tz="Mars/Olympus"))


class TestJobManagement:
    def test_add_list_cancel_persist(self, tmp_path):
        store = tmp_path / "jobs.json"
        service = CronService(store_path=store)
        job = service.add_job(
            name="reminder",
            message="say hi",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=_chat_owner(),
        )
        assert store.exists()

        # A fresh instance sees the persisted job.
        service2 = CronService(store_path=store)
        jobs = service2.list_jobs(owner_key="chat:local-admin")
        assert [j.id for j in jobs] == [job.id]
        assert jobs[0].state.next_run_at_ms is not None

        assert service2.cancel_job(job.id, owner_key="chat:local-admin") is True
        assert CronService(store_path=store).list_jobs() == []

    def test_owner_scoping(self, tmp_path):
        service = CronService(store_path=tmp_path / "jobs.json")
        chat_job = service.add_job(
            name="a",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=_chat_owner(),
        )
        partner_job = service.add_job(
            name="b",
            message="y",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=CronOwner(kind="partner", partner_id="ada", channel="telegram", chat_id="1"),
        )
        assert [j.id for j in service.list_jobs(owner_key="partner:ada")] == [partner_job.id]
        # Cancelling with the wrong owner is refused.
        assert service.cancel_job(chat_job.id, owner_key="partner:ada") is False
        assert service.remove_owner_jobs("partner:ada") == 1
        assert [j.id for j in service.list_jobs()] == [chat_job.id]

    def test_one_shot_defaults_to_delete_after_run(self, tmp_path):
        service = CronService(store_path=tmp_path / "jobs.json")
        job = service.add_job(
            name="once",
            message="x",
            schedule=CronSchedule(kind="at", at_ms=_now_ms() + 60_000),
            owner=_chat_owner(),
        )
        assert job.delete_after_run is True

    def test_corrupt_store_is_preserved_not_wiped(self, tmp_path):
        store = tmp_path / "jobs.json"
        store.write_text("{not json", encoding="utf-8")
        service = CronService(store_path=store)
        assert service.list_jobs() == []
        # The corrupt original was moved aside, not overwritten.
        assert any(p.name.startswith("jobs") and "corrupt" in p.name for p in tmp_path.iterdir())


class TestSchedulerLoop:
    @pytest.mark.asyncio
    async def test_due_job_fires_and_one_shot_is_removed(self, tmp_path):
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(store_path=tmp_path / "jobs.json", on_job=on_job)
        job = service.add_job(
            name="soon",
            message="x",
            schedule=CronSchedule(kind="at", at_ms=_now_ms() + 150),
            owner=_chat_owner(),
        )
        await service.start()
        try:
            for _ in range(40):
                if fired:
                    break
                await asyncio.sleep(0.05)
        finally:
            await service.stop()
        assert fired == [job.id]
        assert service.get_job(job.id) is None  # one-shot removed after run

    @pytest.mark.asyncio
    async def test_failed_run_records_error(self, tmp_path):
        async def on_job(job):
            raise RuntimeError("boom")

        service = CronService(store_path=tmp_path / "jobs.json", on_job=on_job)
        service.add_job(
            name="failing",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        # Force the job due immediately, then run one tick directly.
        job = service.list_jobs()[0]
        job.state.next_run_at_ms = _now_ms() - 10
        await service._tick()
        refreshed = service.get_job(job.id)
        assert refreshed is not None  # repeating job survives a failure
        assert refreshed.state.last_status == "error"
        assert "boom" in (refreshed.state.last_error or "")
        assert refreshed.state.next_run_at_ms is not None
