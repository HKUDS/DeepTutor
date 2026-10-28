"""A literal NUL in Markdown must not crash the Word (DOCX) export.

``_add_inline_runs`` masks backslash escapes with the sentinel ``_MASK = "\x00"``
and pops one saved character per sentinel in ``_unmask``. A NUL already present
in the *input* collides with the sentinel but has no saved entry, so ``_unmask``
called ``deque.popleft()`` on an empty deque and raised ``IndexError`` — aborting
the whole export instead of treating the NUL as ordinary text.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from deeptutor.co_writer.docx_converter import _add_inline_runs


class _FakeParagraph:
    """Minimal stand-in so the pure text path runs without python-docx."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def add_run(self, text: str = "") -> MagicMock:
        self.texts.append(text)
        return MagicMock()


def test_literal_nul_in_markdown_does_not_crash_inline_runs() -> None:
    paragraph = _FakeParagraph()

    _add_inline_runs(paragraph, "Hello \x00 world")

    rendered = "".join(paragraph.texts)
    assert "\x00" not in rendered
    assert rendered == "Hello  world"


def test_nul_next_to_real_escape_is_handled() -> None:
    paragraph = _FakeParagraph()

    # ``\*`` is a real escape (masked then restored); the stray NUL must not
    # steal its saved character.
    _add_inline_runs(paragraph, "a\\*b\x00c")

    rendered = "".join(paragraph.texts)
    assert rendered == "a*bc"


@pytest.mark.parametrize(
    "markdown",
    [
        "hello{bad}world",
        "# hello{bad}world",
        "```\nhello{bad}world\n```",
        "| Column |\n| --- |\n| hello{bad}world |",
    ],
)
@pytest.mark.parametrize("bad", ["\x00", "\x0b", "\x1f", "\ud800", "\ufffe"])
def test_export_sanitizes_xml_text_in_every_markdown_block(markdown, bad):
    docx = pytest.importorskip("docx")
    from deeptutor.co_writer.docx_converter import markdown_to_docx

    data = markdown_to_docx(markdown.format(bad=bad))
    document = docx.Document(BytesIO(data))
    text = "\n".join(p.text for p in document.paragraphs)
    text += "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )
    assert "helloworld" in text
    assert bad not in text
