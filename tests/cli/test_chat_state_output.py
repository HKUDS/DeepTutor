"""Regression tests for literal state values in the interactive chat CLI."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console
from rich.text import Text

from deeptutor_cli import chat


def _render(monkeypatch: pytest.MonkeyPatch, render, state: chat.ChatState) -> str:  # noqa: ANN001
    output = StringIO()
    monkeypatch.setattr(
        chat,
        "console",
        Console(file=output, force_terminal=False, color_system=None, width=1000),
    )
    render(state)
    return output.getvalue()


@pytest.mark.parametrize(
    ("tools", "expected"),
    [
        ([], "tools=[]"),
        (["rag"], "tools=[rag]"),
        (["rag", "web_search"], "tools=[rag, web_search]"),
    ],
)
def test_print_state_renders_tool_lists_literally(
    monkeypatch: pytest.MonkeyPatch,
    tools: list[str],
    expected: str,
) -> None:
    output = _render(monkeypatch, chat._print_state, chat.ChatState(tools=tools))

    assert expected in output


def test_print_state_renders_rich_markup_characters_literally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = chat.ChatState(
        session_id="[bold]session[/bold]",
        capability="[cyan]chat[/cyan]",
        tools=["[rag]"],
        knowledge_bases=["[red]kb[/red]"],
        history_references=["[green]history[/green]"],
        notebook_references=[
            {"notebook_id": "[blue]notebook[/blue]", "record_ids": ["[yellow]record[/yellow]"]}
        ],
        language="[magenta]en[/magenta]",
        config={"theme": "[italic]literal[/italic]"},
    )

    output = _render(monkeypatch, chat._print_state, state)

    for literal in (
        "[bold]session[/bold]",
        "[cyan]chat[/cyan]",
        "tools=[[rag]]",
        "kb=[[red]kb[/red]]",
        "history=[[green]history[/green]]",
        "[blue]notebook[/blue]:[yellow]record[/yellow]",
        "[magenta]en[/magenta]",
        '"[italic]literal[/italic]"',
    ):
        assert literal in output


def test_print_state_keeps_dim_style(monkeypatch: pytest.MonkeyPatch) -> None:
    rendered: list[object] = []

    class RecordingConsole:
        def print(self, value, **_kwargs) -> None:  # noqa: ANN001
            rendered.append(value)

    monkeypatch.setattr(chat, "console", RecordingConsole())

    chat._print_state(chat.ChatState(tools=["rag"]))

    assert len(rendered) == 1
    assert isinstance(rendered[0], Text)
    assert rendered[0].style == "dim"


def test_print_refs_renders_dynamic_values_literally(monkeypatch: pytest.MonkeyPatch) -> None:
    state = chat.ChatState(
        tools=["[bold]rag[/bold]"],
        knowledge_bases=["[red]kb[/red]"],
        history_references=["[green]history[/green]"],
        notebook_references=[{"notebook_id": "[blue]notebook[/blue]", "record_ids": []}],
    )

    output = _render(monkeypatch, chat._print_refs, state)

    assert "tools       [[bold]rag[/bold]]" in output
    assert "kb          [[red]kb[/red]]" in output
    assert "history     [[green]history[/green]]" in output
    assert "notebooks   [[blue]notebook[/blue]]" in output
