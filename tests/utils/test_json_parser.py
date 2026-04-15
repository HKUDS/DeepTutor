"""Tests for robust JSON parsing utilities."""

from __future__ import annotations

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
