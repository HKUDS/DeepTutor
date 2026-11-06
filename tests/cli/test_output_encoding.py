"""CLI output that is piped or redirected on a legacy Windows code page."""

from __future__ import annotations

import io
import sys

import pytest

from deeptutor_cli import main as cli_main


def _code_page_stream() -> io.TextIOWrapper:
    """The stdout Windows gives a piped or redirected process on a cp1252 system."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")


def test_redirected_output_replaces_text_outside_the_code_page(monkeypatch) -> None:
    """``deeptutor skill --help > file`` raised UnicodeEncodeError on cp1252 and
    exited 1, because the help for ``skill login`` is in Chinese. Model replies
    with CJK text or emoji failed the same way under ``deeptutor run``. The
    output keeps its code page and gets ``?`` for what it cannot represent, as
    ``deeptutor start`` does since #702."""
    stdout = _code_page_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", _code_page_stream())
    monkeypatch.setattr(sys, "argv", ["deeptutor", "skill", "--help"])
    # ``app()`` installs Typer's exception hook; restore it after the test.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)

    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()

    assert exit_info.value.code == 0
    stdout.flush()
    help_text = stdout.buffer.getvalue().decode("cp1252")
    assert "login" in help_text
    # The Chinese help for ``skill login`` was replaced, not fatal.
    assert "?" in help_text
