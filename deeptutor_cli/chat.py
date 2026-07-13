"""Interactive chat REPL."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
import json
import shlex
from typing import Any

from rich.panel import Panel
import typer

from deeptutor.app import DeepTutorApp, TurnRequest

from .common import (
    console,
    maybe_run,
    parse_config_items,
    parse_json_object,
    regenerate_and_render,
    render_tool_result_entry,
    run_turn_and_render,
    tool_results,
)


@dataclass
class ChatState:
    session_id: str | None = None
    capability: str = "chat"
    tools: list[str] = field(default_factory=list)
    knowledge_bases: list[str] = field(default_factory=list)
    language: str = "en"
    notebook_references: list[dict[str, Any]] = field(default_factory=list)
    history_references: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


def register(app: typer.Typer) -> None:
    @app.callback(invoke_without_command=True)
    def chat(
        ctx: typer.Context,
        session: str | None = typer.Option(None, "--session", help="Resume an existing session."),
        tool: list[str] = typer.Option([], "--tool", "-t", help="Pre-enable tool(s)."),
        capability: str = typer.Option("chat", "--capability", "-c", help="Initial capability."),
        kb: list[str] = typer.Option([], "--kb", help="Pre-attach knowledge base(s)."),
        notebook_ref: list[str] = typer.Option([], "--notebook-ref", help="Notebook references."),
        history_ref: list[str] = typer.Option([], "--history-ref", help="Referenced session ids."),
        language: str = typer.Option("en", "--language", "-l", help="Response language."),
        config: list[str] = typer.Option([], "--config", help="Initial config key=value."),
        config_json: str | None = typer.Option(
            None, "--config-json", help="Initial config as JSON."
        ),
    ) -> None:
        """Enter interactive chat REPL. Use `deeptutor run` for single-turn execution."""
        if ctx.invoked_subcommand is not None:
            return

        try:
            initial_config = parse_json_object(config_json)
            initial_config.update(parse_config_items(config))
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

        state = ChatState(
            session_id=session,
            capability=capability,
            tools=list(tool),
            knowledge_bases=list(kb),
            language=language,
            notebook_references=_parse_notebook_refs(notebook_ref),
            history_references=[item.strip() for item in history_ref if item.strip()],
            config=initial_config,
        )
        maybe_run(_chat_repl(state))


async def _chat_repl(state: ChatState) -> None:
    client = DeepTutorApp()
    cron_service = None
    try:
        from deeptutor.services.cron import get_cron_service

        cron_service = get_cron_service()
        await cron_service.start()
    except Exception:
        cron_service = None

    if state.session_id:
        existing = await client.get_session(state.session_id)
        if existing is None:
            console.print(f"[red]Session not found:[/] {state.session_id}")
            raise typer.Exit(code=1)
        preferences = existing.get("preferences", {}) or {}
        state.capability = str(preferences.get("capability") or state.capability or "chat")
        state.tools = list(preferences.get("tools") or state.tools)
        state.knowledge_bases = list(preferences.get("knowledge_bases") or state.knowledge_bases)
        state.language = str(preferences.get("language") or state.language)
        state.notebook_references = list(
            preferences.get("notebook_references") or state.notebook_references
        )
        state.history_references = list(
            preferences.get("history_references") or state.history_references
        )

    console.print(
        Panel(
            "[bold]DeepTutor CLI[/]\n"
            "Type a message to chat. Ctrl-C interrupts a running turn. Commands:\n"
            "  /quit  /session  /status  /new  /clear\n"
            "  /regenerate (alias /retry) — re-run the last user message\n"
            "  /tool on|off <name>\n"
            "  /cap <name>\n"
            "  /kb <name>|none\n"
            "  /history add <id> | /history clear\n"
            "  /notebook add <ref> | /notebook clear\n"
            "  /show last|<n> — expand a tool result or captured thinking\n"
            "  /refs  /config show|set|clear",
            title="deeptutor chat",
        )
    )
    _print_state(state)

    try:
        while True:
            try:
                user_input = _read_repl_input()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not user_input:
                continue
            if user_input.startswith("/"):
                command = user_input.split(maxsplit=1)[0].lower()
                if command in {"/regenerate", "/retry"}:
                    if not state.session_id:
                        console.print("[yellow]No active session yet — send a message first.[/]")
                        continue
                    result = await regenerate_and_render(
                        app=client,
                        session_id=state.session_id,
                        capability=state.capability,
                        fmt="rich",
                    )
                    if result is not None:
                        session, _turn = result
                        state.session_id = str(session["id"])
                    continue
                should_continue = _apply_command(user_input, state)
                if should_continue:
                    continue
                break

            request = TurnRequest(
                content=user_input,
                capability=state.capability,
                session_id=state.session_id,
                tools=list(state.tools),
                knowledge_bases=list(state.knowledge_bases),
                language=state.language,
                config=dict(state.config),
                notebook_references=list(state.notebook_references),
                history_references=list(state.history_references),
            )
            session, _turn = await run_turn_and_render(app=client, request=request, fmt="rich")
            state.session_id = str(session["id"])
    finally:
        if cron_service is not None:
            with suppress(Exception):
                await cron_service.stop()


def _apply_command(raw: str, state: ChatState) -> bool:
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        console.print(f"[yellow]Could not parse command:[/] {exc}")
        return True
    if not parts:
        return True
    command = parts[0].lower()
    if command == "/quit":
        return False
    if command == "/session":
        console.print(f"session={state.session_id or '(new)'}")
        return True
    if command == "/status":
        _print_state(state)
        return True
    if command in {"/new", "/clear"}:
        state.session_id = None
        console.print("[dim]Started a new chat context.[/]")
        return True
    if command == "/refs":
        _print_refs(state)
        return True
    if command == "/tool" and len(parts) >= 3:
        action, tool_name = parts[1], parts[2]
        if action == "on" and tool_name not in state.tools:
            state.tools.append(tool_name)
        elif action == "off" and tool_name in state.tools:
            state.tools.remove(tool_name)
        _print_state(state)
        return True
    if command == "/cap" and len(parts) >= 2:
        state.capability = parts[1]
        _print_state(state)
        return True
    if command == "/kb" and len(parts) >= 2:
        value = parts[1]
        state.knowledge_bases = [] if value == "none" else [value]
        _print_state(state)
        return True
    if command == "/history" and len(parts) >= 2:
        if parts[1] == "clear":
            state.history_references = []
        elif parts[1] == "add" and len(parts) >= 3:
            state.history_references.append(parts[2])
        _print_state(state)
        return True
    if command == "/notebook" and len(parts) >= 2:
        if parts[1] == "clear":
            state.notebook_references = []
        elif parts[1] == "add" and len(parts) >= 3:
            state.notebook_references.extend(_parse_notebook_refs([parts[2]]))
        _print_state(state)
        return True
    if command == "/show":
        selector = parts[1] if len(parts) >= 2 else "last"
        entry = tool_results.get(selector)
        if entry is None:
            if selector == "last":
                console.print("[dim]No tool result captured yet in this session.[/]")
            else:
                console.print(
                    f"[dim]No tool result matches [bold]{selector}[/]. "
                    f"Available: {[e.index for e in tool_results.entries()] or 'none'}.[/]"
                )
        else:
            render_tool_result_entry(entry)
        return True
    if command == "/config" and len(parts) >= 2:
        subcommand = parts[1]
        if subcommand == "show":
            console.print_json(_format_config(state.config))
        elif subcommand == "clear":
            state.config = {}
        elif subcommand == "set":
            parsed = _parse_config_assignment(parts)
            if parsed is None:
                console.print("[yellow]Usage:[/] /config set key=value or /config set key value")
                return True
            key, value = parsed
            state.config[key] = _parse_config_value(value)
        _print_state(state)
        return True

    console.print("[dim]Unknown command.[/]")
    return True


def _read_repl_input() -> str:
    """Read one REPL message, supporting backslash-continued multi-line input."""

    lines: list[str] = []
    prompt = "[bold green]You>[/] "
    while True:
        line = console.input(prompt)
        if line.endswith("\\"):
            lines.append(line[:-1])
            prompt = "[dim]...[/] "
            continue
        lines.append(line)
        return "\n".join(lines).strip()


def _print_state(state: ChatState) -> None:
    console.print(
        "[dim]"
        f"session={state.session_id or '(new)'} "
        f"capability={state.capability} "
        f"tools={_format_list(state.tools)} "
        f"kb={_format_list(state.knowledge_bases)} "
        f"history={_format_list(state.history_references)} "
        f"notebook_refs={_format_notebook_refs(state.notebook_references)} "
        f"language={state.language} "
        f"config={_format_config(state.config)}"
        "[/]",
        highlight=False,
    )


def _print_refs(state: ChatState) -> None:
    console.print("[bold]Current state:[/]")
    console.print(f"  session     {state.session_id or '(new)'}")
    console.print(f"  capability  {state.capability}")
    console.print(f"  tools       {_format_list(state.tools)}")
    console.print(f"  kb          {_format_list(state.knowledge_bases)}")
    console.print(f"  history     {_format_list(state.history_references)}")
    console.print(f"  notebooks   {_format_notebook_refs(state.notebook_references)}")
    console.print(f"  language    {state.language}")
    console.print(f"  config      {_format_config(state.config)}")


def _format_list(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]" if items else "[]"


def _format_notebook_refs(refs: list[dict[str, Any]]) -> str:
    if not refs:
        return "[]"
    rendered = []
    for ref in refs:
        notebook_id = str(ref.get("notebook_id") or "")
        record_ids = [str(item) for item in ref.get("record_ids") or []]
        rendered.append(f"{notebook_id}:{','.join(record_ids)}" if record_ids else notebook_id)
    return "[" + ", ".join(rendered) + "]"


def _format_config(config: dict[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False, sort_keys=True)


def _parse_config_assignment(parts: list[str]) -> tuple[str, str] | None:
    if len(parts) >= 3 and "=" in parts[2]:
        key, _, value = parts[2].partition("=")
        key = key.strip()
        return (key, value) if key else None
    if len(parts) >= 4:
        key = parts[2].strip()
        value = " ".join(parts[3:]).strip()
        return (key, value) if key and value else None
    return None


def _parse_notebook_refs(values: list[str]) -> list[dict[str, Any]]:
    refs = []
    for value in values:
        notebook_id, _, record_ids_part = value.partition(":")
        notebook_id = notebook_id.strip()
        if not notebook_id:
            raise typer.BadParameter(f"Invalid notebook reference `{value}`.")
        record_ids = [item.strip() for item in record_ids_part.split(",") if item.strip()]
        refs.append({"notebook_id": notebook_id, "record_ids": record_ids})
    return refs


def _parse_config_value(raw_value: str) -> Any:
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        lowered = raw_value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in {"null", "none"}:
            return None
        return raw_value
