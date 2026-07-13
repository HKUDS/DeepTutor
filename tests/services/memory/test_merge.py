"""Tests for the merge mode (footnote consolidation, no-LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator.modes import merge as merge_mod
from deeptutor.services.memory.document import Document, Entry, parse, serialize


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    yield tmp_path


# A legacy doc: five entries, each citing the same ref. The on-disk file
# has five identical-looking footnote rows that the workbench renders as
# `25. notebook:3a563e6f`, `26. notebook:3a563e6f`, etc.
_LEGACY_DOC_WITH_DUPLICATES = """\
# notebook memory

## Concepts
- understands FSRS scheduling[^m_01HZK1ABCDEFGHJKMNPQRSTVWX]
- understands ε-δ definition[^m_01HZK2ABCDEFGHJKMNPQRSTVWX]
- understands monotone convergence[^m_01HZK3ABCDEFGHJKMNPQRSTVWX]
- understands chain rule[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]
- understands integration by parts[^m_01HZK5ABCDEFGHJKMNPQRSTVWX]

---

[^m_01HZK1ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
[^m_01HZK2ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
[^m_01HZK3ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
[^m_01HZK4ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
[^m_01HZK5ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
"""


@pytest.mark.asyncio
async def test_merge_collapses_duplicate_footnotes(memory_dir):
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_LEGACY_DOC_WITH_DUPLICATES, encoding="utf-8")

    events: list[dict] = []

    async def collect(evt):
        events.append(evt)

    result = await merge_mod.run_merge("L2", "notebook", on_event=collect)

    assert result.rewrote is True
    assert result.footnote_rows_before == 5  # five legacy [^m_xxx]: rows
    assert result.footnote_rows_after == 1  # one unique ref → one footnote

    new_text = target.read_text(encoding="utf-8")
    # The on-disk file is now in the new format — one footnote definition.
    assert new_text.count("[^1]: notebook:3a563e6f") == 1
    assert "[^2]" not in new_text  # no second unique ref
    # All five bullets cite [^1].
    assert new_text.count("[^1]") == 6  # 5 bullets + 1 def
    # Round-trip preserves all five entries with the shared ref.
    doc = parse(new_text)
    assert len(doc.all_entries()) == 5
    for entry in doc.all_entries():
        assert entry.refs == ["notebook:3a563e6f"]

    stages = [e["stage"] for e in events]
    assert "doc_updated" in stages
    done = next(e for e in events if e["stage"] == "done")
    assert done["rewrote"] is True
    assert done["footnote_rows_before"] == 5
    assert done["footnote_rows_after"] == 1


@pytest.mark.asyncio
async def test_merge_is_idempotent_on_already_merged_doc(memory_dir):
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_LEGACY_DOC_WITH_DUPLICATES, encoding="utf-8")

    # First pass migrates legacy → new and consolidates.
    await merge_mod.run_merge("L2", "notebook")
    after_first = target.read_text(encoding="utf-8")

    # Second pass should leave the file byte-equal and skip the checkpoint.
    events: list[dict] = []

    async def collect(evt):
        events.append(evt)

    result = await merge_mod.run_merge("L2", "notebook", on_event=collect)
    assert result.rewrote is False
    assert target.read_text(encoding="utf-8") == after_first
    # No doc_updated emitted on a no-op pass.
    assert "doc_updated" not in {e["stage"] for e in events}


@pytest.mark.asyncio
async def test_merge_no_op_when_doc_missing(memory_dir):
    events: list[dict] = []

    async def collect(evt):
        events.append(evt)

    result = await merge_mod.run_merge("L2", "notebook", on_event=collect)
    assert result.rewrote is False
    assert result.footnote_rows_before == 0
    assert result.footnote_rows_after == 0
    done = next(e for e in events if e["stage"] == "done")
    assert done["no_doc"] is True


@pytest.mark.asyncio
async def test_auto_merge_runs_even_when_update_added_no_facts(memory_dir, monkeypatch):
    """Doc in legacy format gets migrated even on a no-op update.

    This is the bug we hit in the wild: the user presses "Update" on a
    surface with no new L1 entities; ``facts_added`` is 0; the old
    ``if facts_added > 0`` guard meant merge never ran and the legacy
    duplicate footnotes stayed on disk.
    """
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_LEGACY_DOC_WITH_DUPLICATES, encoding="utf-8")

    # No new entities → run_update hits the early-return path.
    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.update.snap.read_snapshot",
        lambda surface: [],
    )

    from deeptutor.services.memory.consolidator.modes import update as update_mod

    result = await update_mod.run_update("L2", "notebook")
    assert result.facts_added == 0
    assert getattr(result, "no_new_input", False) is True

    # ...but the legacy doc was still migrated by auto-merge.
    new_text = target.read_text(encoding="utf-8")
    assert new_text.count("[^1]: notebook:3a563e6f") == 1
    assert new_text.count("[^m_") == 0  # legacy entry-keyed footnotes gone


def _seed_l2(surface: str, entry_id: str) -> None:
    """Write a one-entry L2 md owning ``entry_id``."""
    doc = Document(
        title=f"{surface} memory",
        sections=[
            (
                "Themes",
                [Entry(id=entry_id, section="Themes", text="fact", refs=[f"{surface}:r1"])],
            ),
        ],
    )
    target = paths_mod.l2_file(surface)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize(doc), encoding="utf-8")


@pytest.mark.asyncio
async def test_merge_migrates_legacy_l3_entry_refs_to_surface_names(memory_dir):
    """Pre-pivot L3 docs cite L2 entries by id (``m_<ULID>``); merge
    resolves each id to its owning L2 surface so the rendered L3 doc
    becomes a 7-footnote L3 → L2 → L1 chain.
    """
    chat_id = "m_01HZK1ABCDEFGHJKMNPQRSTVWX"
    notebook_id = "m_01HZK2ABCDEFGHJKMNPQRSTVWX"
    _seed_l2("chat", chat_id)
    _seed_l2("notebook", notebook_id)

    # Legacy L3: one entry citing both L2 entry ids (entry-keyed footnote
    # layout, as written by pre-pivot consolidator runs).
    legacy_l3 = f"""# User profile

## Knowledge
- claim about user[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]

[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]: {chat_id}, {notebook_id}
"""
    target = paths_mod.l3_file("profile")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_l3, encoding="utf-8")

    result = await merge_mod.run_merge("L3", "profile")
    assert result.legacy_l3_refs_migrated == 2

    new_text = target.read_text(encoding="utf-8")
    # Both entry ids are gone; each was rewritten to its owning surface.
    assert chat_id not in new_text
    assert notebook_id not in new_text
    assert "[^1]: chat" in new_text
    assert "[^2]: notebook" in new_text


@pytest.mark.asyncio
async def test_merge_drops_legacy_l3_refs_when_l2_entry_missing(memory_dir):
    """An ``m_<ULID>`` we can't resolve (entry deleted) is dropped, not
    surfaced as a malformed ref."""
    # No L2 seed — every m_<ULID> ref will be unresolvable, so the
    # migration counts the visit but drops the ref.
    legacy_l3 = """# User profile

## Knowledge
- orphaned claim[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]

[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]: m_01HZKAAAAAAAAAAAAAAAAAAAAA
"""
    target = paths_mod.l3_file("profile")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_l3, encoding="utf-8")

    result = await merge_mod.run_merge("L3", "profile")
    assert result.legacy_l3_refs_migrated == 1

    new_text = target.read_text(encoding="utf-8")
    assert "m_01HZKAAAAAAAA" not in new_text
    # Entry survives with no refs left.
    doc = parse(new_text)
    assert len(doc.all_entries()) == 1
    assert doc.all_entries()[0].refs == []


@pytest.mark.asyncio
async def test_merge_handles_mixed_ref_set(memory_dir):
    """Entries can cite different refs; only true duplicates collapse."""
    mixed = """\
# notebook memory

## Concepts
- fact A[^m_01HZK1ABCDEFGHJKMNPQRSTVWX]
- fact B[^m_01HZK2ABCDEFGHJKMNPQRSTVWX]
- fact C[^m_01HZK3ABCDEFGHJKMNPQRSTVWX]

---

[^m_01HZK1ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
[^m_01HZK2ABCDEFGHJKMNPQRSTVWX]: notebook:7b778822
[^m_01HZK3ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
"""
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(mixed, encoding="utf-8")

    result = await merge_mod.run_merge("L2", "notebook")
    assert result.footnote_rows_before == 3
    assert result.footnote_rows_after == 2

    new_text = target.read_text(encoding="utf-8")
    # First-appearance order: 3a563e6f is [^1], 7b778822 is [^2].
    assert "[^1]: notebook:3a563e6f" in new_text
    assert "[^2]: notebook:7b778822" in new_text
    assert "[^3]" not in new_text
