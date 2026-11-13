"""The JSON template must be importable by the same normalizer the UI uses."""

from __future__ import annotations

from deeptutor.services.practice.import_formats import json_import_schema, json_template
from deeptutor.services.practice.importing import normalize_question


def test_json_template_roundtrips_through_the_importer() -> None:
    questions = [normalize_question(row) for row in json_template()]

    assert [row["question_type"] for row in questions] == [
        "single_choice",
        "multi_choice",
        "true_false",
        "fill_blank",
        "short_answer",
        "written",
    ]
    fill = questions[3]
    assert fill["fill_spec"]["version"] == 2
    assert [blank["id"] for blank in fill["fill_spec"]["blanks"]] == ["blank-1", "blank-2"]
    assert fill["question_id"].startswith("import:")


def test_json_schema_requires_a_fill_spec_for_blanks() -> None:
    schema = json_import_schema()

    conditional = schema["items"]["allOf"][0]
    assert conditional["if"]["properties"]["question_type"]["const"] == "fill_blank"
    assert conditional["then"]["required"] == ["fill_spec"]
