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
from deeptutor.services.llm.provider_core.tool_arguments import (
    load_tool_arguments,
    preserve_latex_escapes,
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


# ---------------------------------------------------------------------------
# LaTeX in the arguments
# ---------------------------------------------------------------------------

# What a model writes for a matrix: single backslashes, invalid JSON.
_LATEX_MATRIX = (
    r'{"question": "转移矩阵如下：\begin{pmatrix} 0.5 & 0.5 & 0 & 0\\ '
    r'0.5 & 0.5 & 0 & 0\end{pmatrix}"}'
)


def test_latex_commands_and_row_breaks_survive_repair() -> None:
    """``\\b`` and ``\\f`` are JSON escapes; here they are ``\\begin`` and
    ``\\frac``. Decoding them turned a matrix into a backspace character and
    an unparseable answer card."""
    args = _parse_tool_arguments(_LATEX_MATRIX, "mastery_quiz")

    assert args["question"] == (
        r"转移矩阵如下：\begin{pmatrix} 0.5 & 0.5 & 0 & 0\\ "
        r"0.5 & 0.5 & 0 & 0\end{pmatrix}"
    )
    assert "\x08" not in args["question"]
    assert "\x0c" not in args["question"]


def test_greek_and_relation_commands_survive_repair() -> None:
    # The unescaped quote forces the repair path; the LaTeX must still arrive.
    raw = r'{"q": "求 \theta、\right 与 $\frac12$", "bad": "a"b"}'
    args = load_tool_arguments(raw)

    assert args["q"] == r"求 \theta、\right 与 $\frac12$"


def test_a_real_newline_escape_stays_a_newline() -> None:
    raw = '{"q": "第一行\\n第二行"}'
    args = load_tool_arguments(raw)

    assert args == {"q": "第一行\n第二行"}


def test_valid_json_is_decoded_exactly_as_written() -> None:
    raw = r'{"q": "\\\\begin{pmatrix} 1 \\\\end{pmatrix}", "n": "a\nb"}'

    assert load_tool_arguments(raw) == {
        "q": r"\\begin{pmatrix} 1 \\end{pmatrix}",
        "n": "a\nb",
    }


def test_windows_paths_are_not_mistaken_for_latex() -> None:
    raw = r'{"file": "C:\Users\frank\x.txt", "bad": "a"b"}'

    assert load_tool_arguments(raw)["file"] == r"C:\Users\frank\x.txt"


def test_escaping_leaves_already_escaped_text_alone() -> None:
    raw = r'{"q": "\\alpha"}'

    assert preserve_latex_escapes(raw) == raw
