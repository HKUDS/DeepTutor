"""Feishu markdown tables must keep leading/trailing empty cells."""

from __future__ import annotations

from deeptutor.partners.channels.feishu import FeishuChannel


def test_leading_empty_header_keeps_column_alignment() -> None:
    table = "|| Name | Age |\n| --- | --- | --- |\n| id1 | Alice | 30 |\n| id2 | Bob | 25 |\n"
    parsed = FeishuChannel._parse_md_table(table)
    assert parsed is not None
    assert [c["display_name"] for c in parsed["columns"]] == ["", "Name", "Age"]
    assert parsed["rows"] == [
        {"c0": "id1", "c1": "Alice", "c2": "30"},
        {"c0": "id2", "c1": "Bob", "c2": "25"},
    ]


def test_trailing_empty_header_keeps_row_values() -> None:
    table = "| Name | Age ||\n| --- | --- | --- |\n| Alice | 30 | VIP |\n| Bob | 25 | |\n"
    parsed = FeishuChannel._parse_md_table(table)
    assert parsed is not None
    assert [c["display_name"] for c in parsed["columns"]] == ["Name", "Age", ""]
    assert parsed["rows"] == [
        {"c0": "Alice", "c1": "30", "c2": "VIP"},
        {"c0": "Bob", "c1": "25", "c2": ""},
    ]
