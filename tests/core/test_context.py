"""Tests for UnifiedContext and Attachment dataclasses."""

from __future__ import annotations

from deeptutor.core.context import Attachment, UnifiedContext


def test_unified_context_defaults_are_safe() -> None:
    """Mutable defaults (lists, dicts) must not leak between instances."""
    ctx_a = UnifiedContext()
    ctx_b = UnifiedContext()

    ctx_a.conversation_history.append({"role": "user", "content": "hi"})
    assert len(ctx_b.conversation_history) == 0, "mutable default leaked between instances"

    ctx_a.knowledge_bases.append("kb-1")
    assert len(ctx_b.knowledge_bases) == 0

    ctx_a.config_overrides["temp"] = 0.5
    assert "temp" not in ctx_b.config_overrides


def test_attachment_fields() -> None:
    """Attachment stores all expected fields."""
    att = Attachment(
        type="image",
        url="https://example.com/img.png",
        base64="abc123",
        filename="img.png",
        mime_type="image/png",
    )
    assert att.type == "image"
    assert att.url == "https://example.com/img.png"
    assert att.base64 == "abc123"
    assert att.filename == "img.png"
    assert att.mime_type == "image/png"


def test_enabled_tools_none_vs_empty_list() -> None:
    """None means 'not specified'; [] means 'explicitly disable all tools'."""
    ctx_default = UnifiedContext()
    assert ctx_default.enabled_tools is None, "default should be None (unspecified)"

    ctx_empty = UnifiedContext(enabled_tools=[])
    assert ctx_empty.enabled_tools == [], "explicit empty list should be preserved"


def test_unified_context_full_construction() -> None:
    """All fields can be set during construction."""
    ctx = UnifiedContext(
        session_id="s1",
        user_message="hello",
        conversation_history=[{"role": "user", "content": "hello"}],
        enabled_tools=["rag"],
        active_capability="chat",
        knowledge_bases=["kb1"],
        attachments=[Attachment(type="file", filename="doc.pdf")],
        config_overrides={"temperature": 0.5},
        language="zh",
        notebook_context="notebook",
        history_context="history",
        memory_context="memory",
        metadata={"extra": True},
    )
    assert ctx.session_id == "s1"
    assert ctx.user_message == "hello"
    assert ctx.active_capability == "chat"
    assert ctx.language == "zh"
    assert len(ctx.attachments) == 1
    assert ctx.metadata["extra"] is True


def test_attachment_defaults() -> None:
    """Attachment fields should default to empty strings."""
    att = Attachment(type="pdf")
    assert att.url == ""
    assert att.base64 == ""
    assert att.filename == ""
    assert att.mime_type == ""


def test_language_default_is_english() -> None:
    """Context language defaults to 'en'."""
    ctx = UnifiedContext()
    assert ctx.language == "en"


def test_context_metadata_isolation() -> None:
    """Metadata dict doesn't leak between instances."""
    ctx1 = UnifiedContext()
    ctx2 = UnifiedContext()
    
    ctx1.metadata["flag"] = True
    assert "flag" not in ctx2.metadata

