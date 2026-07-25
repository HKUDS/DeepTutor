from __future__ import annotations

import httpx
from typer.testing import CliRunner

from deeptutor.__version__ import __version__
from deeptutor.update import InstallMode, UpdateCheck, UpdateStatus
from deeptutor.update.jobs import UpdateInProgressError
from deeptutor_cli import update_cmd
from deeptutor_cli.main import app


def _available_pypi_update() -> UpdateCheck:
    return UpdateCheck(
        status=UpdateStatus.AVAILABLE,
        current_version="1.5.4",
        latest_version="1.6.0",
        install_mode=InstallMode.PYPI,
        can_auto_update=True,
        release_url="https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
        detail="installed distribution",
    )


def test_update_cancelled_by_user_does_not_create_a_job(monkeypatch) -> None:
    monkeypatch.setattr(
        update_cmd,
        "create_update_coordinator",
        lambda: type("Coordinator", (), {"check": lambda self: _available_pypi_update()})(),
    )

    class UnexpectedScheduler:
        def schedule_pypi(self, **kwargs):
            raise AssertionError("cancelled update must not create a job")

    monkeypatch.setattr(
        update_cmd,
        "create_update_scheduler",
        lambda: UnexpectedScheduler(),
        raising=False,
    )

    result = CliRunner().invoke(app, ["update"], input="n\n")

    assert result.exit_code == 0
    assert "Update cancelled" in result.output


def test_confirmed_update_schedules_pypi_worker(monkeypatch) -> None:
    monkeypatch.setattr(
        update_cmd,
        "create_update_coordinator",
        lambda: type("Coordinator", (), {"check": lambda self: _available_pypi_update()})(),
    )
    scheduled: dict[str, object] = {}

    class Scheduler:
        def schedule_pypi(self, **kwargs):
            scheduled.update(kwargs)
            return type("Job", (), {"id": "job-123"})()

    monkeypatch.setattr(
        update_cmd,
        "create_update_scheduler",
        lambda: Scheduler(),
        raising=False,
    )

    result = CliRunner().invoke(app, ["update"], input="y\n")

    assert result.exit_code == 0, result.output
    assert scheduled["current_version"] == "1.5.4"
    assert scheduled["target_version"] == "1.6.0"
    assert isinstance(scheduled["parent_pid"], int)
    assert "job-123" in result.output
    assert "will not restart" in result.output


def test_confirmed_update_reports_an_existing_active_job(monkeypatch) -> None:
    monkeypatch.setattr(
        update_cmd,
        "create_update_coordinator",
        lambda: type("Coordinator", (), {"check": lambda self: _available_pypi_update()})(),
    )

    class BusyScheduler:
        def schedule_pypi(self, **kwargs):
            raise UpdateInProgressError("Another update job is already active")

    monkeypatch.setattr(update_cmd, "create_update_scheduler", lambda: BusyScheduler())

    result = CliRunner().invoke(app, ["update"], input="y\n")

    assert result.exit_code == 1
    assert "Another update job is already active" in result.output


def test_update_check_reports_the_latest_stable_release(monkeypatch) -> None:
    def fake_get(self, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "tag_name": "v1.6.0",
                "html_url": ("https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0"),
                "draft": False,
                "prerelease": False,
            },
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = CliRunner().invoke(app, ["update", "--check"])

    assert result.exit_code == 0, result.output
    assert "Installation: source_web" in result.output
    assert f"Current version: {__version__}" in result.output
    assert "Latest stable: 1.6.0" in result.output
    assert "Status: update available" in result.output
    assert "Automatic update: yes" in result.output
