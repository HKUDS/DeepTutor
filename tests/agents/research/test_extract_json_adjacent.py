"""extract_json_from_text must parse the first object when another follows."""

from deeptutor.agents.research.utils.json_utils import extract_json_from_text


def test_adjacent_objects_returns_first() -> None:
    assert extract_json_from_text('{"a": 1}{"b": 2}') == {"a": 1}


def test_object_then_array_returns_object() -> None:
    assert extract_json_from_text('{"a": 1}[2, 3]') == {"a": 1}


def test_trailing_prose_still_works() -> None:
    assert extract_json_from_text('result: {"x": true} done') == {"x": True}
