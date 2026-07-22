from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.services.memory import paths, store
from deeptutor.services.memory.store import (
    MemoryStore,
    migrate_partner_surface_if_needed,
    migrate_v1_if_needed,
)
from deeptutor.services.memory.trace import TraceEvent


@pytest.fixture
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``paths.memory_root`` at an isolated tmp dir."""
    root = tmp_path / "memory"
    monkeypatch.setattr(paths, "memory_root", lambda: root)
    paths.ensure_dirs()
    # Reset the singleton so each test gets a fresh store with its own locks.
    monkeypatch.setattr(store, "_singleton", None)
    return root


def _run(coro):
    return asyncio.run(coro)


def test_read_l3_concat_empty(tmp_memory: Path) -> None:
    s = MemoryStore()
    out = s.read_l3_concat()
    assert "(No memory available" in out


def test_read_l3_concat_joins_present_slots(tmp_memory: Path) -> None:
    (tmp_memory / "L3" / "profile.md").write_text("# User profile\n\n## Identity\n- (none)\n")
    (tmp_memory / "L3" / "preferences.md").write_text("# Preferences\n\n## Style\n- terse\n")
    out = MemoryStore().read_l3_concat()
    assert "# User profile" in out
    assert "# Preferences" in out
    assert "---" in out
    # No "no memory" sentinel when something is present.
    assert "(No memory available" not in out


def test_overwrite_and_read_doc_roundtrip(tmp_memory: Path) -> None:
    s = MemoryStore()
    md = (
        "# Chat memory\n\n"
        "## Misconceptions\n"
        "- Misreads quantifier order[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]\n\n"
        "---\n\n"
        "[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]: chat:01HZK4AAAAAAAAAAAAAAAAAAAA\n"
    )
    _run(s.overwrite_doc("L2", "chat", md))
    doc = s.read_doc("L2", "chat")
    assert doc.title == "Chat memory"
    assert len(doc.all_entries()) == 1


def test_delete_entry_removes_from_persisted_doc(tmp_memory: Path) -> None:
    s = MemoryStore()
    md = (
        "# Chat memory\n\n"
        "## Misconceptions\n"
        "- A[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]\n"
        "- B[^m_01HZK5ABCDEFGHJKMNPQRSTVWX]\n\n"
        "---\n\n"
        "[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]: chat:01HZK4AAAAAAAAAAAAAAAAAAAA\n"
        "[^m_01HZK5ABCDEFGHJKMNPQRSTVWX]: chat:01HZK5BBBBBBBBBBBBBBBBBBBB\n"
    )
    _run(s.overwrite_doc("L2", "chat", md))
    ok = _run(s.delete_entry("L2", "chat", "m_01HZK4ABCDEFGHJKMNPQRSTVWX"))
    assert ok
    doc = s.read_doc("L2", "chat")
    assert len(doc.all_entries()) == 1
    assert doc.all_entries()[0].id == "m_01HZK5ABCDEFGHJKMNPQRSTVWX"


def test_write_preference_add(tmp_memory: Path) -> None:
    s = MemoryStore()
    report = _run(
        s.write_preference(
            op="add",
            text="prefers concise answers",
            trace_id="chat:01HZK4AAAAAAAAAAAAAAAAAAAA",
        )
    )
    assert report.accepted
    doc = s.read_doc("L3", "preferences")
    assert len(doc.all_entries()) == 1
    assert doc.all_entries()[0].text == "prefers concise answers"


def test_write_preference_edit(tmp_memory: Path) -> None:
    s = MemoryStore()
    add_report = _run(
        s.write_preference(
            op="add",
            text="prefers concise",
            trace_id="chat:01HZK4AAAAAAAAAAAAAAAAAAAA",
        )
    )
    new_id = add_report.results[0].entry_id
    assert new_id

    edit_report = _run(
        s.write_preference(
            op="edit",
            text="prefers concise but with examples",
            target_id=new_id,
            trace_id="chat:01HZK5BBBBBBBBBBBBBBBBBBBB",
        )
    )
    assert edit_report.accepted
    doc = s.read_doc("L3", "preferences")
    entry = doc.find(new_id)
    assert entry is not None
    assert entry.text == "prefers concise but with examples"
    assert entry.refs == ["chat:01HZK5BBBBBBBBBBBBBBBBBBBB"]


def test_write_preference_edit_without_target_fails(tmp_memory: Path) -> None:
    report = _run(
        MemoryStore().write_preference(
            op="edit",
            text="x",
            trace_id="chat:01HZK4AAAAAAAAAAAAAAAAAAAA",
        )
    )
    assert not report.accepted
    assert "target_id" in report.reason


def test_update_l3_rejects_preferences_slot(tmp_memory: Path) -> None:
    with pytest.raises(ValueError, match="preferences.md is not auto-consolidated"):
        _run(MemoryStore().update_l3("preferences"))


def test_emit_appends_trace_event(tmp_memory: Path) -> None:
    event = TraceEvent.new(
        "chat",
        "turn",
        {"user": "hi", "assistant": "hello"},
        session_id="sess_1",
    )
    _run(MemoryStore().emit(event))
    files = list((tmp_memory / "trace" / "chat").glob("*.jsonl"))
    assert len(files) == 1
    contents = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 1
    assert "sess_1" in contents[0]


def test_overview_reports_all_layers(tmp_memory: Path) -> None:
    rows = MemoryStore().overview()
    keys = {(r.layer, r.key) for r in rows}
    for surface in paths.SURFACES:
        assert ("L2", surface) in keys
    for slot in paths.L3_SLOTS:
        assert ("L3", slot) in keys
    # All start as exists=False, entry_count=0.
    for r in rows:
        assert not r.exists
        assert r.entry_count == 0


def test_migrate_v1_moves_loose_files(tmp_memory: Path) -> None:
    (tmp_memory / "PROFILE.md").write_text("v1 profile content")
    (tmp_memory / "SUMMARY.md").write_text("v1 summary content")
    (tmp_memory / "stray.md").write_text("untracked")

    backup = migrate_v1_if_needed()
    assert backup is not None
    assert backup.parent == tmp_memory / "backup"
    assert (backup / "PROFILE.md").read_text() == "v1 profile content"
    assert (backup / "SUMMARY.md").read_text() == "v1 summary content"
    assert (backup / "stray.md").read_text() == "untracked"
    assert not (tmp_memory / "PROFILE.md").exists()
    assert not (tmp_memory / "SUMMARY.md").exists()


def test_migrate_v1_noop_when_clean(tmp_memory: Path) -> None:
    # Only v2 dirs present; nothing to migrate.
    assert migrate_v1_if_needed() is None
    assert not (tmp_memory / "backup").exists()


def test_migrate_v1_preserves_v2_dirs(tmp_memory: Path) -> None:
    (tmp_memory / "PROFILE.md").write_text("v1")
    # Pre-existing v2 doc — must not be moved.
    l2_chat = tmp_memory / "L2" / "chat.md"
    l2_chat.write_text("# v2 doc\n")

    backup = migrate_v1_if_needed()
    assert backup is not None
    assert l2_chat.exists()
    assert l2_chat.read_text() == "# v2 doc\n"
    assert (backup / "PROFILE.md").exists()


def test_migrate_partner_surface_renames_artifacts(tmp_memory: Path) -> None:
    import json

    l2 = tmp_memory / "L2"
    (l2 / "tutorbot.md").write_text(
        "# Tutorbot memory\n\n"
        "## Themes\n"
        "- Engages with a tutorbot named Frank[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]\n\n"
        "---\n\n"
        "[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]: tutorbot:frank:web_s1\n",
        encoding="utf-8",
    )
    (l2 / "tutorbot.meta.json").write_text(
        json.dumps({"seen_entity_refs": ["tutorbot:frank:web_s1"]}), encoding="utf-8"
    )
    (tmp_memory / "snapshot" / "tutorbot").mkdir(parents=True)
    (tmp_memory / "snapshot" / "tutorbot" / "state.json").write_text("{}", encoding="utf-8")
    (tmp_memory / "trace" / "tutorbot").mkdir(parents=True, exist_ok=True)
    (tmp_memory / "L3").mkdir(exist_ok=True)
    (tmp_memory / "L3" / "profile.meta.json").write_text(
        json.dumps({"seen_l2_entry_ids": {"tutorbot": ["m_01HZK4ABCDEFGHJKMNPQRSTVWX"]}}),
        encoding="utf-8",
    )

    assert migrate_partner_surface_if_needed() is True

    new_md = l2 / "partner.md"
    assert new_md.exists()
    assert not (l2 / "tutorbot.md").exists()
    text = new_md.read_text(encoding="utf-8")
    # Footnote ref prefix and bare prose word both rewritten.
    assert "partner:frank:web_s1" in text
    assert "a partner named Frank" in text
    assert "tutorbot" not in text.lower()

    meta = json.loads((l2 / "partner.meta.json").read_text(encoding="utf-8"))
    assert meta["seen_entity_refs"] == ["partner:frank:web_s1"]

    assert (tmp_memory / "snapshot" / "partner").is_dir()
    assert not (tmp_memory / "snapshot" / "tutorbot").exists()
    assert (tmp_memory / "trace" / "partner").is_dir()

    l3 = json.loads((tmp_memory / "L3" / "profile.meta.json").read_text(encoding="utf-8"))
    assert "partner" in l3["seen_l2_entry_ids"]
    assert "tutorbot" not in l3["seen_l2_entry_ids"]

    # Idempotent: a second run finds nothing tutorbot-shaped.
    assert migrate_partner_surface_if_needed() is False


def test_migrate_partner_surface_noop_when_clean(tmp_memory: Path) -> None:
    assert migrate_partner_surface_if_needed() is False
