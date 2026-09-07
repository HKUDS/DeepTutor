"""Repaired tool arguments are not all equally trustworthy.

An unescaped quote inside a string is repaired losslessly and says nothing
about the call. Arguments that were *cut off* are a different failure: repair
still hands back an object, so the call proceeds and the card looks finished
while options the model had not written yet are simply gone, and the last one
keeps whatever bytes followed the break. That deserves a log line — it was
silent, and a thinking model that spends its budget before writing its tool
arguments hits it routinely.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib

from loguru import logger

from deeptutor.services.llm.provider_core.openai_responses.parsing import (
    _parse_tool_arguments,
)


@contextlib.contextmanager
def captured_logs(level: str) -> Iterator[list[str]]:
    """loguru does not reach pytest's caplog; add a sink of our own."""
    lines: list[str] = []
    sink_id = logger.add(lines.append, level=level, format="{message}")
    try:
        yield lines
    finally:
        logger.remove(sink_id)


# What DeepSeek actually emitted before running out of budget: a second
# option whose key is still half-written.
_TRUNCATED = (
    '{"intro": "场景题", "questions": [{"question": "要累积 logs 该怎么写？", '
    '"options": [{"label": "operator.add", "description": "追加。"}, {"label'
)
# Prose with an unescaped quote in it — valid content, invalid JSON.
_UNESCAPED_QUOTE = '{"questions": [{"prompt": "路径名"1" 是哪个？", "options": ["A"]}]}'


def test_truncated_arguments_are_reported() -> None:
    with captured_logs("WARNING") as lines:
        args = _parse_tool_arguments(_TRUNCATED, "ask_user")

    assert args["intro"] == "场景题"
    assert any("cut off" in line for line in lines), lines


def test_a_repaired_unescaped_quote_stays_quiet() -> None:
    with captured_logs("WARNING") as lines:
        args = _parse_tool_arguments(_UNESCAPED_QUOTE, "ask_user")

    assert args.get("questions")
    assert lines == []


def test_valid_arguments_are_returned_untouched_and_unlogged() -> None:
    with captured_logs("DEBUG") as lines:
        args = _parse_tool_arguments('{"questions": [{"prompt": "x"}]}', "ask_user")

    assert args == {"questions": [{"prompt": "x"}]}
    assert lines == []


def test_a_complete_object_is_never_called_truncated_however_mangled() -> None:
    """Both failures raise the same decoder error; only the ending differs."""
    from deeptutor.services.llm.provider_core.openai_responses.parsing import (
        _looks_truncated,
    )

    assert _looks_truncated(_TRUNCATED)
    assert not _looks_truncated(_UNESCAPED_QUOTE)
    assert not _looks_truncated('{"questions": []}  \n')
    assert not _looks_truncated({"already": "parsed"})


def test_arguments_repair_cannot_make_an_object_of_reach_the_tool_as_raw() -> None:
    with captured_logs("WARNING") as lines:
        args = _parse_tool_arguments("not json at all", "ask_user")

    assert args == {"raw": "not json at all"}
    assert any("Could not parse" in line for line in lines), lines
