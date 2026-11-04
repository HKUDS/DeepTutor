"""``convert_tools`` keeps an explicit ``strict`` setting and defaults the rest to
non-strict (#1975, #2427)."""

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
def test_unset_strict_defaults_to_non_strict(fields) -> None:
    assert convert_tools([_tool(**fields)])[0]["strict"] is False


def test_mastery_quiz_keeps_its_optional_arguments_optional() -> None:
    from deeptutor.capabilities.mastery.tools import MasteryQuizTool

    tool = MasteryQuizTool().get_definition().to_openai_schema()
    original = copy.deepcopy(tool)

    converted = convert_tools([tool])[0]

    # Left unset, Responses treats the tool as strict and makes ``visual`` and
    # every other optional argument required, so a text-only card cannot be posed.
    assert converted["strict"] is False
    assert "visual" not in converted["parameters"].get("required", [])
    assert converted["parameters"] == original["function"]["parameters"]
    assert tool == original


def test_native_web_search_ignores_strict() -> None:
    tool = _tool(strict=True)
    tool["function"]["name"] = "web_search"

    assert convert_tools([tool], native_web_search=True) == [{"type": "web_search"}]
