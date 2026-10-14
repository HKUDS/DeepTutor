"""Chunked audit edits retain the line identities shown to the model."""

import json
from pathlib import Path
import re

import pytest

from deeptutor.services.memory import paths
from deeptutor.services.memory.consolidator.modes import audit
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ids import new_entry_id
from deeptutor.services.memory.settings import ChunkingSettings, MemorySettings, MergeSettings


@pytest.mark.asyncio
@pytest.mark.parametrize("layer,key", [("L2", "chat"), ("L3", "recent")])
async def test_earlier_deletion_does_not_shift_later_chunk_target(
    tmp_path: Path, monkeypatch, layer: str, key: str
) -> None:
    """Use real annotation, chunking, parsing and disk writes with fixed model edits."""
    monkeypatch.setattr(paths, "memory_root", lambda: tmp_path)
    monkeypatch.setattr(audit.snap, "read_snapshot", lambda surface: [])
    settings = MemorySettings(
        chunking=ChunkingSettings(min_chunk_chars=200, max_chunk_chars=400, overlap_ratio=0),
        merge=MergeSettings(auto_after_audit=False),
    )
    monkeypatch.setattr(audit, "load_memory_settings", lambda: settings)
    labels = ["delete-first", "keep-second", "delete-third", "keep-fourth"]
    entries = [Entry(new_entry_id(), "Notes", label, ["chat:source"]) for label in labels]
    document = tmp_path / layer / f"{key}.md"
    document.parent.mkdir()
    document.write_text(serialize(Document("Memory", [("Notes", entries)])), encoding="utf-8")
    emitted = set()

    async def fixed_edits(*, user_prompt, **kwargs):
        for label in ("delete-first", "delete-third"):
            if label in emitted:
                continue
            match = re.search(r"(?:line\s+|^\s*)(\d+): (?:- )?" + label, user_prompt, re.MULTILINE)
            if match:
                emitted.add(label)
                return json.dumps({"edits": [{"op": "delete", "line": int(match[1])}]})
        return '{"edits": []}'

    monkeypatch.setattr(audit, "call_llm", fixed_edits)
    result = await audit.run_audit(layer, key, budget=4)
    assert result.chunks_processed > 1
    assert emitted == {"delete-first", "delete-third"}
    assert [entry.text for entry in parse(document.read_text(encoding="utf-8")).all_entries()] == [
        "keep-second",
        "keep-fourth",
    ]
