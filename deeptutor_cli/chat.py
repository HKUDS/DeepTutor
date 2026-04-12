"""Interactive chat REPL."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

import typer
from rich.panel import Panel

from deeptutor.app import DeepTutorApp, TurnRequest

from .common import console, maybe_run, run_turn_and_render


@dataclass
class ChatState:
    session_id: str | None = None
    capability: str = "chat"
    tools: list[str] = field(default_factory=list)
    knowledge_bases: list[str] = field(default_factory=list)
    language: str = "zh"
    notebook_references: list[dict[str, Any]] = field(default_factory=list)
    history_references: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


def register(app: typer.Typer) -> None:
    @app.callback(invoke_without_command=True)
    def chat(
        ctx: typer.Context,
        session: str | None = typer.Option(None, "--session", help="继续已有会话。"),
        tool: list[str] = typer.Option([], "--tool", "-t", help="预先启用工具。"),
        capability: str = typer.Option("chat", "--capability", "-c", help="初始能力。"),
        kb: list[str] = typer.Option([], "--kb", help="预关联知识库。"),
        notebook_ref: list[str] = typer.Option([], "--notebook-ref", help="笔记本引用。"),
        history_ref: list[str] = typer.Option([], "--history-ref", help="引用的会话 ID。"),
        language: str = typer.Option("zh", "--language", "-l", help="响应语言。"),
    ) -> None:
        """进入交互式聊天 REPL。单轮执行请使用 `deeptutor run`。"""
        if ctx.invoked_subcommand is not None:
            return

        state = ChatState(
            session_id=session,
            capability=capability,
            tools=list(tool),
            knowledge_bases=list(kb),
            language=language,
            notebook_references=_parse_notebook_refs(notebook_ref),
            history_references=[item.strip() for item in history_ref if item.strip()],
        )
        maybe_run(_chat_repl(state))


async def _chat_repl(state: ChatState) -> None:
    client = DeepTutorApp()
    if state.session_id:
        existing = await client.get_session(state.session_id)
        if existing is None:
            console.print(f"[red]未找到会话：[/] {state.session_id}")
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
            "输入消息开始聊天。命令：\n"
            "  /quit  /session  /new\n"
            "  /tool on|off <name>\n"
            "  /cap <name>\n"
            "  /kb <name>|none\n"
            "  /history add <id> | /history clear\n"
            "  /notebook add <ref> | /notebook clear\n"
            "  /refs  /config show|set|clear",
            title="deeptutor 聊天",
        )
    )
    _print_state(state)

    while True:
        try:
            user_input = console.input("[bold green]你>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not user_input:
            continue
        if user_input.startswith("/"):
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


def _apply_command(raw: str, state: ChatState) -> bool:
    parts = raw.split()
    command = parts[0].lower()
    if command == "/quit":
        return False
    if command == "/session":
        console.print(f"session={state.session_id or '(新建)'}")
        return True
    if command == "/new":
        state.session_id = None
        console.print("[dim]已开始新的聊天上下文。[/]")
        return True
    if command == "/refs":
        _print_state(state)
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
    if command == "/config" and len(parts) >= 2:
        subcommand = parts[1]
        if subcommand == "show":
            console.print_json(json.dumps(state.config, ensure_ascii=False))
        elif subcommand == "clear":
            state.config = {}
        elif subcommand == "set" and len(parts) >= 3:
            key, _, value = parts[2].partition("=")
            if key and value:
                state.config[key] = _parse_config_value(value)
        _print_state(state)
        return True

    console.print("[dim]未知命令。[/]")
    return True


def _print_state(state: ChatState) -> None:
    console.print(
        "[dim]"
        f"session={state.session_id or '(新建)'} "
        f"capability={state.capability} "
        f"tools={state.tools or '[]'} "
        f"kb={state.knowledge_bases or '[]'} "
        f"history={state.history_references or '[]'} "
        f"notebook_refs={state.notebook_references or '[]'}"
        "[/]",
        highlight=False,
    )


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
    except json.JSONDecodeError:
        lowered = raw_value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in {"null", "none"}:
            return None
        return raw_value
