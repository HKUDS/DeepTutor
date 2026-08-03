"""Regression tests for partners.helpers.split_message."""

from __future__ import annotations

from deeptutor.partners.helpers import split_message


def test_split_message_nonpositive_max_len_returns_unsplit() -> None:
    content = "hello world"
    assert split_message(content, max_len=0) == [content]
    assert split_message(content, max_len=-1) == [content]


def test_split_message_normal_path() -> None:
    chunks = split_message("aaa\nbbb\nccc", max_len=5)
    assert chunks
    assert all(len(c) <= 5 for c in chunks)
