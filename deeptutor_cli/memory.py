"""
CLI memory commands for the two-file public memory system (SUMMARY/PROFILE).
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from deeptutor.services.memory import get_memory_service

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("show")
    def memory_show(
        file: str = typer.Argument(
            "all", help="要显示的文件：summary、profile 或 all。",
        ),
    ) -> None:
        """Display memory file content."""
        svc = get_memory_service()
        if file == "all":
            snap = svc.read_snapshot()
            for label, content in [
                ("SUMMARY", snap.summary),
                ("PROFILE", snap.profile),
            ]:
                if content:
                    console.print(Panel(Markdown(content), title=f"[bold]{label}.md[/]"))
                else:
                    console.print(f"[dim]{label}.md: （空）[/]")
        elif file in ("summary", "profile"):
            content = svc.read_file(file)
            if content:
                console.print(Panel(Markdown(content), title=f"[bold]{file.upper()}.md[/]"))
            else:
                console.print(f"[dim]{file.upper()}.md: （空）[/]")
        else:
            console.print(f"[red]未知文件：{file}。请使用 summary、profile 或 all。[/]")

    @app.command("clear")
    def memory_clear(
        file: str = typer.Argument(
            "all", help="要清空的文件：summary、profile 或 all。",
        ),
        force: bool = typer.Option(False, "--force", "-f", help="跳过确认。"),
    ) -> None:
        """Clear memory file(s)."""
        svc = get_memory_service()
        if file not in ("summary", "profile", "all"):
            console.print(f"[red]未知文件：{file}[/]")
            raise typer.Exit(1)

        if not force:
            target = "所有记忆文件" if file == "all" else f"{file.upper()}.md"
            if not typer.confirm(f"确认清空 {target} 吗？"):
                raise typer.Abort()

        if file == "all":
            svc.clear_memory()
            console.print("[green]已清空所有记忆文件。[/]")
        else:
            svc.clear_file(file)
            console.print(f"[green]已清空 {file.upper()}.md。[/]")
