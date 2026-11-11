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
    _error_detail,
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


# --- frames captured from a live claude-agent-sdk 0.2.x run ----------------
#
# ``errors[]`` is where the CLI puts the sentence a human should read, and on
# the turn-limit path ``result`` is *None*. The SDK's own
# ``_error_result_text`` prefers the same field for the same reason, so these
# cases pin our priority order to it.


class _LiveMaxTurnsFrame:
    """Verbatim shape observed from a real ``error_max_turns`` result."""

    subtype = "error_max_turns"
    is_error = True
    result = None
    errors = ["Reached maximum number of turns (1)"]
    api_error_status = None
    terminal_reason = "max_turns"


@pytest.mark.asyncio
async def test_live_max_turns_frame_uses_the_cli_sentence() -> None:
    response = await _consume(_LiveMaxTurnsFrame())

    assert response.finish_reason == "error"
    # The CLI's own prose, not our paraphrase of the subtype.
    assert response.content == ("Error calling Claude Code: Reached maximum number of turns (1)")


def test_errors_list_wins_over_the_result_field() -> None:
    assert (
        _result_detail(
            {
                "subtype": "error_during_execution",
                "is_error": True,
                "result": "generic",
                "errors": ["No such tool available: write_note"],
            }
        )
        == "No such tool available: write_note"
    )


def test_multiple_errors_are_joined() -> None:
    assert (
        _result_detail({"is_error": True, "errors": ["first reason", "second reason"]})
        == "first reason; second reason"
    )


def test_blank_and_non_string_errors_fall_through() -> None:
    assert (
        _result_detail(
            {
                "subtype": "error_max_turns",
                "is_error": True,
                "result": None,
                "errors": ["  ", None, 7],
            }
        )
        == "the turn hit its maximum number of turns (error_max_turns)"
    )


def test_a_bare_string_in_errors_is_tolerated() -> None:
    assert _result_detail({"is_error": True, "errors": "only one reason"}) == "only one reason"


def test_api_failure_keeps_the_result_prose_not_the_success_subtype() -> None:
    """An API failure arrives as ``subtype: "success"`` with prose in ``result``.

    Rendering the subtype there would produce the self-contradictory
    "an error result: success" the SDK itself calls out.
    """
    assert (
        _result_detail(
            {
                "subtype": "success",
                "is_error": True,
                "result": "API Error: 529 overloaded",
                "errors": None,
                "api_error_status": 529,
            }
        )
        == "API Error: 529 overloaded"
    )


def test_http_status_is_the_last_resort_before_giving_up() -> None:
    assert (
        _result_detail(
            {
                "subtype": "success",
                "is_error": True,
                "result": None,
                "errors": [],
                "api_error_status": 429,
            }
        )
        == "the provider API call failed (HTTP 429)"
    )


# --- rejected tool calls must survive as turn-failure evidence -------------
#
# When the CLI rejects a tool call the model made, the rejection only
# surfaces as an error ``tool_result`` block on a user message. A turn that
# dies right afterwards (``max_turns``) must still name it, after the CLI's
# own fields (#2539).

_REJECTED_TOOL_RESULT_MESSAGE = {
    "type": "user",
    "message": {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "is_error": True,
                "content": "Error: No such tool available: write_note",
            },
            {
                "type": "tool_result",
                "tool_use_id": "toolu_2",
                "content": "<tool_use_error>No such tool available: search_notes</tool_use_error>",
            },
        ],
    },
}


@pytest.mark.asyncio
async def test_rejected_tool_evidence_is_appended_to_the_cli_reason() -> None:
    response = await _consume(
        _REJECTED_TOOL_RESULT_MESSAGE,
        _LiveMaxTurnsFrame(),
    )

    assert response.finish_reason == "error"
    # The CLI's own prose leads…
    assert response.content.startswith(
        "Error calling Claude Code: Reached maximum number of turns (1)"
    )
    # …and both rejections follow as evidence.
    assert "rejected tool call: Error: No such tool available: write_note" in response.content
    assert "rejected tool call: No such tool available: search_notes" in response.content


@pytest.mark.asyncio
async def test_rejection_not_repeated_when_the_cli_already_reported_it() -> None:
    frame = _ResultMessage(result="", is_error=True, subtype="error_during_execution")
    frame.errors = ["No such tool available: write_note"]

    response = await _consume(_REJECTED_TOOL_RESULT_MESSAGE, frame)

    assert response.content.count("write_note") == 1


@pytest.mark.asyncio
async def test_rejection_evidence_alone_names_the_unavailable_tool() -> None:
    """No ``errors[]``, no ``result``: the subtype plus the rejections speak."""
    response = await _consume(
        _REJECTED_TOOL_RESULT_MESSAGE,
        _ResultMessage(result="", is_error=True, subtype="error_max_turns"),
    )

    assert response.finish_reason == "error"
    assert "maximum number of turns" in response.content
    assert "No such tool available: write_note" in response.content


@pytest.mark.asyncio
async def test_codebuddy_label_wraps_rejection_evidence_the_same_way() -> None:
    response = await _consume(
        _REJECTED_TOOL_RESULT_MESSAGE,
        _ResultMessage(result="", is_error=True, subtype="error_during_execution"),
        label="CodeBuddy",
    )

    assert response.content.startswith("Error calling CodeBuddy: the CLI reported an error")
    assert "No such tool available: write_note" in response.content


def test_error_detail_appends_only_new_rejections() -> None:
    frame = {"is_error": True, "subtype": "error_max_turns", "result": "", "errors": []}

    assert _error_detail(frame, ["Error: No such tool available: write_note"]) == (
        "the turn hit its maximum number of turns (error_max_turns); "
        "rejected tool call: Error: No such tool available: write_note"
    )
    # Already-covered evidence and blank entries add nothing.
    assert _error_detail(frame, ["", "error_max_turns"]) == (
        "the turn hit its maximum number of turns (error_max_turns)"
    )


def test_a_short_cli_reason_never_swallows_the_rejection() -> None:
    """Dedup runs one way: evidence in the detail is redundant, not vice versa.

    ``errors[]`` sometimes carries a stub ("Error") rather than the sentence.
    Comparing the detail against the rejection as well would read that stub as
    "already reported" and drop the only mention of the refused tool — the
    exact silence #2539 is about.
    """
    frame = {
        "is_error": True,
        "subtype": "error_during_execution",
        "result": None,
        "errors": ["Error"],
    }

    detail = _error_detail(frame, ["Error: No such tool available: write_note"])

    assert "No such tool available: write_note" in detail
    assert detail.startswith("Error; rejected tool call:")


def test_the_wrapped_rejection_is_still_recognised_as_the_same_fact() -> None:
    """The ``Error: `` prefix the CLI wraps around a sentence is not new evidence."""
    frame = {
        "is_error": True,
        "subtype": "error_max_turns",
        "result": None,
        "errors": ["No such tool available: write_note"],
    }

    assert _error_detail(frame, ["Error: No such tool available: write_note"]) == (
        "No such tool available: write_note"
    )
