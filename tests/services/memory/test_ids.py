from __future__ import annotations

import time

from deeptutor.services.memory.ids import (
    is_entry_id,
    is_shortname_ref,
    is_trace_id,
    is_valid_ref,
    new_entry_id,
    new_trace_id,
    new_ulid,
)


def test_ulid_length_and_charset() -> None:
    u = new_ulid()
    assert len(u) == 26
    assert all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in u)


def test_ulid_monotonic_within_window() -> None:
    # Within a few ms the timestamp prefix should sort consistently.
    first = new_ulid()
    time.sleep(0.005)
    second = new_ulid()
    assert first[:10] <= second[:10]


def test_entry_id_shape_and_validation() -> None:
    eid = new_entry_id()
    assert eid.startswith("m_")
    assert is_entry_id(eid)
    assert not is_trace_id(eid)


def test_trace_id_shape_and_validation() -> None:
    tid = new_trace_id("chat")
    assert tid.startswith("chat:")
    assert is_trace_id(tid)
    assert not is_entry_id(tid)


def test_invalid_ids_rejected() -> None:
    assert not is_entry_id("m_short")
    assert not is_entry_id("foo")
    assert not is_entry_id("")
    assert not is_trace_id("01HZK4ABCDEFGHJKMNPQRSTVWX")  # missing surface prefix
    assert not is_trace_id("CHAT:01HZK4ABCDEFGHJKMNPQRSTVWX")  # uppercase surface


def test_uniqueness_across_calls() -> None:
    ids = {new_ulid() for _ in range(1000)}
    assert len(ids) == 1000


def test_shortname_ref_accepts_known_surfaces() -> None:
    """L3 refs are bare surface names. Whitelisted (not a loose regex)
    so an LLM hallucination like ``not-an-id`` doesn't sneak through."""
    for surface in ("chat", "notebook", "quiz", "kb", "book", "partner", "cowriter"):
        assert is_shortname_ref(surface), surface
    # is_valid_ref must accept the new form so the ops validator does too.
    assert is_valid_ref("chat")


def test_shortname_ref_rejects_unknown_tokens() -> None:
    assert not is_shortname_ref("CHAT")
    assert not is_shortname_ref("not-an-id")
    assert not is_shortname_ref("")
    assert not is_shortname_ref("co-writer")  # the actual surface is ``cowriter``
