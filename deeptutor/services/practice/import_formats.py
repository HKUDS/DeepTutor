"""Examples and structural schema for canonical flat imports; preview is authoritative."""

from typing import Literal

TemplateFormat = Literal["csv", "xlsx", "json", "json-schema"]


def json_template() -> list[dict]:
    return [
        {
            "question": "2 + 2 = ?",
            "question_type": "single_choice",
            "options": {"A": "3", "B": "4"},
            "correct_answer": "B",
            "explanation": "2 + 2 = 4",
            "difficulty": "Easy",
            "tags": ["Math"],
        },
        {
            "question": "Select the prime numbers",
            "question_type": "multi_choice",
            "options": {"A": "2", "B": "3", "C": "4"},
            "correct_answer": "A,B",
        },
        {
            "question": "The Earth orbits the Sun",
            "question_type": "true_false",
            "correct_answer": "true",
        },
        {
            "question": "China's capital is {{blank:blank-1}}; France's capital is {{blank:blank-2}}.",
            "question_type": "fill_blank",
            "correct_answer": "Beijing; Paris",
            "fill_spec": {
                "version": 2,
                "policy_version": "fill-grading/v2",
                "blanks": [
                    {
                        "id": "blank-1",
                        "label": "China's capital",
                        "max_score": "3.00000",
                        "accepted_answers": [
                            {"value": "Beijing", "score": "3.00000"},
                            {"value": "北京", "score": "3.00000"},
                            {"value": "Peking", "score": "1.00000"},
                        ],
                        "comparison_policy": "qti_literal_v1",
                        "rubric": "Beijing or 北京: 3 points; Peking: 1 point.",
                    },
                    {
                        "id": "blank-2",
                        "label": "France's capital",
                        "max_score": "2.00000",
                        "accepted_answers": [
                            {"value": "Paris", "score": "2.00000"},
                            {"value": "巴黎", "score": "2.00000"},
                        ],
                        "comparison_policy": "qti_literal_v1",
                        "rubric": "Paris or 巴黎: 2 points. Total: 5 points.",
                    },
                ],
            },
        },
        {
            "question": "What causes rain?",
            "question_type": "short_answer",
            "correct_answer": "Water vapor condenses into droplets that fall when heavy enough.",
            "explanation": "Assess condensation and falling droplets semantically; equivalent wording is acceptable.",
        },
        {
            "question": "Describe the water cycle",
            "question_type": "written",
            "correct_answer": "Evaporation, condensation, precipitation and collection.",
        },
    ]


def json_import_schema() -> dict:
    text = {"type": "string", "maxLength": 20000}
    nonempty = {**text, "minLength": 1, "pattern": r"\S"}
    points = {
        "type": "string",
        "pattern": r"^(?:(?:0|[1-9][0-9]{0,2})\.[0-9]{5}|1000\.00000)(?![\s\S])",
        "description": "Canonical five-decimal points, at most 1000.00000; answer score must not exceed its blank maximum.",
    }
    blank = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "label", "max_score", "accepted_answers", "comparison_policy", "rubric"],
        "properties": {
            "id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,80}(?![\\s\\S])"},
            "label": {
                "type": "string",
                "maxLength": 120,
                "description": "At most 120 UTF-8 bytes.",
            },
            "max_score": {**points, "not": {"const": "0.00000"}},
            "accepted_answers": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value", "score"],
                    "properties": {
                        "value": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000,
                            "pattern": r"\S",
                            "description": "At most 2000 UTF-8 bytes.",
                        },
                        "score": points,
                    },
                },
            },
            "comparison_policy": {
                "enum": [
                    "qti_literal_v1",
                    "exact_v1",
                    "comparison_v1",
                    "numeric_text_v1",
                    "semantic_v1",
                ]
            },
            "rubric": {
                "type": "string",
                "maxLength": 2000,
                "description": "At most 2000 UTF-8 bytes.",
            },
        },
    }
    options = {
        "oneOf": [
            {
                "type": "object",
                "minProperties": 2,
                "maxProperties": 10,
                "propertyNames": {"pattern": "^[A-J]$"},
                "additionalProperties": nonempty,
            },
            {"type": "array", "minItems": 2, "maxItems": 10, "items": nonempty},
        ]
    }
    properties = {
        "question": nonempty,
        "question_type": {
            "enum": [
                "single_choice",
                "multi_choice",
                "true_false",
                "fill_blank",
                "short_answer",
                "written",
            ]
        },
        "correct_answer": text,
        "options": options,
        "explanation": text,
        "difficulty": {"type": "string", "maxLength": 64},
        "tags": {
            "oneOf": [
                {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 100}},
                text,
            ]
        },
        "user_answer": {
            "const": "",
            "description": "Historical learner answers must be omitted or empty.",
        },
        "fill_spec": {
            "type": "object",
            "additionalProperties": False,
            "required": ["version", "policy_version", "blanks"],
            "properties": {
                "version": {"type": "integer", "const": 2},
                "policy_version": {"const": "fill-grading/v2"},
                "blanks": {"type": "array", "minItems": 1, "maxItems": 20, "items": blank},
            },
        },
        **{letter: text for letter in "ABCDEFGHIJ"},
    }
    choices = {
        "anyOf": [
            {"required": ["options"]},
            *[
                {"required": [a, b], "properties": {a: nonempty, b: nonempty}}
                for index, a in enumerate("ABCDEFGHIJ")
                for b in "ABCDEFGHIJ"[index + 1 :]
            ],
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Reactutor flat question import",
        "description": "Documented canonical flat JSON-array format (not question-content documents or legacy aliases). "
        "Upload UTF-8 JSON, at most 5 MiB. Server preview is authoritative: UTF-8 byte limits, "
        "unique blank IDs, exact ordered {{blank:id}} markers when present, option/answer references, "
        "normalized duplicate answers, score/max/full-credit constraints and historical-answer exclusion require semantic validation. "
        "Fill specifications are limited to 16384 canonical UTF-8 bytes. "
        "Older underscore-only stems and parser aliases remain supported outside these authoring rules.",
        "type": "array",
        "minItems": 1,
        "maxItems": 500,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["question", "question_type"],
            "properties": properties,
            "allOf": [
                {
                    "if": {"properties": {"question_type": {"const": "fill_blank"}}},
                    "then": {"required": ["fill_spec"]},
                    "else": {
                        "required": ["correct_answer"],
                        "properties": {"correct_answer": nonempty},
                        "not": {"required": ["fill_spec"]},
                    },
                },
                {
                    "if": {
                        "properties": {"question_type": {"enum": ["single_choice", "multi_choice"]}}
                    },
                    "then": choices,
                },
                {
                    "if": {"properties": {"question_type": {"const": "true_false"}}},
                    "then": {"properties": {"correct_answer": {"enum": ["true", "false"]}}},
                },
            ],
        },
    }
