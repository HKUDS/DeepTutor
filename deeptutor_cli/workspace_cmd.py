"""CLI commands for the active content workspace."""

from __future__ import annotations

from pathlib import Path

import typer


def register(app: typer.Typer) -> None:
    @app.command("show")
    def show() -> None:
        """Show the active content workspace."""
        from deeptutor.services.workspace import get_content_workspace_service

        payload = get_content_workspace_service().describe_current()
        typer.echo(f"Path: {payload['path']}")
        typer.echo(f"Status: {payload['status']}")
        typer.echo(f"Output security: {payload['security_level']}")

    @app.command("set")
    def set_workspace(folder: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
        """Use FOLDER as the active content workspace."""
        from deeptutor.services.workspace import WorkspaceError, get_content_workspace_service

        try:
            binding = get_content_workspace_service().set_workspace(folder)
        except WorkspaceError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(f"Workspace set to {binding.root}")

    @app.command("reset")
    def reset() -> None:
        """Return to DeepTutor's default content workspace."""
        from deeptutor.services.workspace import WorkspaceError, get_content_workspace_service

        try:
            binding = get_content_workspace_service().set_workspace(None)
        except WorkspaceError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(f"Workspace reset to {binding.root}")


__all__ = ["register"]
