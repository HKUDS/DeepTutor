"""Partner archive snapshots using real, portable session-store files."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.services.memory.snapshot import adapters
from deeptutor.services.memory.snapshot.diff import diff_snapshots
from deeptutor.services.partners.sessions import PartnerSessionStore


@pytest.fixture
def partner_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Route the adapter to disposable admin storage."""
    import deeptutor.multi_user.paths as paths

    service = SimpleNamespace(workspace_root=tmp_path)
    monkeypatch.setattr(adapters, "get_path_service", lambda: service)
    monkeypatch.setattr(paths, "get_admin_path_service", lambda: service)
    return tmp_path / "partners" / "bot1"


def _session(partner_root: Path) -> PartnerSessionStore:
    store = PartnerSessionStore(partner_root / "sessions")
    store.append("web:study", "user", "Explain limits")
    store.append("web:study", "assistant", "A limit describes approaching a value.")
    return store


def test_soft_archive_is_visible_without_renaming_or_modifying_history(partner_root: Path) -> None:
    store = _session(partner_root)
    original = adapters.read_partner_entities()[0]
    assert original.metadata["archived"] is False

    assert store.set_archived("web:study", True)
    archived = adapters.read_partner_entities()[0]

    assert archived.metadata["archived"] is True
    assert archived.id == original.id
    assert archived.content == original.content
    assert archived.ts == original.ts
    assert archived.metadata["message_count"] == original.metadata["message_count"]
    assert archived.fingerprint != original.fingerprint


def test_archive_and_restore_are_visible_to_snapshot_diff(partner_root: Path) -> None:
    store = _session(partner_root)
    original = adapters.read_stamps("partner")[0]
    store.set_archived("web:study", True)
    archived = adapters.read_stamps("partner")[0]

    changes = diff_snapshots(
        {original.id: original.fingerprint},
        {archived.id: archived.fingerprint},
        label_map={archived.id: archived.label},
    )
    assert len(changes) == 1
    assert changes[0].kind == "modified"

    store.set_archived("web:study", False)
    restored = adapters.read_partner_entities()[0]
    assert restored.metadata["archived"] is False
    assert restored.fingerprint == original.fingerprint


def test_renamed_archives_still_work_with_no_sidecar(partner_root: Path) -> None:
    store = _session(partner_root)
    assert store.archive("web:study") is not None

    archived = adapters.read_partner_entities()[0]
    assert archived.metadata["archived"] is True
    assert archived.metadata["session_key"].startswith("_archived_")


@pytest.mark.parametrize("index", ["{broken", "[]", '{"web_study": null}', '{"web_study": []}'])
def test_malformed_index_does_not_hide_history(partner_root: Path, index: str) -> None:
    _session(partner_root)
    (partner_root / "sessions" / "_index.json").write_text(index, encoding="utf-8")

    entities = adapters.read_partner_entities()
    assert len(entities) == 1
    assert entities[0].metadata["archived"] is False


def test_archive_flags_are_scoped_to_each_partner(partner_root: Path) -> None:
    first = _session(partner_root)
    first.set_archived("web:study", True)
    _session(partner_root.parent / "bot2")

    entities = {
        entity.metadata["partner_id"]: entity for entity in adapters.read_partner_entities()
    }
    assert entities["bot1"].metadata["archived"] is True
    assert entities["bot2"].metadata["archived"] is False


def test_snapshot_read_does_not_write_to_partner_storage(partner_root: Path) -> None:
    store = _session(partner_root)
    store.set_archived("web:study", True)
    before = {
        path.relative_to(partner_root): path.read_bytes()
        for path in partner_root.rglob("*")
        if path.is_file()
    }

    adapters.read_partner_entities()

    after = {
        path.relative_to(partner_root): path.read_bytes()
        for path in partner_root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_missing_sidecar_is_not_created(partner_root: Path) -> None:
    _session(partner_root)
    index = partner_root / "sessions" / "_index.json"
    assert not index.exists()
    assert adapters.read_partner_entities()[0].metadata["archived"] is False
    assert not index.exists()


@pytest.mark.parametrize("archived", [False, True])
def test_regular_user_archive_flags_come_from_their_own_sessions(
    partner_root: Path, monkeypatch: pytest.MonkeyPatch, archived: bool
) -> None:
    from deeptutor.multi_user.models import CurrentUser, UserScope
    import deeptutor.multi_user.partner_access as access
    from deeptutor.multi_user.paths import user_context

    admin_store = _session(partner_root)
    admin_store.set_archived("web:study", not archived)
    private_store = _session(partner_root / "users" / "u1")
    private_store.set_archived("web:study", archived)
    monkeypatch.setattr(access, "load_grant", lambda uid: {"partners": [{"partner_id": "bot1"}]})
    root = partner_root.parent.parent / "users" / "u1"
    user = CurrentUser("u1", "alice", "user", UserScope("user", "u1", root))

    with user_context(user):
        entities = adapters.read_partner_entities()

    assert len(entities) == 1
    assert entities[0].metadata["archived"] is archived
