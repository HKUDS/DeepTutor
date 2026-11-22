"""Intra-word underscores must not become italics in the Word (DOCX) export.

Per CommonMark, ``_`` only opens/closes emphasis at a word boundary, so
``snake_case_word`` is literal text — unlike ``*`` which may emphasise
intra-word. ``_add_inline_runs`` matched the inner ``_case_`` as italic, which
both styled part of an identifier and dropped the surrounding underscores.
"""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.co_writer.docx_converter import _add_inline_runs


class _FakeRun:
    def __init__(self, text: str) -> None:
        self.text = text
        self.italic: bool | None = None
        self.bold: bool | None = None
        self.font = SimpleNamespace(name=None, strike=None)


class _FakeParagraph:
    def __init__(self) -> None:
        self.runs: list[_FakeRun] = []

    def add_run(self, text: str = "") -> _FakeRun:
        run = _FakeRun(text)
        self.runs.append(run)
        return run


def test_intraword_underscores_are_literal() -> None:
    paragraph = _FakeParagraph()

    _add_inline_runs(paragraph, "use snake_case_word and 中_英_文 please")

    assert "".join(run.text for run in paragraph.runs) == "use snake_case_word and 中_英_文 please"
    assert not any(run.italic for run in paragraph.runs)


def test_word_bounded_underscore_still_italic() -> None:
    paragraph = _FakeParagraph()

    _add_inline_runs(paragraph, "a _word_ here")

    assert any(run.italic and run.text == "word" for run in paragraph.runs)
