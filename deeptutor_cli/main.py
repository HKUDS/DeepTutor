"""CLI entry point for the standalone ``deeptutor-cli`` package."""

from __future__ import annotations

import typer

from deeptutor.logging import configure_logging
from deeptutor.runtime.mode import RunMode, set_mode
from deeptutor.services.setup import get_backend_port

from .book import register as register_book
from .bot import register as register_bot
from .chat import register as register_chat
from .common import build_turn_request, console, maybe_run
from .config_cmd import register as register_config
from .kb import register as register_kb
from .memory import register as register_memory
from .notebook import register as register_notebook
from .plugin import register as register_plugin
from .provider_cmd import register as register_provider
from .session_cmd import register as register_session

set_mode(RunMode.CLI)
configure_logging()

app = typer.Typer(
    name="deeptutor",
    help="DeepTutor CLI – agent-first interface for capabilities, tools, and knowledge.",
    no_args_is_help=True,
    add_completion=False,
)

bot_app = typer.Typer(help="Manage TutorBot instances.")
chat_app = typer.Typer(help="Interactive chat REPL.")
kb_app = typer.Typer(help="Manage knowledge bases.")
memory_app = typer.Typer(help="View and manage lightweight memory.")
plugin_app = typer.Typer(help="List plugins.")
config_app = typer.Typer(help="Inspect configuration.")
session_app = typer.Typer(help="Manage shared sessions.")
notebook_app = typer.Typer(help="Manage notebooks and imported markdown records.")
provider_app = typer.Typer(help="Manage provider OAuth login.")
book_app = typer.Typer(help="Manage interactive Books (BookEngine).")

app.add_typer(bot_app, name="bot")
app.add_typer(chat_app, name="chat")
app.add_typer(kb_app, name="kb")
app.add_typer(memory_app, name="memory")
app.add_typer(plugin_app, name="plugin")
app.add_typer(config_app, name="config")
app.add_typer(session_app, name="session")
app.add_typer(notebook_app, name="notebook")
app.add_typer(provider_app, name="provider")
app.add_typer(book_app, name="book")

register_bot(bot_app)
register_chat(chat_app)
register_kb(kb_app)
register_memory(memory_app)
register_plugin(plugin_app)
register_config(config_app)
register_session(session_app)
register_notebook(notebook_app)
register_provider(provider_app)
register_book(book_app)


@app.command("run")
def run_capability(
    capability: str = typer.Argument(
        ...,
        help="Capability name (e.g. chat, deep_solve, deep_question, deep_research, math_animator).",
    ),
    message: str = typer.Argument(..., help="Message to send."),
    session: str | None = typer.Option(None, "--session", help="Existing session id."),
    tool: list[str] = typer.Option([], "--tool", "-t", help="Enabled tool(s)."),
    kb: list[str] = typer.Option([], "--kb", help="Knowledge base name."),
    notebook_ref: list[str] = typer.Option([], "--notebook-ref", help="Notebook references."),
    history_ref: list[str] = typer.Option([], "--history-ref", help="Referenced session ids."),
    language: str = typer.Option("en", "--language", "-l", help="Response language."),
    config: list[str] = typer.Option([], "--config", help="Capability config key=value."),
    config_json: str | None = typer.Option(
        None, "--config-json", help="Capability config as JSON."
    ),
    fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich | json."),
) -> None:
    """Run any capability in a single turn (agent-first entry point)."""
    from deeptutor.app import DeepTutorApp

    from .common import run_turn_and_render

    request = build_turn_request(
        content=message,
        capability=capability,
        session_id=session,
        tools=tool,
        knowledge_bases=kb,
        language=language,
        config_items=config,
        config_json=config_json,
        notebook_refs=notebook_ref,
        history_refs=history_ref,
    )
    maybe_run(run_turn_and_render(app=DeepTutorApp(), request=request, fmt=fmt))


@app.command()
def start() -> None:
    """Launch backend + frontend together."""
    from pathlib import Path
    import subprocess
    import sys

    script = str(Path(__file__).resolve().parent.parent / "scripts" / "start_web.py")
    result = subprocess.run([sys.executable, script], check=False)
    if result.returncode:
        raise typer.Exit(code=result.returncode)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int = typer.Option(get_backend_port(), help="Port number."),
    reload: bool = typer.Option(False, help="Enable auto-reload for development."),
) -> None:
    """Start the DeepTutor API server."""
    import asyncio
    import sys

    set_mode(RunMode.SERVER)

    # Windows: uvicorn defaults to SelectorEventLoop which does not support
    # asyncio.create_subprocess_exec.  Switch to ProactorEventLoop so that
    # child-process APIs (used by Math Animator renderer, etc.) work correctly.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        import uvicorn
    except ImportError:
        console.print(
            "[bold red]Error:[/] API server dependencies not installed.\n"
            "Run: pip install -e '.[server]'"
        )
        raise typer.Exit(code=1)

    uvicorn.run(
        "deeptutor.api.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_excludes=["web/*", "data/*"] if reload else None,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
