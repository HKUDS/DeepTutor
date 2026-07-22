"""
CLI commands for managing partner instances.
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.table import Table
import typer

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("list")
    def partner_list() -> None:
        """List all partners."""
        from deeptutor.services.partners import get_partner_manager

        partners = get_partner_manager().list_partners()
        if not partners:
            console.print("[dim]No partners configured.[/]")
            return

        table = Table(title="Partners")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Model", style="dim")
        table.add_column("Channels", style="dim")

        for p in partners:
            status = "[green]running[/]" if p.get("running") else "[dim]stopped[/]"
            selection = p.get("llm_selection") or {}
            model = selection.get("model_id") or p.get("model") or "(default)"
            table.add_row(
                p["partner_id"],
                p.get("name", ""),
                status,
                model,
                ", ".join(p.get("channels", [])) or "-",
            )
        console.print(table)

    @app.command("start")
    def partner_start(
        name: str = typer.Argument(..., help="Partner ID to start."),
    ) -> None:
        """Start a partner."""
        from deeptutor.services.partners import get_partner_manager

        mgr = get_partner_manager()
        try:
            instance = asyncio.run(mgr.start_partner(name))
            console.print(f"[green]Started partner '{instance.config.name}' ({name})[/]")
        except RuntimeError as e:
            console.print(f"[red]Failed to start: {e}[/]")
            raise typer.Exit(1)

    @app.command("stop")
    def partner_stop(
        name: str = typer.Argument(..., help="Partner ID to stop."),
    ) -> None:
        """Stop a running partner."""
        from deeptutor.services.partners import get_partner_manager

        mgr = get_partner_manager()
        stopped = asyncio.run(mgr.stop_partner(name))
        if stopped:
            console.print(f"[green]Stopped partner '{name}'[/]")
        else:
            console.print(f"[yellow]Partner '{name}' not found or not running.[/]")

    @app.command("create")
    def partner_create(
        name: str = typer.Argument(..., help="Partner ID."),
        display_name: str = typer.Option("", "--name", "-n", help="Display name."),
        soul: str = typer.Option("", "--soul", "-s", help="Soul markdown (the persona)."),
        model: str = typer.Option("", "--model", "-m", help="Model override."),
    ) -> None:
        """Create a new partner configuration and start it."""
        from deeptutor.services.partners import get_partner_manager
        from deeptutor.services.partners.manager import PartnerConfig
        from deeptutor.services.partners.workspace import write_soul

        config = PartnerConfig(
            name=display_name or name,
            model=model or None,
        )
        mgr = get_partner_manager()
        try:
            mgr.save_config(name, config, auto_start=True)
            if soul:
                write_soul(name, soul)
            instance = asyncio.run(mgr.start_partner(name, config))
            console.print(
                f"[green]Created and started partner '{instance.config.name}' ({name})[/]"
            )
        except RuntimeError as e:
            console.print(f"[red]Failed: {e}[/]")
            raise typer.Exit(1)
