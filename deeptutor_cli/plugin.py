"""
CLI Plugin Command
==================

List and inspect registered tools, capabilities, and plugin packages.
"""

from __future__ import annotations

from dataclasses import asdict
import json

from rich.console import Console
from rich.table import Table
import typer

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("list")
    def plugin_list() -> None:
        """List registered tools, capabilities, and plugin packages."""
        from deeptutor.plugins.registry import get_plugin_registry
        from deeptutor.runtime.registry.capability_registry import get_capability_registry
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        table = Table(title="Registered Plugins")
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Description")

        for definition in get_tool_registry().get_definitions():
            table.add_row(definition.name, "tool", "enabled", definition.description[:80])

        for manifest in get_capability_registry().get_manifests():
            table.add_row(
                manifest["name"],
                "capability",
                "enabled",
                manifest["description"][:80],
            )

        for record in get_plugin_registry().list_plugins():
            table.add_row(record.id, "plugin package", record.status, record.description[:80])

        console.print(table)

    @app.command("info")
    def plugin_info(name: str = typer.Argument(..., help="Tool, capability, or plugin ID.")) -> None:
        """Show details of a tool, capability, or plugin package."""
        from deeptutor.plugins.registry import get_plugin_registry
        from deeptutor.runtime.registry.capability_registry import get_capability_registry
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        tool = get_tool_registry().get(name)
        if tool:
            definition = tool.get_definition()
            console.print_json(json.dumps(definition.to_openai_schema(), indent=2))
            return

        capability = get_capability_registry().get(name)
        if capability:
            from deeptutor.app import DeepTutorApp

            availability = DeepTutorApp().get_capability_availability(name)
            console.print_json(
                json.dumps(
                    {
                        "name": capability.manifest.name,
                        "description": capability.manifest.description,
                        "cli_aliases": capability.manifest.cli_aliases,
                        "stages": capability.manifest.stages,
                        "tools_used": capability.manifest.tools_used,
                        "config_defaults": capability.manifest.config_defaults,
                        "availability": asdict(availability),
                    },
                    indent=2,
                )
            )
            return

        record = get_plugin_registry().get_plugin(name)
        if record is not None:
            console.print_json(json.dumps(record.to_dict(), indent=2))
            return

        console.print(f"[red]'{name}' not found.[/]")
        raise typer.Exit(code=1)

    @app.command("state")
    def plugin_state() -> None:
        """Show installed, catalog, approval, and compatibility state."""
        from deeptutor.plugins.registry import get_plugin_registry

        table = Table(title="Plugin Packages")
        table.add_column("ID", style="bold")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("Description")

        records = get_plugin_registry().list_plugins()
        if not records:
            table.add_row("-", "-", "empty", "No plugin packages are installed or cataloged")
        for record in records:
            table.add_row(record.id, record.version, record.status, record.description[:100])
        console.print(table)

    @app.command("search")
    def plugin_search(
        query: str = typer.Argument("", help="Search official catalog metadata."),
    ) -> None:
        """Search the vendored official plugin catalog."""
        from deeptutor.plugins.catalog import search_catalog

        table = Table(title="Official Plugin Catalog")
        table.add_column("ID", style="bold")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("Description")

        entries = search_catalog(query)
        if not entries:
            table.add_row("-", "-", "empty", "No matching catalog entries")
        for entry in entries:
            table.add_row(
                entry.id,
                entry.version,
                entry.status,
                entry.description_i18n.get("en", "")[:100],
            )
        console.print(table)

    @app.command("show")
    def plugin_show(
        plugin_id: str = typer.Argument(..., help="Installed or catalog plugin ID."),
    ) -> None:
        """Show full plugin package metadata."""
        from deeptutor.plugins.catalog import get_catalog_entry
        from deeptutor.plugins.registry import PluginRecord, get_plugin_registry

        record = get_plugin_registry().get_plugin(plugin_id)
        if record is None:
            entry = get_catalog_entry(plugin_id)
            if entry is None:
                console.print(f"[red]Plugin package '{plugin_id}' not found.[/]")
                raise typer.Exit(code=1) from None
            record = PluginRecord(
                id=entry.id,
                status="deprecated" if entry.status == "deprecated" else "available",
                catalog_entry=entry,
            )
        console.print_json(json.dumps(record.to_dict(), indent=2))

    @app.command("enable")
    def plugin_enable(plugin_id: str = typer.Argument(..., help="Installed plugin ID.")) -> None:
        """Record an installed plugin package as enabled."""
        from deeptutor.plugins.registry import PluginStateError, get_plugin_registry

        try:
            record = get_plugin_registry().set_enabled(plugin_id, True)
        except PluginStateError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from None
        console.print(f"[green]{record.id} is {record.status}.[/]")

    @app.command("disable")
    def plugin_disable(plugin_id: str = typer.Argument(..., help="Installed plugin ID.")) -> None:
        """Record an installed plugin package as disabled."""
        from deeptutor.plugins.registry import PluginStateError, get_plugin_registry

        try:
            record = get_plugin_registry().set_enabled(plugin_id, False)
        except PluginStateError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from None
        console.print(f"[green]{record.id} is {record.status}.[/]")
