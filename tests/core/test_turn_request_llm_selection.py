"""The turn-contract LLMSelection: IDs plus the #641 reasoning-effort override."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.core.turn_request import LLMSelection, TurnRequest


def test_two_id_selection_stays_valid() -> None:
    selection = LLMSelection.model_validate({"profile_id": "profile", "model_id": "model"})

    assert selection.profile_id == "profile"
    assert selection.model_id == "model"
    assert selection.reasoning_effort is None


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_reasoning_effort_accepts_the_service_vocabulary(effort: str) -> None:
    selection = LLMSelection.model_validate(
        {"profile_id": "profile", "model_id": "model", "reasoning_effort": effort}
    )

    assert selection.reasoning_effort == effort


def test_reasoning_effort_normalizes_like_the_service_layer() -> None:
    selection = LLMSelection.model_validate(
        {"profile_id": "profile", "model_id": "model", "reasoning_effort": "  High  "}
    )

    assert selection.reasoning_effort == "high"
    blank = LLMSelection.model_validate(
        {"profile_id": "profile", "model_id": "model", "reasoning_effort": "  "}
    )
    assert blank.reasoning_effort is None


def test_reasoning_effort_rejects_values_outside_the_vocabulary() -> None:
    with pytest.raises(ValidationError, match="reasoning_effort"):
        LLMSelection.model_validate(
            {"profile_id": "profile", "model_id": "model", "reasoning_effort": "ludicrous"}
        )


def test_unknown_keys_are_still_forbidden() -> None:
    with pytest.raises(ValidationError):
        LLMSelection.model_validate(
            {"profile_id": "profile", "model_id": "model", "surprise": True}
        )


def test_turn_request_carries_the_override_into_the_execution_payload() -> None:
    request = TurnRequest.model_validate(
        {
            "content": "hello",
            "llm_selection": {
                "profile_id": "profile",
                "model_id": "model",
                "reasoning_effort": "low",
            },
        }
    )

    assert request.to_payload()["llm_selection"] == {
        "profile_id": "profile",
        "model_id": "model",
        "reasoning_effort": "low",
    }


def test_turn_request_payload_omits_absent_override() -> None:
    request = TurnRequest.model_validate(
        {"content": "hello", "llm_selection": {"profile_id": "profile", "model_id": "model"}}
    )

    assert request.to_payload()["llm_selection"] == {
        "profile_id": "profile",
        "model_id": "model",
    }
