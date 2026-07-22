"""Tests for oversized event-payload truncation in the session GET response.

Covers ``_truncate_oversized_events`` (introduced via PR #524 and refactored to
operate directly on the store's parsed ``events`` list). The session store
returns each message with an ``events`` list and no ``events_json`` key, so the
helper mutates that list in place.
"""

from deeptutor.api.routers.sessions import (
    _TRUNCATION_NOTICE,
    MAX_EVENT_PAYLOAD,
    _truncate_oversized_events,
)


def _big(n: int) -> str:
    return "x" * n


def test_truncates_oversized_tool_result_content():
    big = _big(MAX_EVENT_PAYLOAD + 100)
    messages = [{"events": [{"type": "tool_result", "content": big}]}]

    _truncate_oversized_events(messages)

    event = messages[0]["events"][0]
    assert len(event["content"]) == MAX_EVENT_PAYLOAD + len(_TRUNCATION_NOTICE)
    assert event["content"].endswith(_TRUNCATION_NOTICE)
    assert event["_truncated"] is True


def test_truncates_nested_tool_metadata_fields():
    big = _big(MAX_EVENT_PAYLOAD + 1)
    messages = [
        {
            "events": [
                {
                    "type": "observation",
                    "content": "short",
                    "metadata": {"tool_metadata": {"content": big, "answer": big}},
                }
            ]
        }
    ]

    _truncate_oversized_events(messages)

    tm = messages[0]["events"][0]["metadata"]["tool_metadata"]
    assert tm["content"].endswith(_TRUNCATION_NOTICE)
    assert tm["answer"].endswith(_TRUNCATION_NOTICE)
    assert messages[0]["events"][0]["_truncated"] is True
    # Untouched short top-level content stays intact.
    assert messages[0]["events"][0]["content"] == "short"


def test_small_payloads_are_left_untouched():
    messages = [
        {"events": [{"type": "tool_result", "content": "tiny"}]},
        {"events": [{"type": "thinking", "content": _big(MAX_EVENT_PAYLOAD + 5)}]},
    ]

    _truncate_oversized_events(messages)

    # Small payload unchanged, no truncation marker added.
    assert messages[0]["events"][0]["content"] == "tiny"
    assert "_truncated" not in messages[0]["events"][0]
    # Non-truncatable event type left alone even when oversized.
    assert "_truncated" not in messages[1]["events"][0]
    assert len(messages[1]["events"][0]["content"]) == MAX_EVENT_PAYLOAD + 5


def test_handles_messages_without_events_or_malformed_events():
    messages = [
        {"role": "user", "content": "hi"},  # no events key
        {"events": None},
        {"events": "not-a-list"},
        {"events": ["not-a-dict", {"type": "tool_result"}]},  # missing content
    ]

    # Must not raise.
    _truncate_oversized_events(messages)

    # Event with no content gains no spurious content key.
    assert "content" not in messages[3]["events"][1]
