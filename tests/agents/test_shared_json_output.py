from __future__ import annotations

import json

import pytest

from deeptutor.agents._shared.json_output import extract_json_object


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", {}),
        ('{"value": 1}', {"value": 1}),
        ('Result:\n```json\n{"value": 2}\n```', {"value": 2}),
        ('Model preface\n{"value": 3}', {"value": 3}),
        ('{"value": 4}\nTrailing explanation', {"value": 4}),
    ],
)
def test_extract_json_object(text: str, expected: dict[str, int]) -> None:
    assert extract_json_object(text) == expected


def test_extract_json_object_rejects_output_without_an_object() -> None:
    with pytest.raises(json.JSONDecodeError, match="No JSON object found"):
        extract_json_object("No structured output")
