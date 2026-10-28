"""Manage the modules in the current DeepTutor environment."""

import json
from pathlib import Path

import typer

from deeptutor.modules.catalog import module_statuses
from deeptutor.modules.lifecycle import change, plan


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_modules():
        """Show installed, enabled and ready states separately."""
        typer.echo(json.dumps(module_statuses(), ensure_ascii=False, indent=2))

    def command(action: str):
        def run(
            name: str,
            dry_run: bool = typer.Option(False, "--dry-run"),
            wheelhouse: Path | None = typer.Option(None, "--wheelhouse"),
        ):
            try:
                result = (
                    plan(action, name) if dry_run else change(action, name, wheelhouse=wheelhouse)
                )
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(1) from exc
            typer.echo(json.dumps(result, ensure_ascii=False, indent=2))

        return run

    for action in ("install", "uninstall", "enable", "disable"):
        app.command(action)(command(action))
