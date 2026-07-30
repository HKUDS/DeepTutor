"""Tests for robust JSON parsing utilities."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from deeptutor.utils.json_parser import parse_json_response, safe_json_loads

# ---------------------------------------------------------------------------
# parse_json_response — direct parsing
# ---------------------------------------------------------------------------


class TestParseJsonResponseDirect:
    def test_valid_json_object(self) -> None:
        assert parse_json_response('{"key": "value"}') == {"key": "value"}

    def test_valid_json_array(self) -> None:
        assert parse_json_response("[1, 2, 3]") == [1, 2, 3]

    def test_valid_json_string(self) -> None:
        assert parse_json_response('"hello"') == "hello"

    def test_empty_string_returns_fallback(self) -> None:
        assert parse_json_response("") == {}

    def test_whitespace_only_returns_fallback(self) -> None:
        assert parse_json_response("   \n  ") == {}

    def test_none_returns_fallback(self) -> None:
        assert parse_json_response(None) == {}  # type: ignore[arg-type]

    def test_explicit_none_fallback(self) -> None:
        assert parse_json_response("", fallback=None) is None

    def test_custom_fallback(self) -> None:
        assert parse_json_response("not json", fallback={"default": True}) == {"default": True}


# ---------------------------------------------------------------------------
# parse_json_response — markdown extraction
# ---------------------------------------------------------------------------


class TestParseJsonResponseMarkdown:
    def test_json_code_block(self) -> None:
        response = '```json\n{"key": "value"}\n```'
        assert parse_json_response(response) == {"key": "value"}

    def test_plain_code_block(self) -> None:
        response = '```\n{"answer": 42}\n```'
        assert parse_json_response(response) == {"answer": 42}

    def test_code_block_with_surrounding_text(self) -> None:
        response = 'Here is the result:\n```json\n{"x": 1}\n```\nDone.'
        assert parse_json_response(response) == {"x": 1}

    def test_nested_backticks_extracts_first(self) -> None:
        response = '```json\n{"a": 1}\n```\nsome text\n```json\n{"b": 2}\n```'
        result = parse_json_response(response)
        assert result == {"a": 1}


# ---------------------------------------------------------------------------
# parse_json_response — json-repair
# ---------------------------------------------------------------------------


class TestParseJsonResponseRepair:
    def test_trailing_comma_repaired(self) -> None:
        """json-repair should handle trailing commas if installed."""
        response = '{"key": "value",}'
        result = parse_json_response(response)
        if result == {}:
            pytest.skip("json-repair not installed")
        assert result == {"key": "value"}

    def test_missing_quotes_repaired(self) -> None:
        response = "{key: value}"
        result = parse_json_response(response)
        if result == {}:
            pytest.skip("json-repair not installed")
        assert isinstance(result, dict)

    def test_repair_unavailable_returns_fallback(self) -> None:
        with patch("deeptutor.utils.json_parser.repair_json", None):
            result = parse_json_response("{bad json", fallback={"err": True})
            assert result == {"err": True}

    def test_invalid_plain_text_is_not_logged_as_error(self, caplog) -> None:
        caplog.set_level(logging.ERROR)

        result = parse_json_response("not json", fallback={"default": True})

        assert result == {"default": True}
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------------------------------
# safe_json_loads
# ---------------------------------------------------------------------------


class TestSafeJsonLoads:
    def test_valid_json(self) -> None:
        assert safe_json_loads('{"a": 1}') == {"a": 1}

    def test_invalid_json_returns_default_fallback(self) -> None:
        assert safe_json_loads("not json") == {}

    def test_invalid_json_returns_custom_fallback(self) -> None:
        assert safe_json_loads("not json", fallback=[]) == []

    def test_explicit_none_fallback(self) -> None:
        assert safe_json_loads("bad", fallback=None) is None


class TestParseJsonResponseTrailingProse:
    def test_trailing_brace_prose_keeps_object(self) -> None:
        raw = '{"chapters":[{"title":"Intro"}]} note: see {schema}'
        result = parse_json_response(raw)
        assert result == {"chapters": [{"title": "Intro"}]}

    def test_trailing_brace_prose_keeps_array(self) -> None:
        raw = '[{"id":1},{"id":2}] trailing {x}'
        result = parse_json_response(raw, fallback=None)
        assert result == [{"id": 1}, {"id": 2}]


class TestParseJsonResponseLeadingProse:
    """Untagged reasoning preludes with JSON fragments inside (issue #692)."""

    def test_leading_prose_with_brace_example_keeps_payload(self) -> None:
        raw = (
            'The output format is {"chapters": []} so I will fill it in.\n'
            '{"chapters":[{"title":"C1"},{"title":"C2"},{"title":"C3"}]}'
        )
        result = parse_json_response(raw, fallback=None)
        assert result == {"chapters": [{"title": "C1"}, {"title": "C2"}, {"title": "C3"}]}

    def test_two_concatenated_objects_longest_wins(self) -> None:
        raw = '{"plan": "six chapters"}\n{"chapters":[{"title":"C1"},{"title":"C2"}]}'
        result = parse_json_response(raw, fallback=None)
        assert result == {"chapters": [{"title": "C1"}, {"title": "C2"}]}

    def test_prose_on_both_sides_keeps_payload(self) -> None:
        raw = (
            'Schema: {"chapters": []}.\n'
            '{"chapters":[{"title":"C1"}]}\n'
            "Note: each entry follows {title} form."
        )
        result = parse_json_response(raw, fallback=None)
        assert result == {"chapters": [{"title": "C1"}]}

    def test_single_small_object_still_returned(self) -> None:
        raw = 'Prefix prose {"only": 1} suffix prose'
        assert parse_json_response(raw, fallback=None) == {"only": 1}


# ---------------------------------------------------------------------------
# parse_json_response — <think> reasoning tags (issue #673)
# ---------------------------------------------------------------------------


class TestParseJsonResponseThinkTags:
    def test_think_block_before_json(self) -> None:
        response = (
            "<think>\n1. Analyze user intent...\n2. Determine target audience...\n</think>\n"
            '{"title":"T","description":"D","scope":"S","rationale":"R"}'
        )
        assert parse_json_response(response) == {
            "title": "T",
            "description": "D",
            "scope": "S",
            "rationale": "R",
        }

    def test_think_block_containing_braces_does_not_leak(self) -> None:
        """Braces inside the reasoning must not be returned instead of the real object."""
        response = (
            '<think>maybe output {"draft": true} or [a, b]</think>\n'
            '{"title":"Real","description":"D"}'
        )
        assert parse_json_response(response) == {"title": "Real", "description": "D"}

    def test_think_block_with_markdown_fence(self) -> None:
        response = '<think>reasoning here</think>\n```json\n{"answer": 42}\n```'
        assert parse_json_response(response) == {"answer": 42}

    def test_think_tag_case_insensitive(self) -> None:
        response = '<THINK>step by step</THINK>{"ok": true}'
        assert parse_json_response(response) == {"ok": True}

    def test_only_think_block_returns_fallback(self) -> None:
        response = "<think>just reasoning, no payload</think>"
        assert parse_json_response(response) == {}
        assert parse_json_response(response, fallback=None) is None

    def test_multiple_think_blocks_stripped(self) -> None:
        response = '<think>one</think>{"a":1}<think>two {b}</think>'
        assert parse_json_response(response) == {"a": 1}

    def test_literal_think_in_valid_json_preserved(self) -> None:
        """A valid JSON string value that literally contains <think> must not be altered."""
        response = '{"x":"literal <think>keep</think> value"}'
        assert parse_json_response(response, fallback=None) == {
            "x": "literal <think>keep</think> value"
        }

    def test_unclosed_think_prelude_without_braces(self) -> None:
        response = '<think>reasoning here, no JSON yet\n{"real":1}'
        assert parse_json_response(response, fallback=None) == {"real": 1}
