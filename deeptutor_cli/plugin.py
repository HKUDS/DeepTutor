"""
CLI Plugin Command
==================

List and inspect registered tools, capabilities, and resource providers.
"""

from __future__ import annotations

from dataclasses import asdict

from rich.console import Console
from rich.table import Table
import typer

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("list")
    def plugin_list() -> None:
        """List all registered tools, capabilities, and resource providers."""
        from deeptutor.runtime.registry.capability_registry import get_capability_registry
        from deeptutor.runtime.registry.tool_registry import get_tool_registry
        from deeptutor.services.resource_providers import get_resource_provider_registry

        tr = get_tool_registry()
        cr = get_capability_registry()

        table = Table(title="Registered Plugins")
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Description")

        for defn in tr.get_definitions():
            table.add_row(defn.name, "tool", defn.description[:80])

        for m in cr.get_manifests():
            table.add_row(m["name"], "capability", m["description"][:80])

        console.print(table)

        provider_rows = get_resource_provider_registry().descriptions()
        if provider_rows:
            provider_table = Table(title="Resource Providers")
            provider_table.add_column("Name", style="bold")
            provider_table.add_column("Type")
            provider_table.add_column("Version")
            provider_table.add_column("Languages")
            provider_table.add_column("Offline")
            provider_table.add_column("State")
            for row in provider_rows:
                provider_table.add_row(
                    str(row["name"]),
                    str(row["type"]),
                    str(row["version"]),
                    ",".join(row["languages"]),
                    "yes" if row["offline"] else "no",
                    "enabled" if row["enabled"] else "disabled",
                )
            console.print(provider_table)

    @app.command("info")
    def plugin_info(name: str = typer.Argument(..., help="Tool or capability name.")) -> None:
        """Show details of a tool or capability."""
        import json

        from deeptutor.runtime.registry.capability_registry import get_capability_registry
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        tr = get_tool_registry()
        cr = get_capability_registry()

        tool = tr.get(name)
        if tool:
            defn = tool.get_definition()
            console.print_json(json.dumps(defn.to_openai_schema(), indent=2))
            return

        cap = cr.get(name)
        if cap:
            from deeptutor.app import DeepTutorApp

            availability = DeepTutorApp().get_capability_availability(name)
            console.print_json(
                json.dumps(
                    {
                        "name": cap.manifest.name,
                        "description": cap.manifest.description,
                        "cli_aliases": cap.manifest.cli_aliases,
                        "stages": cap.manifest.stages,
                        "tools_used": cap.manifest.tools_used,
                        "config_defaults": cap.manifest.config_defaults,
                        "availability": asdict(availability),
                    },
                    indent=2,
                )
            )
            return

        console.print(f"[red]'{name}' not found.[/]")
        raise typer.Exit(code=1)

    @app.command("enable")
    def plugin_enable(name: str = typer.Argument(..., help="Provider name.")) -> None:
        """Enable one registered resource provider."""
        _set_provider_enabled(name, True)

    @app.command("disable")
    def plugin_disable(name: str = typer.Argument(..., help="Provider name.")) -> None:
        """Disable one registered resource provider (state is preserved)."""
        _set_provider_enabled(name, False)


def _set_provider_enabled(name: str, enabled: bool) -> None:
    from deeptutor.services.resource_providers import (
        get_resource_provider_registry,
        set_provider_enabled,
    )

    if get_resource_provider_registry().get(name) is None:
        console.print(f"[red]'{name}' is not a registered resource provider.[/]")
        raise typer.Exit(code=1)
    set_provider_enabled(name, enabled)
    console.print(f"'{name}' {'enabled' if enabled else 'disabled'}.")
