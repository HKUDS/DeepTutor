"""Local and remote subagent connections exclude Partners."""

from __future__ import annotations

from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager


def test_partners_are_selected_directly_not_registered(tmp_path: Path) -> None:
    import pytest

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    with pytest.raises(ValueError, match="Ask partner"):
        manager.register_subagent_connection("Panda Kate", "partner")


def test_register_cli_connection_has_no_partner_id(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    manager.register_subagent_connection("MyClaude", "claude_code", cwd="")
    meta = manager.get_metadata("MyClaude")
    assert meta["agent_kind"] == "claude_code"
    # Empty partner_id is dropped from the curated metadata (None-stripped).
    assert "partner_id" not in meta or not meta["partner_id"]
