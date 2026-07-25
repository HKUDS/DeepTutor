"""CLI entry point for installation-aware updates."""

from __future__ import annotations

import os

import typer

from deeptutor.update import InstallMode, UpdateCheck, UpdateStatus, create_update_coordinator
from deeptutor.update.jobs import UpdateInProgressError, create_update_scheduler


def _print_check(result: UpdateCheck) -> None:
    status_label = {
        UpdateStatus.AVAILABLE: "update available",
        UpdateStatus.UP_TO_DATE: "up to date",
        UpdateStatus.FAILED: "check failed",
    }[result.status]
    typer.echo(f"Installation: {result.install_mode.value}")
    typer.echo(f"Current version: {result.current_version}")
    typer.echo(f"Latest stable: {result.latest_version or 'unknown'}")
    typer.echo(f"Status: {status_label}")
    typer.echo(f"Automatic update: {'yes' if result.can_auto_update else 'no'}")
    if result.release_url:
        typer.echo(f"Release notes: {result.release_url}")
    if result.install_mode is InstallMode.DOCKER:
        typer.echo("Update the container image and recreate the service on the host.")


def register(app: typer.Typer) -> None:
    """Register the top-level ``update`` command."""

    @app.command("update")
    def update(
        check: bool = typer.Option(
            False,
            "--check",
            help="Check the latest stable release without changing this installation.",
        ),
    ) -> None:
        """Check for or install a stable DeepTutor update."""

        result = create_update_coordinator().check()
        _print_check(result)
        if result.status is UpdateStatus.FAILED:
            typer.echo(result.detail)
            raise typer.Exit(code=1)
        if check or result.status is UpdateStatus.UP_TO_DATE:
            return
        if result.install_mode is not InstallMode.PYPI:
            typer.echo(f"Automatic updates are not available for {result.install_mode.value} yet.")
            raise typer.Exit(code=2)
        if not result.latest_version:
            typer.echo("The stable target version is unavailable.")
            raise typer.Exit(code=1)
        if not typer.confirm(
            f"Update deeptutor from {result.current_version} to {result.latest_version}?",
            default=False,
        ):
            typer.echo("Update cancelled.")
            return
        try:
            job = create_update_scheduler().schedule_pypi(
                current_version=result.current_version,
                target_version=result.latest_version,
                parent_pid=os.getpid(),
            )
        except UpdateInProgressError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
        except OSError as exc:
            typer.echo(f"Unable to start update worker: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(f"Update scheduled: {job.id}")
        typer.echo("DeepTutor will not restart automatically after this CLI update.")


__all__ = ("register",)
