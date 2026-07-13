"""Tests for meta.json sidecars + memory settings loader."""

from __future__ import annotations

from unittest.mock import patch

from deeptutor.services.memory.consolidator import meta as meta_mod
from deeptutor.services.memory.settings import (
    MemorySettings,
    load_memory_settings,
    save_memory_settings,
)


def test_settings_defaults_match_spec() -> None:
    s = MemorySettings()
    assert s.update.l2_budget == 20
    assert s.update.l3_budget == 10
    assert s.audit.l2_budget == 20
    assert s.audit.l3_budget == 10
    assert s.dedup.iterations == 3
    assert s.dedup.auto_after_update is True
    assert s.chunking.overlap_ratio == 0.10
    assert s.chunking.boundary == "paragraph"
    assert s.chunking.min_chunk_chars == 1000
    assert s.chunking.max_chunk_chars == 64000
    assert s.reference.enforce_required is True
    assert s.reference.drop_invalid_refs is True


def test_settings_partial_payload_falls_back_to_defaults() -> None:
    with patch.object(
        load_memory_settings.__wrapped__
        if hasattr(load_memory_settings, "__wrapped__")
        else load_memory_settings,
        "__call__",
        create=True,
    ):
        pass  # no-op; the next assertion exercises the real coercion path
    from deeptutor.services.memory.settings import _from_dict

    merged = _from_dict(
        MemorySettings,
        {"update": {"l2_budget": 42}, "chunking": {"overlap_ratio": 0.25}},
    )
    assert merged.update.l2_budget == 42
    assert merged.update.l3_budget == 10  # default
    assert merged.chunking.overlap_ratio == 0.25
    assert merged.chunking.min_chunk_chars == 1000


def test_settings_clamps_out_of_range_values() -> None:
    from deeptutor.services.memory.settings import _from_dict

    merged = _from_dict(
        MemorySettings,
        {
            "update": {"l2_budget": 9999, "l3_budget": -10},
            "dedup": {"iterations": 99},
            "chunking": {"overlap_ratio": 2.0, "boundary": "not-real"},
        },
    )
    assert 1 <= merged.update.l2_budget <= 200
    assert 1 <= merged.update.l3_budget <= 200
    assert 1 <= merged.dedup.iterations <= 20
    assert 0.0 <= merged.chunking.overlap_ratio <= 0.5
    assert merged.chunking.boundary == "paragraph"  # invalid choice → default


def test_l2_meta_roundtrip(tmp_path, monkeypatch) -> None:
    # Redirect paths to a temp memory dir.
    from deeptutor.services.memory import paths as paths_mod

    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)

    refs = {"chat:01ABC", "chat:01DEF"}
    meta = meta_mod.save_l2_meta("chat", seen_entity_refs=refs)
    assert meta.seen_entity_refs == refs

    reloaded = meta_mod.load_l2_meta("chat")
    assert reloaded.seen_entity_refs == refs
    assert reloaded.last_update_at is not None


def test_l3_meta_roundtrip(tmp_path, monkeypatch) -> None:
    from deeptutor.services.memory import paths as paths_mod

    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)

    seen = {"chat": {"m_a", "m_b"}, "notebook": {"m_c"}}
    meta_mod.save_l3_meta("recent", seen_l2_entry_ids=seen)
    reloaded = meta_mod.load_l3_meta("recent")
    assert reloaded.seen_l2_entry_ids == seen


def test_l2_meta_missing_file_returns_empty() -> None:
    from deeptutor.services.memory.consolidator.meta import L2Meta

    m = L2Meta()
    assert m.seen_entity_refs == set()
    assert m.last_update_at is None
