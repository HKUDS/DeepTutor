"""End-to-end (LLM-mocked) tests for the three modes.

These are the load-bearing tests for the new pipeline. The LLM call is
mocked at the ``call_llm`` boundary in :mod:`modes._runtime`; everything
else (chunker, ref validation, doc IO, meta) runs for real on a temp
memory dir.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator.modes import audit as audit_mod
from deeptutor.services.memory.consolidator.modes import dedup as dedup_mod
from deeptutor.services.memory.consolidator.modes import update as update_mod
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ids import new_entry_id
from deeptutor.services.memory.snapshot.entity import Entity


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "trace").mkdir(parents=True, exist_ok=True)
    yield tmp_path


def _entity(eid: str, content: str = "user uses spaced repetition with FSRS scheduler.") -> Entity:
    return Entity(
        id=eid,
        label=f"entry {eid}",
        ts="2026-05-19T00:00:00Z",
        content=content,
        metadata={},
        fingerprint="fp",
    )


# ── update — L2 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_l2_appends_facts_from_chunk(memory_dir, monkeypatch):
    entities = [_entity("01ABC"), _entity("01DEF")]

    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.update.snap.read_snapshot",
        lambda surface: entities,
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        # Return one valid fact per call, citing a ref in the chunk.
        if "01ABC" in user_prompt:
            return '{"facts": [{"text": "uses FSRS scheduling", "section": "Mastery", "refs": ["chat:01ABC"]}]}'
        if "01DEF" in user_prompt:
            return '{"facts": [{"text": "scheduler customisation", "section": "Mastery", "refs": ["chat:01DEF"]}]}'
        return '{"facts": []}'

    # Force a tiny chunker so each entity ends up in its own chunk.
    with (
        patch("deeptutor.services.memory.consolidator.modes.update.call_llm", side_effect=fake_llm),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
    ):
        from deeptutor.services.memory.settings import (
            ChunkingSettings,
            DedupSettings,
            MemorySettings,
        )

        mock_settings.return_value = MemorySettings(
            chunking=ChunkingSettings(min_chunk_chars=200, max_chunk_chars=400, overlap_ratio=0.0),
            dedup=DedupSettings(auto_after_update=False),
        )
        result = await update_mod.run_update("L2", "chat", language="en")

    assert result.facts_added >= 1
    assert not result.no_new_input
    md = (memory_dir / "L2" / "chat.md").read_text(encoding="utf-8")
    assert "## Mastery" in md
    assert "FSRS" in md or "scheduler" in md


@pytest.mark.asyncio
async def test_update_l2_idempotent_when_no_new_entities(memory_dir, monkeypatch):
    entities = [_entity("01ABC")]
    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.update.snap.read_snapshot",
        lambda surface: entities,
    )

    # First run records the entity in meta.
    async def llm_returns_one(*, system_prompt, user_prompt, **kwargs):
        return '{"facts": [{"text": "uses Anki", "section": "Topics", "refs": ["chat:01ABC"]}]}'

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.update.call_llm",
            side_effect=llm_returns_one,
        ),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
    ):
        from deeptutor.services.memory.settings import DedupSettings, MemorySettings

        mock_settings.return_value = MemorySettings(dedup=DedupSettings(auto_after_update=False))
        first = await update_mod.run_update("L2", "chat", language="en")
    assert first.facts_added >= 0

    # Second run with the same entities: no new traces → no LLM calls,
    # no facts added.
    llm_called = []

    async def llm_should_not_run(*args, **kwargs):
        llm_called.append(1)
        return '{"facts": []}'

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.update.call_llm",
            side_effect=llm_should_not_run,
        ),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
    ):
        from deeptutor.services.memory.settings import DedupSettings, MemorySettings

        mock_settings.return_value = MemorySettings(dedup=DedupSettings(auto_after_update=False))
        second = await update_mod.run_update("L2", "chat", language="en")
    assert second.no_new_input is True
    assert llm_called == []


@pytest.mark.asyncio
async def test_update_l2_drops_facts_with_out_of_pool_refs(memory_dir, monkeypatch):
    entities = [_entity("01ABC")]
    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.update.snap.read_snapshot",
        lambda surface: entities,
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        # Return one fact with a ref not in the chunk pool.
        return (
            '{"facts": [{"text": "uses Anki", "section": "Topics", "refs": ["chat:NOT_IN_CHUNK"]}]}'
        )

    with (
        patch("deeptutor.services.memory.consolidator.modes.update.call_llm", side_effect=fake_llm),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
    ):
        from deeptutor.services.memory.settings import (
            DedupSettings,
            MemorySettings,
            ReferenceSettings,
        )

        mock_settings.return_value = MemorySettings(
            dedup=DedupSettings(auto_after_update=False),
            reference=ReferenceSettings(enforce_required=True, drop_invalid_refs=True),
        )
        result = await update_mod.run_update("L2", "chat", language="en")

    # The fact had only an out-of-pool ref → dropped.
    assert result.refs_dropped >= 1
    assert result.facts_added == 0


# ── audit — L2 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_l2_applies_replace_edit(memory_dir, monkeypatch):
    # Seed an existing L2 doc.
    ids = [new_entry_id()]
    doc = Document(
        title="chat memory",
        sections=[
            ("Topics", [Entry(id=ids[0], section="Topics", text="claims X", refs=["chat:01ABC"])])
        ],
    )
    path = memory_dir / "L2" / "chat.md"
    path.write_text(serialize(doc), encoding="utf-8")

    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.audit.snap.read_snapshot",
        lambda surface: [_entity("01ABC", content="the user actually said Y, not X")],
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        # Find the bullet line and emit a replace.
        line_no = None
        for ln in user_prompt.splitlines():
            if "claims X" in ln and ln.lstrip().startswith(("3", "4", "5", "6", "7", "8")):
                line_no = int(ln.strip().split(":")[0])
                break
        if line_no is None:
            return '{"edits": []}'
        return (
            '{"edits": [{"op": "replace", "line": '
            + str(line_no)
            + ', "new_text": "claims Y", "refs": ["chat:01ABC"], "reason": "matched evidence"}]}'
        )

    with patch("deeptutor.services.memory.consolidator.modes.audit.call_llm", side_effect=fake_llm):
        result = await audit_mod.run_audit("L2", "chat", language="en", budget=1)

    new_md = path.read_text(encoding="utf-8")
    assert "claims Y" in new_md
    assert result.edits_applied >= 1


# ── dedup ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_early_stop_when_no_edits(memory_dir, monkeypatch):
    ids = [new_entry_id() for _ in range(2)]
    doc = Document(
        title="chat memory",
        sections=[
            (
                "Topics",
                [
                    Entry(id=ids[0], section="Topics", text="alpha", refs=["chat:01"]),
                    Entry(id=ids[1], section="Topics", text="beta", refs=["chat:02"]),
                ],
            )
        ],
    )
    path = memory_dir / "L2" / "chat.md"
    path.write_text(serialize(doc), encoding="utf-8")

    llm_calls = []

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings") as mock_settings,
    ):
        from deeptutor.services.memory.settings import DedupSettings, MemorySettings

        mock_settings.return_value = MemorySettings(
            dedup=DedupSettings(iterations=5, auto_after_update=False)
        )
        result = await dedup_mod.run_dedup("L2", "chat", language="en")

    assert result.converged_early is True
    assert result.iterations_run == 1
    assert len(llm_calls) == 1


@pytest.mark.asyncio
async def test_dedup_applies_delete_then_stops(memory_dir, monkeypatch):
    ids = [new_entry_id() for _ in range(2)]
    doc = Document(
        title="chat memory",
        sections=[
            (
                "Topics",
                [
                    Entry(id=ids[0], section="Topics", text="duplicate fact", refs=["chat:01"]),
                    Entry(id=ids[1], section="Topics", text="duplicate fact", refs=["chat:02"]),
                ],
            )
        ],
    )
    path = memory_dir / "L2" / "chat.md"
    path.write_text(serialize(doc), encoding="utf-8")

    call_count = [0]

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # Find the second bullet's line number.
            line_no = None
            seen = 0
            for ln in user_prompt.splitlines():
                if "duplicate fact" in ln and ln.lstrip()[:2].rstrip(":").isdigit():
                    seen += 1
                    if seen == 2:
                        line_no = int(ln.strip().split(":")[0])
                        break
            if line_no is None:
                return '{"edits": []}'
            return (
                '{"edits": [{"op": "delete", "line_start": '
                + str(line_no)
                + ', "line_end": '
                + str(line_no)
                + ', "reason": "duplicate"}]}'
            )
        return '{"edits": []}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings") as mock_settings,
    ):
        from deeptutor.services.memory.settings import DedupSettings, MemorySettings

        mock_settings.return_value = MemorySettings(
            dedup=DedupSettings(iterations=3, auto_after_update=False)
        )
        result = await dedup_mod.run_dedup("L2", "chat", language="en")

    assert result.edits_applied >= 1
    new_doc = parse(path.read_text(encoding="utf-8"))
    assert len([e for e in new_doc.all_entries() if e.text == "duplicate fact"]) == 1
