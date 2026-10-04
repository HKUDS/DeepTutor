"""CronService: scheduling math, persistence, scheduler loop, owner scoping."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from types import SimpleNamespace

import pytest

from deeptutor.services.cron import repository as cron_repository
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


def test_cron_repository_does_not_bind_fcntl_at_import() -> None:
    assert "fcntl" not in cron_repository.__dict__


def test_cron_repository_uses_msvcrt_locking_on_windows(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, int]] = []
    fake_msvcrt = SimpleNamespace(
        LK_LOCK=1,
        LK_UNLCK=2,
        locking=lambda _fileno, mode, length: calls.append((mode, length)),
    )
    monkeypatch.setattr(cron_repository, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    repository = cron_repository.SQLiteCronRepository(tmp_path / "jobs.sqlite3")

    assert repository.revision() == 0
    assert calls == [
        (fake_msvcrt.LK_LOCK, 1),
        (fake_msvcrt.LK_UNLCK, 1),
        (fake_msvcrt.LK_LOCK, 1),
        (fake_msvcrt.LK_UNLCK, 1),
    ]
    assert repository._migration_lock_path.read_bytes() == b"\0"


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

    def test_two_service_instances_observe_each_others_changes(self, tmp_path):
        store = tmp_path / "jobs.sqlite3"
        first = CronService(store_path=store)
        second = CronService(store_path=store)
        one = first.add_job(
            name="one",
            message="first",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=_chat_owner(),
        )
        two = second.add_job(
            name="two",
            message="second",
            schedule=CronSchedule(kind="every", every_seconds=60),
            owner=_chat_owner(),
        )

        assert {job.id for job in first.list_jobs()} == {one.id, two.id}
        assert first.cancel_job(two.id) is True
        assert [job.id for job in second.list_jobs()] == [one.id]
        assert store.read_bytes().startswith(b"SQLite format 3\x00")

    def test_legacy_json_is_migrated_once_and_archived(self, tmp_path):
        legacy = tmp_path / "jobs.json"
        database = tmp_path / "jobs.sqlite3"
        future = _now_ms() + 60_000
        legacy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "jobs": [
                        {
                            "id": "legacy-job",
                            "name": "legacy",
                            "message": "remember",
                            "schedule": {"kind": "at", "at_ms": future},
                            "owner": {
                                "kind": "chat",
                                "user_id": "local-admin",
                                "session_id": "s1",
                            },
                            "enabled": True,
                            "delete_after_run": True,
                            "created_at_ms": _now_ms(),
                            "state": {"next_run_at_ms": future, "run_history": []},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        service = CronService(store_path=database, legacy_store_path=legacy)
        assert [job.id for job in service.list_jobs()] == ["legacy-job"]
        assert not legacy.exists()
        assert len(list(tmp_path.glob("jobs.legacy-*.json"))) == 1
        assert [job.id for job in CronService(store_path=database).list_jobs()] == ["legacy-job"]


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


class TestSchedulerSettings:
    """The #451 toggles: disable the scheduler, configure the idle re-check."""

    @staticmethod
    def _provider(enabled: bool = True, interval: int = 60):
        state = {"enabled": enabled, "interval": interval}
        return lambda: {
            "cron_scheduler_enabled": state["enabled"],
            "cron_scheduler_check_interval_s": state["interval"],
        }, state

    @pytest.mark.asyncio
    async def test_disabled_at_start_registers_no_timer_and_fires_nothing(self, tmp_path):
        provider, _ = self._provider(enabled=False)
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(
            store_path=tmp_path / "jobs.json", on_job=on_job, settings_provider=provider
        )
        # A job that is already due must stay dormant: no timer, no run.
        job = service.add_job(
            name="due-now",
            message="x",
            schedule=CronSchedule(kind="at", at_ms=_now_ms() + 50),
            owner=_chat_owner(),
        )
        job.state.next_run_at_ms = _now_ms() - 10

        await service.start()
        await asyncio.sleep(0.2)

        assert service._timer_task is None  # the scheduler timer never registered
        assert service._running is False
        assert fired == []
        await service.stop()

    @pytest.mark.asyncio
    async def test_disable_midrun_parks_the_loop(self, tmp_path):
        provider, state = self._provider(enabled=True)
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(
            store_path=tmp_path / "jobs.json", on_job=on_job, settings_provider=provider
        )
        await service.start()
        assert service._timer_task is not None
        # Let the loop run one enabled iteration (it ticks, then idles).
        await asyncio.sleep(0.1)

        state["enabled"] = False
        # A job that is already due, plus the disable, both land together.
        job = service.add_job(
            name="due-while-disabled",
            message="x",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=_chat_owner(),
        )
        job.state.next_run_at_ms = _now_ms() - 10
        service.reload()
        await asyncio.sleep(0.3)

        assert fired == []  # parked: no periodic wake, no due-job run
        await service.stop()

    @pytest.mark.asyncio
    async def test_interval_change_applies_immediately(self, tmp_path):
        provider, state = self._provider(enabled=True, interval=60)
        service = CronService(store_path=tmp_path / "jobs.json", settings_provider=provider)
        await service.start()
        assert service._max_sleep_seconds == 60.0
        assert service._seconds_until_next_due() == 60.0  # no jobs → idle bound

        state["interval"] = 5
        service.reload()  # the settings PUT pokes the leader through here
        for _ in range(40):
            if service._max_sleep_seconds == 5.0:
                break
            await asyncio.sleep(0.05)
        assert service._max_sleep_seconds == 5.0
        assert service._seconds_until_next_due() == 5.0
        await service.stop()

    @pytest.mark.asyncio
    async def test_reenable_after_disabled_start_launches_loop_again(self, tmp_path):
        provider, state = self._provider(enabled=False)
        fired: list[str] = []

        async def on_job(job):
            fired.append(job.id)
            return "ok", None

        service = CronService(
            store_path=tmp_path / "jobs.json", on_job=on_job, settings_provider=provider
        )
        await service.start()
        assert service._timer_task is None

        state["enabled"] = True
        job = service.add_job(
            name="after-reenable",
            message="x",
            schedule=CronSchedule(kind="at", at_ms=_now_ms() + 50),
            owner=_chat_owner(),
        )
        service.reload()  # the leader relaunches the loop for due work
        assert service._timer_task is not None
        for _ in range(40):
            if fired:
                break
            await asyncio.sleep(0.05)
        await service.stop()
        assert fired == [job.id]

    @pytest.mark.asyncio
    async def test_provider_failure_falls_back_to_defaults(self, tmp_path):
        def broken_provider():
            raise RuntimeError("settings store exploded")

        service = CronService(store_path=tmp_path / "jobs.json", settings_provider=broken_provider)
        settings = service._scheduler_settings()
        assert settings == {"enabled": True, "check_interval_s": 60.0}
