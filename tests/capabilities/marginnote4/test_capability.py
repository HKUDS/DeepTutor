"""Tests for the MarginNote 4 capability: binding, hooks, exclusivity."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.capabilities import any_exclusive_capability_active
from deeptutor.capabilities.marginnote4 import (
    MARGINNOTE_TOOL_NAMES,
    MarginNoteCapability,
)
from deeptutor.capabilities.marginnote4 import binding as mn4_binding
from deeptutor.core.context import UnifiedContext


def _bind(monkeypatch, db_path: str, name: str = "mylibrary") -> None:
    """Make resolve_kb_metadata report ``name`` as a marginnote4 KB."""
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
        lambda ref: (
            {"name": ref, "type": "marginnote4", "db_path": db_path}
            if ref == name
            else {"name": ref, "type": None}
        ),
    )


def test_capability_inactive_without_mn4_kb(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path / "test.db"))
    cap = MarginNoteCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert cap.is_active(ctx) is False
    assert cap.system_block(ctx, language="en", prompts={}) is None


def test_capability_active_injects_db_path(monkeypatch, tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _bind(monkeypatch, db_path)
    cap = MarginNoteCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["mylibrary"])
    assert cap.is_active(ctx) is True
    assert tuple(cap.owned_tools) == MARGINNOTE_TOOL_NAMES
    # db_path injected for marginnote tools, even overwriting a forged value
    assert cap.augment_kwargs("marginnote_read", {}, ctx)["_db_path"] == db_path
    assert cap.augment_kwargs("marginnote_read", {"_db_path": "/etc"}, ctx)["_db_path"] == db_path
    # but never for a non-marginnote tool
    assert "_db_path" not in cap.augment_kwargs("rag", {}, ctx)


def test_system_block_contains_library_name(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path / "test.db"))
    cap = MarginNoteCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["mylibrary"])
    block = cap.system_block(ctx, language="en", prompts={})
    assert block is not None
    assert "mylibrary" in block.content


def test_system_block_zh(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path / "test.db"))
    cap = MarginNoteCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["mylibrary"])
    block = cap.system_block(ctx, language="zh", prompts={})
    assert block is not None


def test_binding_resolved_once_and_cached(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake(ref):
        calls["n"] += 1
        return {"name": ref, "type": "marginnote4", "db_path": str(tmp_path / "x.db")}

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake)
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["lib"])
    mn4_binding.marginnote_binding(ctx)
    mn4_binding.marginnote_binding(ctx)
    assert calls["n"] == 1  # cached after first resolution


def test_owned_kbs_reports_only_mn4_refs(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path / "test.db"))
    cap = MarginNoteCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["mylibrary", "kb-plain"])
    assert cap.owned_kbs(ctx) == {"mylibrary"}


def test_kb_refs_enumerates_every_selected_library(monkeypatch, tmp_path: Path) -> None:
    def fake(ref):
        if ref in {"libA", "libB"}:
            return {"name": ref, "type": "marginnote4", "db_path": str(tmp_path / "x.db")}
        return {"name": ref, "type": None}

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake)
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["libA", "kb1", "libB"])
    assert mn4_binding.marginnote_kb_refs(ctx) == {"libA", "libB"}


def test_exclusive_flag_replaces_tool_surface(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path / "test.db"))
    mn4_turn = UnifiedContext(user_message="hi", knowledge_bases=["mylibrary"])
    plain_turn = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert any_exclusive_capability_active(mn4_turn) is True
    assert any_exclusive_capability_active(plain_turn) is False
