"""CLI commands for shared session management."""

from __future__ import annotations

import json

import typer

from deeptutor.app import DeepTutorApp

from .chat import ChatState, _chat_repl
from .common import console, maybe_run, print_session_table


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_sessions(
        limit: int = typer.Option(20, "--limit", help="Maximum sessions to show."),
    ) -> None:
        """List existing sessions."""
        maybe_run(_list_sessions(limit))

    @app.command("show")
    def show_session(
        session_id: str = typer.Argument(..., help="Session id."),
        fmt: str = typer.Option("rich", "--format", help="Output format: rich | json."),
    ) -> None:
        """Show a session and its persisted messages."""
        maybe_run(_show_session(session_id, fmt))

    @app.command("open")
    def open_session(
        session_id: str = typer.Argument(..., help="Session id."),
    ) -> None:
        """Enter the interactive chat REPL with an existing session."""
        maybe_run(_chat_repl(ChatState(session_id=session_id)))

    @app.command("delete")
    def delete_session(
        session_id: str = typer.Argument(..., help="Session id."),
    ) -> None:
        """Move a session to the recycle bin (soft delete, recoverable)."""
        maybe_run(_delete_session(session_id))

    @app.command("rename")
    def rename_session(
        session_id: str = typer.Argument(..., help="Session id."),
        title: str = typer.Option(..., "--title", help="New session title."),
    ) -> None:
        """Rename a session."""
        maybe_run(_rename_session(session_id, title))


async def _list_sessions(limit: int) -> None:
    client = DeepTutorApp()
    sessions = await client.list_sessions(limit=limit)
    print_session_table(sessions)


async def _show_session(session_id: str, fmt: str) -> None:
    client = DeepTutorApp()
    session = await client.get_session(session_id)
    if session is None:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)

    if fmt == "json":
        console.print(json.dumps(session, ensure_ascii=False, indent=2, default=str))
        return

    console.print(f"[bold]{session.get('title', '')}[/] ({session.get('id', '')})")
    console.print(
        f"[dim]capability={session.get('capability', '') or 'chat'} "
        f"status={session.get('status', '')} "
        f"messages={len(session.get('messages', []))}[/]",
        highlight=False,
    )
    for message in session.get("messages", []):
        role = str(message.get("role", "")).upper()
        content = str(message.get("content", "") or "").strip()
        console.print(f"\n[cyan]{role}[/]")
        if content:
            console.print(content)


async def _delete_session(session_id: str) -> None:
    client = DeepTutorApp()
    success = await client.delete_session(session_id)
    if not success:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)
    console.print(f"Deleted session {session_id}")


async def _rename_session(session_id: str, title: str) -> None:
    client = DeepTutorApp()
    success = await client.rename_session(session_id, title)
    if not success:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)
    console.print(f"Renamed {session_id} -> {title}")
