"""Empty markdown table cells must still appear in labeled-row conversion."""

from __future__ import annotations

from deeptutor.partners.helpers import convert_markdown_table_to_labeled_rows


def test_empty_cells_kept_in_converted_table() -> None:
    table = (
        "| Name | Score | Note |\n"
        "| --- | --- | --- |\n"
        "| Alice |  | ok |\n"
        "| Bob | 10 |  |\n"
    )
    out = convert_markdown_table_to_labeled_rows(table)
    assert out.count("**Name**:") == 2
    assert out.count("**Score**:") == 2
    assert out.count("**Note**:") == 2
    assert "**Score**: " in out  # Alice empty score kept
    assert out.endswith("**Note**: ") or "**Note**: " in out.split("\n")[1]
