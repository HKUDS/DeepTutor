"""The built-in ``cron`` tool: schema contract, owner injection, actions."""

from __future__ import annotations

import time

import pytest

from deeptutor.services.cron.service import CronService
from deeptutor.tools.cron_tool import run_cron_action


@pytest.fixture
def cron_service(tmp_path, monkeypatch):
    import deeptutor.services.cron.service as service_mod
    import deeptutor.tools.cron_tool as tool_mod

    service = CronService(store_path=tmp_path / "jobs.json")
    monkeypatch.setattr(service_mod, "_service", service)
    monkeypatch.setattr(tool_mod, "get_cron_service", lambda: service)
    return service


CHAT_OWNER = {"kind": "chat", "user_id": "local-admin", "session_id": "s1"}
PARTNER_OWNER = {
    "kind": "partner",
    "partner_id": "ada",
    "channel": "telegram",
    "chat_id": "42",
    "session_key": "telegram:42",
    "channel_meta": {"thread_ts": "111.222"},
}


class TestCronTool:
    def test_requires_injected_owner(self, cron_service):
        outcome = run_cron_action({"action": "schedule", "message": "x", "every_seconds": 60})
        assert outcome.ok is False
        assert "not available" in outcome.text

    def test_schedule_every_and_list_and_cancel(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "summarize my day",
                "name": "daily recap",
                "every_seconds": 3600,
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job_id = outcome.meta["job_id"]

        listed = run_cron_action({"action": "list", "_cron_owner": CHAT_OWNER})
        assert job_id in listed.text and "daily recap" in listed.text

        # Another owner can't see or cancel it.
        other = run_cron_action({"action": "list", "_cron_owner": PARTNER_OWNER})
        assert "No scheduled tasks" in other.text
        steal = run_cron_action(
            {"action": "cancel", "job_id": job_id, "_cron_owner": PARTNER_OWNER}
        )
        assert steal.ok is False

        cancelled = run_cron_action(
            {"action": "cancel", "job_id": job_id, "_cron_owner": CHAT_OWNER}
        )
        assert cancelled.ok, cancelled.text

    def test_nanobot_action_aliases(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "add",
                "message": "summarize my day",
                "every_seconds": 3600,
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job_id = outcome.meta["job_id"]

        cancelled = run_cron_action(
            {"action": "remove", "job_id": job_id, "_cron_owner": CHAT_OWNER}
        )
        assert cancelled.ok, cancelled.text

    def test_schedule_at_parses_iso(self, cron_service):
        from datetime import datetime, timedelta

        at = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
        outcome = run_cron_action(
            {"action": "schedule", "message": "remind me", "at": at, "_cron_owner": CHAT_OWNER}
        )
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job is not None and job.schedule.kind == "at"
        assert job.delete_after_run is True

    def test_schedule_requires_exactly_one_kind(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "every_seconds": 60,
                "cron_expr": "0 9 * * *",
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok is False
        assert "exactly one" in outcome.text

    def test_schedule_rejected_inside_cron_context(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "every_seconds": 60,
                "_cron_owner": CHAT_OWNER,
                "_cron_in_context": True,
            }
        )
        assert outcome.ok is False
        assert "inside a running scheduled task" in outcome.text

    def test_schedule_rejects_past_at(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "x",
                "at": "2020-01-01T00:00:00",
                "_cron_owner": CHAT_OWNER,
            }
        )
        assert outcome.ok is False
        assert "past" in outcome.text

    def test_partner_owner_round_trip(self, cron_service):
        outcome = run_cron_action(
            {
                "action": "schedule",
                "message": "morning briefing",
                "cron_expr": "0 8 * * *",
                "tz": "Asia/Hong_Kong",
                "_cron_owner": PARTNER_OWNER,
            }
        )
        assert outcome.ok, outcome.text
        job = cron_service.get_job(outcome.meta["job_id"])
        assert job.owner.key == "partner:ada"
        assert job.owner.session_key == "telegram:42"
        assert job.owner.channel_meta == {"thread_ts": "111.222"}
        assert job.schedule.tz == "Asia/Hong_Kong"


class TestRegistryIntegration:
    def test_cron_tool_is_builtin_and_automounted(self):
        from deeptutor.agents._shared.tool_composition import AUTO_MOUNTED_TOOLS
        from deeptutor.tools.builtin import BUILTIN_TOOL_NAMES

        assert "cron" in BUILTIN_TOOL_NAMES
        assert "cron" in AUTO_MOUNTED_TOOLS

    def test_schema_has_action_enum(self):
        from deeptutor.tools.builtin import CronTool

        schema = CronTool().get_definition().to_openai_schema()
        action = schema["function"]["parameters"]["properties"]["action"]
        assert set(action["enum"]) == {"schedule", "list", "cancel"}


class TestExecutorRouting:
    @pytest.mark.asyncio
    async def test_partner_job_runs_and_publishes_outbound(self, monkeypatch):
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule

        processed = []
        published = []

        class FakeBus:
            async def publish_outbound(self, msg):
                published.append(msg)

        class FakeRunner:
            bus = FakeBus()

            async def process_message(self, msg, *, delivery_meta=None):
                processed.append(msg)
                if delivery_meta is not None:
                    delivery_meta["delivered_via"] = "test"
                return "Reminder: stretch"

        class FakeInstance:
            running = True
            runner = FakeRunner()

        class FakeMgr:
            def get_partner(self, partner_id):
                return FakeInstance() if partner_id == "ada" else None

        import deeptutor.services.partners as partners_mod

        monkeypatch.setattr(partners_mod, "get_partner_manager", lambda: FakeMgr())
        monkeypatch.setattr(executor, "_maybe_send_desktop_notification", _noop_notify)

        job = CronJob(
            id="j1",
            name="briefing",
            message="what's new today?",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=CronOwner(
                kind="partner",
                partner_id="ada",
                channel="telegram",
                chat_id="42",
                session_key="telegram:42",
                channel_meta={"thread_ts": "111.222"},
            ),
        )
        status, error = await executor.execute_job(job)
        assert (status, error) == ("ok", None)
        assert len(processed) == 1
        inbound = processed[0]
        assert inbound.channel == "telegram" and inbound.chat_id == "42"
        assert inbound.session_key == "telegram:42"
        assert "what's new today?" in inbound.content
        assert inbound.metadata["_cron_job_id"] == "j1"
        assert inbound.metadata["thread_ts"] == "111.222"

        assert len(published) == 1
        outbound = published[0]
        assert outbound.channel == "telegram" and outbound.chat_id == "42"
        assert outbound.content == "Reminder: stretch"
        assert outbound.metadata["_cron_job_id"] == "j1"
        assert outbound.metadata["thread_ts"] == "111.222"
        assert outbound.metadata["delivered_via"] == "test"

    @pytest.mark.asyncio
    async def test_partner_job_skipped_when_not_running(self, monkeypatch):
        from deeptutor.services.cron import executor
        from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule

        class FakeMgr:
            def get_partner(self, partner_id):
                return None

        import deeptutor.services.partners as partners_mod

        monkeypatch.setattr(partners_mod, "get_partner_manager", lambda: FakeMgr())
        monkeypatch.setattr(executor, "_maybe_send_desktop_notification", _noop_notify)

        job = CronJob(
            id="j2",
            name="x",
            message="y",
            schedule=CronSchedule(kind="every", every_seconds=3600),
            owner=CronOwner(kind="partner", partner_id="ghost"),
        )
        status, error = await executor.execute_job(job)
        assert status == "skipped"
        assert "not running" in (error or "")


async def _noop_notify(*_args, **_kwargs):
    return None
