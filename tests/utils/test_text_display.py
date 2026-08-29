"""Tests for learner-facing unicode escape decoding (#973)."""

from __future__ import annotations

from deeptutor.utils.text_display import decode_escaped_unicode_for_display


def test_decodes_dense_non_ascii_runs() -> None:
    escaped = "\\u300c\\u6570\\u5236\\u8f6c\\u6362\\u300d"
    assert decode_escaped_unicode_for_display(escaped) == "「数制转换」"


def test_leaves_short_ascii_runs_alone() -> None:
    text = "A JSON string can encode A as \\u0041."
    assert decode_escaped_unicode_for_display(text) == text


def test_empty_and_plain_text_passthrough() -> None:
    assert decode_escaped_unicode_for_display("") == ""
    assert decode_escaped_unicode_for_display("hello") == "hello"
