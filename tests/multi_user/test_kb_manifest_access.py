"""``resolve_kb_manifest`` is the one seam that reads a KB's document list.

Both consumers (the chat system-prompt inventory and the ``kb_files`` tool) go
through it, so per-user visibility has to hold here: a user's own KBs resolve,
an admin KB resolves only while it is granted, and anything else yields
``None`` rather than a listing.
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.multi_user.knowledge_access import resolve_kb_manifest


def _make_kb(manager: KnowledgeBaseManager, name: str, *files: str) -> None:
    """Register a KB and stage documents into it, as an upload would."""
    raw = Path(manager.base_dir) / name / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for filename in files:
        (raw / filename).write_bytes(b"x" * 512)
    manager.register_knowledge_base(name, description=f"test KB {name}")


def test_user_sees_their_own_kb(mu_isolated_root, as_user) -> None:
    from deeptutor.multi_user.knowledge_access import current_kb_manager

    with as_user("u_alice", role="user"):
        _make_kb(current_kb_manager(), "alice-kb", "a.pdf", "b.pdf")

        manifest = resolve_kb_manifest("alice-kb")

        assert manifest is not None
        assert manifest.total == 2
        assert [document.name for document in manifest.documents] == ["a.pdf", "b.pdf"]


def test_pattern_and_limit_reach_the_filesystem(mu_isolated_root, as_user) -> None:
    from deeptutor.multi_user.knowledge_access import current_kb_manager

    with as_user("u_alice", role="user"):
        _make_kb(current_kb_manager(), "alice-kb", "a.pdf", "b.pdf", "notes.md")

        manifest = resolve_kb_manifest("alice-kb", pattern="*.pdf", limit=1)

        assert manifest is not None
        assert (manifest.total, manifest.matched, manifest.omitted) == (3, 2, 1)


def test_unknown_kb_yields_no_manifest(mu_isolated_root, as_user) -> None:
    with as_user("u_alice", role="user"):
        assert resolve_kb_manifest("does-not-exist") is None


def test_ungranted_admin_kb_yields_no_manifest(mu_isolated_root, as_user) -> None:
    """Naming an admin KB directly must not leak its file list (403 → None)."""
    from deeptutor.multi_user.knowledge_access import admin_kb_manager

    with as_user("u_admin", role="admin"):
        _make_kb(admin_kb_manager(), "admin-kb", "secret.pdf")

    with as_user("u_alice", role="user"):
        assert resolve_kb_manifest("admin:kb:admin-kb") is None


def test_empty_reference_yields_no_manifest(mu_isolated_root, as_user) -> None:
    with as_user("u_alice", role="user"):
        assert resolve_kb_manifest("") is None
        assert resolve_kb_manifest(None) is None
