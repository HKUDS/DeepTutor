"""Manager handling of connected-subagent KBs (``type: subagent`` pointers).

A subagent connection records the backend (``agent_kind``) and its target — a
``cwd`` for a local CLI, or a ``partner_id`` for a partner. Like the other
connected types it creates no folder and runs no index. The critical contract
exercised here: ``get_metadata`` must surface ``partner_id`` — the subagent
binding reads it from there to drive the right partner, so dropping it silently
breaks partner consults ("No partner is bound to this connection").
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager


def test_register_partner_connection_round_trips_partner_id(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    entry = manager.register_subagent_connection("Panda Kate", "partner", partner_id="panda-kate")
    assert entry["type"] == "subagent"
    assert entry["agent_kind"] == "partner"
    assert entry["partner_id"] == "panda-kate"
    assert entry["cwd"] == ""
    # No KB folder is created under base_dir.
    assert not (manager.base_dir / "Panda Kate").exists()

    # The binding resolves the partner through get_metadata — it MUST carry it.
    meta = manager.get_metadata("Panda Kate")
    assert meta["type"] == "subagent"
    assert meta["agent_kind"] == "partner"
    assert meta["partner_id"] == "panda-kate"


def test_register_cli_connection_has_no_partner_id(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    manager.register_subagent_connection("MyClaude", "claude_code", cwd="")
    meta = manager.get_metadata("MyClaude")
    assert meta["agent_kind"] == "claude_code"
    # Empty partner_id is dropped from the curated metadata (None-stripped).
    assert "partner_id" not in meta or not meta["partner_id"]
