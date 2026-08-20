"""Generated code must at least parse before it reaches the reader.

A truncated snippet is worse than no snippet: the reader copies it, it fails,
and nothing in the page said it was never checked. Parsing is free, runs
in-process, and has no side effects — unlike executing it, which a generated
snippet must never be trusted to do.
"""

from __future__ import annotations

import pytest

from deeptutor.book.blocks.code import _CHECKABLE, _syntax_error


@pytest.mark.parametrize(
    "code",
    [
        "def f():\n    return 1",
        "x = [1, 2, 3]\nprint(sum(x))",
        "",  # empty is rejected earlier, and parses here
    ],
)
def test_valid_python_passes(code: str) -> None:
    assert _syntax_error(code, "python") is None


@pytest.mark.parametrize(
    "code",
    [
        'print("hi',  # unterminated string — the classic truncation
        "def f(:\n    pass",  # malformed signature
        "if True\n    pass",  # missing colon
        "def f():\n  return 1\n   return 2",  # inconsistent indent
    ],
)
def test_malformed_python_is_reported(code: str) -> None:
    error = _syntax_error(code, "python")
    assert error, f"expected a syntax error for {code!r}"
    assert isinstance(error, str) and error.strip()


def test_json_is_validated_too() -> None:
    assert _syntax_error('{"a": 1}', "json") is None
    assert _syntax_error('{"a": }', "json")


@pytest.mark.parametrize("language", ["rust", "go", "haskell", "", "unknown"])
def test_languages_we_cannot_check_are_left_alone(language: str) -> None:
    """No false failures for languages without an in-process parser."""
    assert _syntax_error("this is definitely not valid code {{{", language) is None


def test_language_matching_is_case_and_whitespace_insensitive() -> None:
    assert _syntax_error('print("hi', "  Python  ") is not None
    assert _syntax_error('print("hi', "PY") is not None


def test_a_broken_checker_never_breaks_generation(monkeypatch) -> None:
    """Validation is a safety net, not a new failure mode."""

    def boom(_code: str) -> str | None:
        raise RuntimeError("checker exploded")

    monkeypatch.setitem(_CHECKABLE, "python", boom)
    assert _syntax_error("anything", "python") is None
