"""A failed local-agent-SDK turn must always name a reason.

The Claude Code / CodeBuddy SDK backends report failure with
``is_error=True`` and ``finish_reason="error"``, and the CLI only fills
``result`` when the turn produced assistant text. A turn that dies on a
rejected tool call or on ``max_turns`` therefore ended with an empty
``result``, and the operator saw a bare ``"Error calling Claude Code: "``
with nothing after the colon (#2539). These tests pin the reason to
something the reader can act on.
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.sdk_bridge import (
    _consume_messages,
    _result_detail,
)


class _ResultMessage:
    """Mirrors the SDK result message: ``result``, ``is_error``, ``subtype``."""

    def __init__(self, result: str = "", is_error: bool = False, subtype: str = "success"):
        self.result = result
        self.is_error = is_error
        self.subtype = subtype


async def _stream(*messages):
    for message in messages:
        yield message


def _consume(*messages, label: str = "Claude Code"):
    return _consume_messages(_stream(*messages), on_content_delta=None, label=label)


@pytest.mark.asyncio
async def test_empty_error_result_names_the_cli_subtype() -> None:
    response = await _consume(_ResultMessage(result="", is_error=True, subtype="error_max_turns"))

    assert response.finish_reason == "error"
    # The old rendering was exactly "Error calling Claude Code: ".
    assert response.content.startswith("Error calling Claude Code: ")
    assert response.content != "Error calling Claude Code: "
    assert "maximum number of turns" in response.content
    assert "error_max_turns" in response.content


@pytest.mark.asyncio
async def test_unknown_subtype_still_explains_the_empty_turn() -> None:
    response = await _consume(
        _ResultMessage(result="", is_error=True, subtype="error_something_new")
    )

    assert response.content != "Error calling Claude Code: "
    assert "error_something_new" in response.content


@pytest.mark.asyncio
async def test_no_subtype_and_no_text_is_still_not_blank() -> None:
    response = await _consume(_ResultMessage(result="", is_error=True))

    assert response.content != "Error calling Claude Code: "
    assert "without a result" in response.content


@pytest.mark.asyncio
async def test_cli_message_is_kept_ahead_of_the_subtype() -> None:
    response = await _consume(
        _ResultMessage(
            result="No such tool available: write_note",
            is_error=True,
            subtype="error_during_execution",
        )
    )

    # The CLI's own wording stays first; the subtype is added as a hint.
    assert response.content == (
        "Error calling Claude Code: No such tool available: write_note (error_during_execution)"
    )


@pytest.mark.asyncio
async def test_a_successfully_empty_turn_does_not_gain_an_error() -> None:
    response = await _consume(_ResultMessage(result="", is_error=False))

    assert response.finish_reason == "stop"
    assert response.content == ""


def test_result_detail_accepts_plain_dicts_from_the_sdk() -> None:
    assert _result_detail({"is_error": True, "subtype": "error_max_turns", "result": ""}) == (
        "the turn hit its maximum number of turns (error_max_turns)"
    )


def test_successful_subtype_is_not_appended_to_real_text() -> None:
    assert _result_detail(_ResultMessage(result="done", is_error=True, subtype="success")) == "done"


@pytest.mark.asyncio
async def test_codebuddy_label_is_used_in_the_same_shape() -> None:
    response = await _consume(
        _ResultMessage(result="", is_error=True, subtype="error_max_turns"),
        label="CodeBuddy",
    )

    assert response.content.startswith("Error calling CodeBuddy: the turn hit")
