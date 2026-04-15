"""Tests for UnifiedContext, Attachment, StreamEvent, and trace helpers."""

from __future__ import annotations

from deeptutor.core.context import Attachment, UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.errors import (
    ConfigurationError,
    DeepTutorError,
    EnvironmentConfigError,
    LLMContextError,
    LLMServiceError,
    ServiceError,
    ValidationError,
)
from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------


class TestAttachment:
    def test_default_fields(self) -> None:
        att = Attachment(type="image")
        assert att.type == "image"
        assert att.url == ""
        assert att.base64 == ""
        assert att.filename == ""
        assert att.mime_type == ""

    def test_full_construction(self) -> None:
        att = Attachment(
            type="pdf",
            url="https://example.com/doc.pdf",
            filename="doc.pdf",
            mime_type="application/pdf",
        )
        assert att.type == "pdf"
        assert att.filename == "doc.pdf"


# ---------------------------------------------------------------------------
# UnifiedContext
# ---------------------------------------------------------------------------


class TestUnifiedContext:
    def test_defaults(self) -> None:
        ctx = UnifiedContext()
        assert ctx.session_id == ""
        assert ctx.user_message == ""
        assert ctx.conversation_history == []
        assert ctx.enabled_tools is None
        assert ctx.active_capability is None
        assert ctx.knowledge_bases == []
        assert ctx.attachments == []
        assert ctx.config_overrides == {}
        assert ctx.language == "en"
        assert ctx.notebook_context == ""
        assert ctx.history_context == ""
        assert ctx.memory_context == ""
        assert ctx.metadata == {}

    def test_mutable_defaults_are_independent(self) -> None:
        ctx_a = UnifiedContext()
        ctx_b = UnifiedContext()
        ctx_a.conversation_history.append({"role": "user", "content": "hi"})
        assert ctx_b.conversation_history == []

    def test_full_construction(self) -> None:
        att = Attachment(type="image", url="https://img.png")
        ctx = UnifiedContext(
            session_id="s1",
            user_message="hello",
            conversation_history=[{"role": "user", "content": "hi"}],
            enabled_tools=["rag", "web_search"],
            active_capability="deep_solve",
            knowledge_bases=["kb1"],
            attachments=[att],
            config_overrides={"temperature": 0.5},
            language="zh",
            notebook_context="some notes",
            history_context="prior session",
            memory_context="user preference",
            metadata={"turn_id": "t1"},
        )
        assert ctx.session_id == "s1"
        assert ctx.active_capability == "deep_solve"
        assert len(ctx.attachments) == 1
        assert ctx.attachments[0].type == "image"
        assert ctx.language == "zh"

    def test_enabled_tools_none_vs_empty(self) -> None:
        """None means 'not specified', [] means 'explicitly disable all'."""
        ctx_none = UnifiedContext(enabled_tools=None)
        ctx_empty = UnifiedContext(enabled_tools=[])
        assert ctx_none.enabled_tools is None
        assert ctx_empty.enabled_tools == []


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------


class TestStreamEvent:
    def test_defaults(self) -> None:
        event = StreamEvent(type=StreamEventType.CONTENT)
        assert event.source == ""
        assert event.stage == ""
        assert event.content == ""
        assert event.metadata == {}
        assert event.session_id == ""
        assert event.turn_id == ""
        assert event.seq == 0
        assert isinstance(event.timestamp, float)

    def test_to_dict(self) -> None:
        event = StreamEvent(
            type=StreamEventType.TOOL_CALL,
            source="chat",
            stage="responding",
            content="web_search",
            metadata={"args": {"q": "test"}},
        )
        d = event.to_dict()
        assert d["type"] == "tool_call"
        assert d["source"] == "chat"
        assert d["metadata"]["args"]["q"] == "test"

    def test_all_event_types_have_string_values(self) -> None:
        for member in StreamEventType:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TestErrors:
    def test_base_error_str_without_details(self) -> None:
        err = DeepTutorError("boom")
        assert str(err) == "boom"
        assert err.details == {}

    def test_base_error_str_with_details(self) -> None:
        err = DeepTutorError("boom", details={"key": "val"})
        assert "key" in str(err)

    def test_hierarchy(self) -> None:
        assert issubclass(ConfigurationError, DeepTutorError)
        assert issubclass(ValidationError, DeepTutorError)
        assert issubclass(ServiceError, DeepTutorError)
        assert issubclass(LLMServiceError, ServiceError)
        assert issubclass(LLMContextError, LLMServiceError)
        assert issubclass(EnvironmentConfigError, ConfigurationError)


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------


class TestTrace:
    def test_new_call_id_prefix(self) -> None:
        cid = new_call_id("solver")
        assert cid.startswith("solver-")
        assert len(cid) == len("solver-") + 10

    def test_new_call_ids_are_unique(self) -> None:
        ids = {new_call_id() for _ in range(100)}
        assert len(ids) == 100

    def test_build_trace_metadata(self) -> None:
        meta = build_trace_metadata(
            call_id="c1",
            phase="plan",
            label="Plan step",
            call_kind="llm_reasoning",
            trace_id="session-1",
        )
        assert meta["call_id"] == "c1"
        assert meta["phase"] == "plan"
        assert meta["trace_id"] == "session-1"
        assert "trace_role" not in meta  # omitted when None

    def test_derive_trace_metadata_overrides(self) -> None:
        base = {"call_id": "c1", "phase": "plan", "label": "X", "call_kind": "llm"}
        derived = derive_trace_metadata(base, phase="solve", label="Y")
        assert derived["phase"] == "solve"
        assert derived["label"] == "Y"
        assert derived["call_id"] == "c1"  # unchanged

    def test_merge_trace_metadata(self) -> None:
        merged = merge_trace_metadata({"a": 1}, {"b": 2, "a": 3})
        assert merged == {"a": 3, "b": 2}

    def test_merge_trace_metadata_handles_none(self) -> None:
        assert merge_trace_metadata(None, None) == {}
        assert merge_trace_metadata({"x": 1}, None) == {"x": 1}
