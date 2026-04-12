"""
CLI Plugin Command
==================

List and inspect registered plugins (tools, capabilities, playground).
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register(app: typer.Typer) -> None:

    @app.command("list")
    def plugin_list() -> None:
        """List all registered tools and capabilities."""
        from deeptutor.runtime.registry.capability_registry import get_capability_registry
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        tr = get_tool_registry()
        cr = get_capability_registry()

        table = Table(title="已注册插件")
        table.add_column("名称", style="bold")
        table.add_column("类型")
        table.add_column("描述")

        for defn in tr.get_definitions():
            table.add_row(defn.name, "工具", defn.description[:80])

        for m in cr.get_manifests():
            table.add_row(m["name"], "能力", m["description"][:80])

        console.print(table)

    @app.command("info")
    def plugin_info(name: str = typer.Argument(..., help="工具或能力名称。")) -> None:
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
            console.print_json(json.dumps({
                "name": cap.manifest.name,
                "description": cap.manifest.description,
                "stages": cap.manifest.stages,
                "tools_used": cap.manifest.tools_used,
                "config_defaults": cap.manifest.config_defaults,
            }, indent=2))
            return

        console.print(f"[red]未找到 '{name}'。[/]")
        raise typer.Exit(code=1)
