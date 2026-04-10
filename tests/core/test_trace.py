"""Tests for trace helper utilities."""

from __future__ import annotations

from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)


def test_new_call_id_format() -> None:
    """Call IDs start with the prefix and contain a hex suffix."""
    cid = new_call_id("tool")
    assert cid.startswith("tool-")
    # Suffix is 10 hex chars
    suffix = cid.split("-", 1)[1]
    assert len(suffix) == 10
    int(suffix, 16)  # must be valid hex


def test_new_call_id_uniqueness() -> None:
    """Two calls produce different IDs."""
    a = new_call_id()
    b = new_call_id()
    assert a != b


def test_build_trace_metadata_required_fields() -> None:
    """build_trace_metadata always includes the four mandatory keys."""
    meta = build_trace_metadata(
        call_id="c1",
        phase="planning",
        label="Plan step",
        call_kind="llm",
    )
    assert meta["call_id"] == "c1"
    assert meta["phase"] == "planning"
    assert meta["label"] == "Plan step"
    assert meta["call_kind"] == "llm"


def test_build_trace_metadata_optional_fields() -> None:
    """Optional fields appear only when provided."""
    meta = build_trace_metadata(
        call_id="c1",
        phase="p",
        label="l",
        call_kind="k",
        trace_id="t1",
        trace_role="observe",
    )
    assert meta["trace_id"] == "t1"
    assert meta["trace_role"] == "observe"
    assert "trace_group" not in meta  # not provided


def test_build_trace_metadata_extra_kwargs() -> None:
    """Extra keyword arguments are included if not None."""
    meta = build_trace_metadata(
        call_id="c1",
        phase="p",
        label="l",
        call_kind="k",
        custom_field="value",
        none_field=None,
    )
    assert meta["custom_field"] == "value"
    assert "none_field" not in meta


def test_derive_trace_metadata_overrides() -> None:
    """derive_trace_metadata can override selected fields from a base dict."""
    base = {"call_id": "old", "phase": "planning", "label": "old-label", "call_kind": "llm"}
    derived = derive_trace_metadata(base, phase="reasoning", label="new-label")

    assert derived["call_id"] == "old"  # unchanged
    assert derived["phase"] == "reasoning"  # overridden
    assert derived["label"] == "new-label"  # overridden
    assert derived["call_kind"] == "llm"  # unchanged


def test_derive_trace_metadata_from_none_base() -> None:
    """Works with None base (starts fresh)."""
    derived = derive_trace_metadata(None, call_id="c1", phase="p")
    assert derived["call_id"] == "c1"
    assert derived["phase"] == "p"


def test_merge_trace_metadata_both_present() -> None:
    """Extra overrides base when keys collide."""
    result = merge_trace_metadata({"a": 1, "b": 2}, {"b": 3, "c": 4})
    assert result == {"a": 1, "b": 3, "c": 4}


def test_merge_trace_metadata_none_handling() -> None:
    """None args produce empty dicts, not errors."""
    assert merge_trace_metadata(None, None) == {}
    assert merge_trace_metadata({"a": 1}, None) == {"a": 1}
    assert merge_trace_metadata(None, {"b": 2}) == {"b": 2}


def test_new_call_id_default_prefix() -> None:
    """Default prefix to new_call_id is 'call'."""
    cid = new_call_id()
    assert cid.startswith("call-")


def test_build_trace_metadata_with_all_optional_fields() -> None:
    """Verify trace_group and trace_kind exact injection."""
    meta = build_trace_metadata(
        call_id="c1",
        phase="p",
        label="l",
        call_kind="k",
        trace_group="g1",
        trace_kind="agent",
    )
    assert meta["trace_group"] == "g1"
    assert meta["trace_kind"] == "agent"


def test_derive_preserves_extra_from_base() -> None:
    """Custom keys in base that aren't overrides are preserved."""
    base = {"call_id": "c1", "phase": "p", "label": "l", "call_kind": "k", "custom": "stays"}
    derived = derive_trace_metadata(base, phase="new_p")
    assert derived["custom"] == "stays"
    assert derived["phase"] == "new_p"
    assert derived["call_id"] == "c1"

