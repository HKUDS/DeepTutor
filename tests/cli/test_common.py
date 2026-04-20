"""Unit tests for shared CLI helpers."""

from __future__ import annotations

import pytest

from deeptutor_cli.common import parse_json_object


def test_parse_json_object_whitespace_is_empty_dict() -> None:
    assert parse_json_object("   ") == {}


def test_parse_json_object_invalid_json_still_errors() -> None:
    with pytest.raises(ValueError, match="Invalid JSON config"):
        parse_json_object("{")
