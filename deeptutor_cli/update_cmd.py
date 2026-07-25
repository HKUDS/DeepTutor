"""CLI entry point for installation-aware updates."""

from __future__ import annotations

import typer

from deeptutor.update import InstallMode, UpdateStatus, create_update_coordinator


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

        if not check:
            typer.echo("Automatic update execution is not available yet. Use --check.")
            raise typer.Exit(code=2)

        result = create_update_coordinator().check()
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
        if result.status is UpdateStatus.FAILED:
            typer.echo(result.detail)
            raise typer.Exit(code=1)


__all__ = ("register",)
