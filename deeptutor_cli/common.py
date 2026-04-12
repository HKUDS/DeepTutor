"""Shared CLI helpers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from deeptutor.app import DeepTutorApp, TurnRequest

console = Console()


def parse_config_items(items: list[str]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for item in items:
        key, sep, raw_value = item.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"无效 --config 参数 `{item}`，期望格式 KEY=VALUE。")
        config[key.strip()] = _parse_scalar_value(raw_value.strip())
    return config


def parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"无效 JSON 配置：{exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 配置必须是对象。")
    return value


def parse_notebook_references(items: list[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in items:
        notebook_id, _, record_part = item.partition(":")
        resolved_notebook_id = notebook_id.strip()
        if not resolved_notebook_id:
            raise ValueError(f"无效笔记本引用 `{item}`。")
        record_ids = [
            record_id.strip()
            for record_id in record_part.split(",")
            if record_id.strip()
        ]
        refs.append({"notebook_id": resolved_notebook_id, "record_ids": record_ids})
    return refs


async def run_turn_and_render(
    *,
    app: DeepTutorApp,
    request: TurnRequest,
    fmt: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    session, turn = await app.start_turn(request)

    if fmt == "json":
        async for item in app.stream_turn(turn["id"]):
            console.print(json.dumps(item, ensure_ascii=False))
        return session, turn

    await render_turn_stream(app=app, turn_id=turn["id"])
    console.print(
        f"[dim]session={session['id']} turn={turn['id']} capability={request.capability}[/]",
        highlight=False,
    )
    return session, turn


async def render_turn_stream(*, app: DeepTutorApp, turn_id: str) -> None:
    content_buf = ""
    current_stage = ""
    async for item in app.stream_turn(turn_id):
        event_type = str(item.get("type", ""))
        if event_type == "stage_start":
            if content_buf:
                console.print(Markdown(content_buf))
                content_buf = ""
            current_stage = str(item.get("stage", "") or "")
            console.print(f"\n[bold cyan]▶ {current_stage or '处理中'}[/]", highlight=False)
        elif event_type == "stage_end":
            if content_buf:
                console.print(Markdown(content_buf))
                content_buf = ""
            current_stage = ""
        elif event_type == "thinking":
            console.print(f"  [dim]{item.get('content', '')}[/]", highlight=False)
        elif event_type == "progress":
            console.print(f"  [dim]{item.get('content', '')}[/]", highlight=False)
        elif event_type == "content":
            content_buf += str(item.get("content", "") or "")
        elif event_type == "tool_call":
            metadata = item.get("metadata", {}) or {}
            console.print(
                f"  [yellow]tool[/] {item.get('content', '')} {json.dumps(metadata, ensure_ascii=False)}",
                highlight=False,
            )
        elif event_type == "tool_result":
            console.print(f"  [green]result[/] {item.get('content', '')}", highlight=False)
        elif event_type == "error":
            console.print(f"[bold red]错误：[/] {item.get('content', '')}")
        elif event_type == "done":
            if content_buf:
                console.print(Markdown(content_buf))
                content_buf = ""


def build_turn_request(
    *,
    content: str,
    capability: str,
    session_id: str | None,
    tools: list[str],
    knowledge_bases: list[str],
    language: str,
    config_items: list[str],
    config_json: str | None,
    notebook_refs: list[str],
    history_refs: list[str],
) -> TurnRequest:
    config = parse_json_object(config_json)
    config.update(parse_config_items(config_items))
    return TurnRequest(
        content=content,
        capability=capability,
        session_id=session_id,
        tools=tools,
        knowledge_bases=knowledge_bases,
        language=language,
        config=config,
        notebook_references=parse_notebook_references(notebook_refs),
        history_references=[item.strip() for item in history_refs if item.strip()],
    )


def maybe_run(coro):  # noqa: ANN001
    return asyncio.run(coro)


def print_session_table(sessions: list[dict[str, Any]]) -> None:
    table = Table(title="会话")
    table.add_column("ID")
    table.add_column("标题")
    table.add_column("能力")
    table.add_column("状态")
    table.add_column("消息数", justify="right")
    for session in sessions:
        table.add_row(
            str(session.get("id", "")),
            str(session.get("title", "")),
            str(session.get("capability", "") or "chat"),
            str(session.get("status", "")),
            str(session.get("message_count", 0)),
        )
    console.print(table)


def print_notebook_table(notebooks: list[dict[str, Any]]) -> None:
    table = Table(title="笔记本")
    table.add_column("ID")
    table.add_column("名称")
    table.add_column("记录数", justify="right")
    table.add_column("描述")
    for notebook in notebooks:
        table.add_row(
            str(notebook.get("id", "")),
            str(notebook.get("name", "")),
            str(notebook.get("record_count", 0)),
            str(notebook.get("description", "")),
        )
    console.print(table)


def print_path_result(path: str | Path) -> None:
    console.print(f"[dim]{Path(path).resolve()}[/]")


def _parse_scalar_value(raw_value: str) -> Any:
    lowered = raw_value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value
