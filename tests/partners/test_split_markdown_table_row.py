"""The shared markdown pipe-table row splitter keeps leading/trailing empty cells.

Regression guard for the class of bug fixed per-channel in #679/#682/#683: the
old ``str.strip("|")`` collapsed leading/trailing empty cells and shifted every
column. All three partner channels now split rows through this one primitive.
"""

from __future__ import annotations

from deeptutor.partners.helpers import (
    convert_markdown_table_to_labeled_rows,
    split_markdown_table_row,
)


def test_standard_row() -> None:
    assert split_markdown_table_row("| A | B | C |") == ["A", "B", "C"]


def test_leading_empty_cell_kept() -> None:
    assert split_markdown_table_row("|| B | C |") == ["", "B", "C"]


def test_trailing_empty_cell_kept() -> None:
    assert split_markdown_table_row("| A | B ||") == ["A", "B", ""]


def test_middle_empty_cell_kept() -> None:
    assert split_markdown_table_row("| A |  | C |") == ["A", "", "C"]


def test_row_without_outer_pipes() -> None:
    assert split_markdown_table_row("A | B") == ["A", "B"]


def test_slack_conversion_no_longer_shifts_columns() -> None:
    # A leading empty header column used to be dropped by strip("|"), shifting
    # every value one column to the left in the Slack labeled-row output.
    table = "|| Name | Age |\n| --- | --- | --- |\n| id1 | Alice | 30 |\n"
    out = convert_markdown_table_to_labeled_rows(table)
    assert "**Name**: Alice" in out  # Alice correctly under Name, not "id1"
    assert "**Age**: 30" in out
    assert "**Name**: id1" not in out
