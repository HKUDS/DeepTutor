"""All-empty markdown table rows are not separators."""

from deeptutor.partners.helpers import is_markdown_table_separator_row


def test_empty_row_is_not_separator() -> None:
    assert is_markdown_table_separator_row(["", "", ""]) is False
    assert is_markdown_table_separator_row([]) is False


def test_dash_row_is_separator() -> None:
    assert is_markdown_table_separator_row(["---", "---"]) is True
    assert is_markdown_table_separator_row([":---", "---:"]) is True


def test_data_row_is_not_separator() -> None:
    assert is_markdown_table_separator_row(["1", "2"]) is False
    assert is_markdown_table_separator_row(["1", "", "3"]) is False
