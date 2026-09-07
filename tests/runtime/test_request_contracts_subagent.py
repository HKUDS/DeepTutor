"""Regression coverage for typed per-turn subagent consult budgets."""

from __future__ import annotations

import pytest

from deeptutor.app.contracts import TurnRequest
from deeptutor.runtime.capability_routing import route_explicit_quiz_request
from deeptutor.runtime.request_contracts import (
    validate_capability_config,
    validate_chat_request_config,
)


def test_turn_request_translates_legacy_subagent_consult_budget() -> None:
    with pytest.warns(DeprecationWarning):
        request = TurnRequest(
            content="delegate this",
            config={"subagent_consult_budget": 5},
        )
    assert request.subagent_consult_budget == 5
    assert request.config == {}


def test_chat_config_rejects_runtime_subagent_consult_budget() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_chat_request_config({"subagent_consult_budget": 5})
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_capability_config("chat", {"subagent_consult_budget": 5})


def test_chat_config_still_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_chat_request_config({"totally_unknown_key": 1})


def test_explicit_quiz_routing_rules() -> None:
    route = route_explicit_quiz_request(
        "Please generate 3 quiz questions",
        "chat",
        enabled=True,
    )
    assert route is not None
    assert route.capability == "deep_question"
    assert route.requested_capability == "chat"
    assert route.auto_routed is True

    assert (
        route_explicit_quiz_request("What is formative assessment?", "chat", enabled=True) is None
    )
    assert route_explicit_quiz_request("Practice more", "chat", enabled=True) is None
    assert route_explicit_quiz_request("Quiz me on this chapter", "chat", enabled=True) is None
    assert route_explicit_quiz_request("Start a quiz", "chat", enabled=True) is None
    assert route_explicit_quiz_request("考考我", "chat", enabled=True) is None
    assert route_explicit_quiz_request("考考我", "deep_question", enabled=True) is None


def test_a_workspace_turn_is_never_re_routed():
    """A mastery turn keeps its tutor loop even when it sounds like a quiz ask."""
    assert (
        route_explicit_quiz_request(
            "给我出几道测验题",
            "chat",
            enabled=True,
            workspace_mode="mastery_path",
        )
        is None
    )
    assert (
        route_explicit_quiz_request(
            "generate quiz questions from this chapter",
            "chat",
            enabled=True,
            workspace_mode="immersive_reading",
        )
        is None
    )
    # Ordinary chat is unaffected.
    assert (
        route_explicit_quiz_request("给我出几道测验题", "chat", enabled=True, workspace_mode="")
        is not None
    )
