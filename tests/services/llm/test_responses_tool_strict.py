"""Responses conversion preserves strict choices and optional argument semantics."""

from __future__ import annotations

import copy

import pytest

from deeptutor.services.llm.provider_core.openai_responses import convert_tools


def _tool(**function_fields):
    return {
        "type": "function",
        "function": {
            "name": "demo_search",
            "description": "Search a synthetic demo.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            **function_fields,
        },
    }


@pytest.mark.parametrize("strict", [False, True])
def test_explicit_strict_is_preserved(strict: bool) -> None:
    tool = _tool(strict=strict)
    original = copy.deepcopy(tool)

    converted = convert_tools([tool])[0]

    assert converted["strict"] is strict
    assert converted["parameters"] == original["function"]["parameters"]
    assert tool == original


@pytest.mark.parametrize("fields", [{}, {"strict": None}])
def test_unset_strict_preserves_non_strict_chat_default(fields) -> None:
    tool = _tool(**fields)
    tool["function"]["parameters"]["properties"]["limit"] = {"type": "integer"}
    original = copy.deepcopy(tool)

    converted = convert_tools([tool])[0]

    assert converted["strict"] is False
    assert converted["parameters"] == original["function"]["parameters"]
    assert converted["parameters"]["required"] == ["query"]
    assert "limit" not in converted["parameters"]["required"]
    assert tool == original


def test_native_web_search_ignores_strict() -> None:
    tool = _tool(strict=True)
    tool["function"]["name"] = "web_search"

    assert convert_tools([tool], native_web_search=True) == [{"type": "web_search"}]


def test_mastery_quiz_resume_id_can_be_absent() -> None:
    from deeptutor.capabilities.mastery.tools import MasteryQuizTool

    tool = MasteryQuizTool().get_definition().to_openai_schema()
    original = copy.deepcopy(tool)

    converted = convert_tools([tool])[0]

    assert converted["strict"] is False
    assert "resume_question_id" in converted["parameters"]["properties"]
    assert "resume_question_id" not in converted["parameters"].get("required", [])
    assert converted["parameters"] == original["function"]["parameters"]
    assert tool == original
