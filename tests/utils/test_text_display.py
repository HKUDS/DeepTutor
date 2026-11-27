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


def test_joins_surrogate_pairs_into_one_character() -> None:
    # ``json.dumps`` escapes characters outside the BMP as surrogate pairs.
    escaped = "\\u597d\\u7684\\ud83d\\udc4d"
    decoded = decode_escaped_unicode_for_display(escaped)
    assert decoded == "好的👍"


def test_leaves_runs_with_unpaired_surrogates_escaped() -> None:
    text = "\\u4f60\\u597d\\ud83d"
    assert decode_escaped_unicode_for_display(text) == text
