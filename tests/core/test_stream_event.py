"""Tests for StreamEvent and StreamEventType."""

from __future__ import annotations

from deeptutor.core.stream import StreamEvent, StreamEventType


def test_event_type_values_are_stable() -> None:
    """Guard against accidental enum value changes that would break serialization."""
    expected = {
        "stage_start": StreamEventType.STAGE_START,
        "stage_end": StreamEventType.STAGE_END,
        "thinking": StreamEventType.THINKING,
        "observation": StreamEventType.OBSERVATION,
        "content": StreamEventType.CONTENT,
        "tool_call": StreamEventType.TOOL_CALL,
        "tool_result": StreamEventType.TOOL_RESULT,
        "progress": StreamEventType.PROGRESS,
        "sources": StreamEventType.SOURCES,
        "result": StreamEventType.RESULT,
        "error": StreamEventType.ERROR,
        "session": StreamEventType.SESSION,
        "done": StreamEventType.DONE,
    }
    for value, member in expected.items():
        assert member.value == value, f"{member.name} should be '{value}', got '{member.value}'"


def test_to_dict_includes_all_fields() -> None:
    """to_dict() must include every field the consumers rely on."""
    event = StreamEvent(
        type=StreamEventType.CONTENT,
        source="chat",
        stage="responding",
        content="text",
        metadata={"k": "v"},
        session_id="s1",
        turn_id="t1",
        seq=42,
    )
    d = event.to_dict()

    assert d["type"] == "content"
    assert d["source"] == "chat"
    assert d["stage"] == "responding"
    assert d["content"] == "text"
    assert d["metadata"] == {"k": "v"}
    assert d["session_id"] == "s1"
    assert d["turn_id"] == "t1"
    assert d["seq"] == 42
    assert "timestamp" in d


def test_default_timestamp_is_set() -> None:
    """A freshly created event should have a non-zero timestamp."""
    event = StreamEvent(type=StreamEventType.DONE)
    assert event.timestamp > 0


def test_event_type_is_str_enum() -> None:
    """StreamEventType should inherently behave as strings."""
    assert isinstance(StreamEventType.CONTENT, str)
    assert StreamEventType.CONTENT == "content"


def test_to_dict_metadata_default_is_empty_dict() -> None:
    """to_dict() must return empty dict for metadata if unset."""
    event = StreamEvent(type=StreamEventType.SESSION)
    d = event.to_dict()
    assert d["metadata"] == {}


def test_event_instances_have_independent_metadata() -> None:
    """Mutable defaults don't leak across event instances."""
    e1 = StreamEvent(type=StreamEventType.CONTENT)
    e2 = StreamEvent(type=StreamEventType.CONTENT)
    
    e1.metadata["test"] = 123
    assert "test" not in e2.metadata

