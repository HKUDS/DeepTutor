"""
CLI commands for managing TutorBot instances.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register(app: typer.Typer) -> None:

    @app.command("list")
    def bot_list() -> None:
        """List all TutorBot instances."""
        from deeptutor.services.tutorbot import get_tutorbot_manager

        bots = get_tutorbot_manager().list_bots()
        if not bots:
            console.print("[dim]未配置 TutorBot。[/]")
            return

        table = Table(title="TutorBot 列表")
        table.add_column("ID", style="cyan")
        table.add_column("名称")
        table.add_column("状态")
        table.add_column("模型", style="dim")
        table.add_column("渠道", style="dim")

        for b in bots:
            status = "[green]运行中[/]" if b.get("running") else "[dim]已停止[/]"
            table.add_row(
                b["bot_id"],
                b.get("name", ""),
                status,
                b.get("model") or "(默认)",
                ", ".join(b.get("channels", [])) or "无",
            )
        console.print(table)

    @app.command("start")
    def bot_start(
        name: str = typer.Argument(..., help="要启动的 Bot ID。"),
    ) -> None:
        """Start a TutorBot instance."""
        from deeptutor.services.tutorbot import get_tutorbot_manager

        mgr = get_tutorbot_manager()
        try:
            instance = asyncio.get_event_loop().run_until_complete(mgr.start_bot(name))
            console.print(f"[green]已启动 TutorBot '{instance.config.name}' ({name})[/]")
        except RuntimeError as e:
            console.print(f"[red]启动失败：{e}[/]")
            raise typer.Exit(1)

    @app.command("stop")
    def bot_stop(
        name: str = typer.Argument(..., help="要停止的 Bot ID。"),
    ) -> None:
        """Stop a running TutorBot instance."""
        from deeptutor.services.tutorbot import get_tutorbot_manager

        mgr = get_tutorbot_manager()
        stopped = asyncio.get_event_loop().run_until_complete(mgr.stop_bot(name))
        if stopped:
            console.print(f"[green]已停止 TutorBot '{name}'[/]")
        else:
            console.print(f"[yellow]未找到 Bot '{name}' 或其未运行。[/]")

    @app.command("create")
    def bot_create(
        name: str = typer.Argument(..., help="Bot ID。"),
        display_name: str = typer.Option("", "--name", "-n", help="显示名称。"),
        persona: str = typer.Option("", "--persona", "-p", help="人设描述。"),
        model: str = typer.Option("", "--model", "-m", help="覆盖模型。"),
    ) -> None:
        """Create a new TutorBot configuration and start it."""
        from deeptutor.services.tutorbot import get_tutorbot_manager
        from deeptutor.services.tutorbot.manager import BotConfig

        config = BotConfig(
            name=display_name or name,
            persona=persona,
            model=model or None,
        )
        mgr = get_tutorbot_manager()
        try:
            instance = asyncio.get_event_loop().run_until_complete(
                mgr.start_bot(name, config)
            )
            console.print(f"[green]已创建并启动 TutorBot '{instance.config.name}' ({name})[/]")
        except RuntimeError as e:
            console.print(f"[red]失败：{e}[/]")
            raise typer.Exit(1)
