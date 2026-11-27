"""Snapshot adapter tests — focus on the partner-conversation bridge.

Partner runtimes persist their conversations as JSONL under
``<admin>/partners/<id>/sessions/*.jsonl`` (a store separate from the
chat-history SQLite DB). ``read_partner_entities`` bridges those files
into the ``partner`` memory surface so they consolidate into L2/L3 like
any other surface, tagged with the originating partner.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from deeptutor.services.memory.snapshot import adapters


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self.workspace_root = root


def _write_session(sessions_dir: Path, key: str, turns: list[tuple[str, str]]) -> None:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    with (sessions_dir / f"{key}.jsonl").open("w", encoding="utf-8") as fh:
        for i, (role, content) in enumerate(turns):
            fh.write(
                json.dumps(
                    {"role": role, "content": content, "timestamp": f"2026-06-16T10:0{i}:00"},
                    ensure_ascii=False,
                )
                + "\n"
            )


@pytest.fixture
def partner_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make ``tmp_path`` the admin root and route both path services there."""
    monkeypatch.setattr(adapters, "get_path_service", lambda: _FakePathService(tmp_path))
    import deeptutor.multi_user.paths as mu_paths

    monkeypatch.setattr(mu_paths, "get_admin_path_service", lambda: _FakePathService(tmp_path))
    return tmp_path


def test_partner_sessions_become_tagged_entities(partner_tree: Path) -> None:
    pdir = partner_tree / "partners" / "bot1"
    (pdir).mkdir(parents=True)
    (pdir / "config.yaml").write_text("name: Math Tutor\n", encoding="utf-8")
    _write_session(
        pdir / "sessions",
        "telegram:42",
        [("user", "what is a limit"), ("assistant", "a limit is...")],
    )

    entities = adapters.read_partner_entities()

    assert len(entities) == 1
    ent = entities[0]
    assert ent.id == "bot1:telegram:42"
    # Partner tag lands in both the label and the metadata.
    assert "Math Tutor" in ent.label
    assert ent.metadata["partner_id"] == "bot1"
    assert ent.metadata["partner_name"] == "Math Tutor"
    assert ent.metadata["message_count"] == 2
    assert ent.metadata["archived"] is False
    # Conversation is inlined as role blocks for L2 to chew on.
    assert "### user" in ent.content
    assert "what is a limit" in ent.content


def test_archived_sessions_included_and_flagged(partner_tree: Path) -> None:
    pdir = partner_tree / "partners" / "bot1"
    pdir.mkdir(parents=True)
    _write_session(pdir / "sessions", "web:s1", [("user", "hi"), ("assistant", "hello")])
    _write_session(
        pdir / "sessions",
        "_archived_20260101-000000_web_s1",
        [("user", "old"), ("assistant", "older")],
    )

    entities = adapters.read_partner_entities()

    by_id = {e.id: e for e in entities}
    assert len(by_id) == 2
    archived = next(e for e in entities if e.metadata["archived"])
    assert archived.metadata["session_key"].startswith("_archived_")


def test_empty_sessions_skipped_and_name_falls_back_to_id(partner_tree: Path) -> None:
    pdir = partner_tree / "partners" / "bot2"
    pdir.mkdir(parents=True)
    # whitespace-only content → no usable turns → no entity
    _write_session(pdir / "sessions", "web:empty", [("user", "   "), ("assistant", "")])

    entities = adapters.read_partner_entities()
    assert entities == []


def test_missing_config_uses_dir_id_as_name(partner_tree: Path) -> None:
    pdir = partner_tree / "partners" / "bot3"
    pdir.mkdir(parents=True)
    _write_session(pdir / "sessions", "web:s", [("user", "q"), ("assistant", "a")])

    entities = adapters.read_partner_entities()
    assert len(entities) == 1
    assert entities[0].metadata["partner_name"] == "bot3"


def test_non_admin_scope_sees_no_partners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A regular user's memory view must not surface admin partner chats."""
    admin_root = tmp_path / "admin"
    user_root = tmp_path / "users" / "u1" / "workspace"
    pdir = admin_root / "partners" / "bot1"
    pdir.mkdir(parents=True)
    _write_session(pdir / "sessions", "web:s", [("user", "q"), ("assistant", "a")])

    monkeypatch.setattr(adapters, "get_path_service", lambda: _FakePathService(user_root))
    import deeptutor.multi_user.paths as mu_paths

    monkeypatch.setattr(mu_paths, "get_admin_path_service", lambda: _FakePathService(admin_root))

    assert adapters.read_partner_entities() == []


def test_non_admin_sees_only_assigned_private_partner_sessions(
    partner_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.multi_user.paths import user_context

    pdir = partner_tree / "partners" / "bot1"
    pdir.mkdir(parents=True)
    _write_session(pdir / "sessions", "admin", [("user", "admin secret")])
    _write_session(pdir / "users" / "u1" / "sessions", "mine", [("user", "my chat")])
    _write_session(pdir / "users" / "u2" / "sessions", "theirs", [("user", "their chat")])

    import deeptutor.multi_user.partner_access as partner_access

    monkeypatch.setattr(
        partner_access,
        "load_grant",
        lambda uid: {"partners": [{"partner_id": "bot1"}]} if uid == "u1" else {},
    )
    root = (partner_tree / "users" / "u1").resolve()
    user = CurrentUser("u1", "alice", "user", UserScope("user", "u1", root))
    with user_context(user):
        entities = adapters.read_partner_entities()

    assert [entity.id for entity in entities] == ["bot1:mine"]
    assert "my chat" in entities[0].content
    assert "admin secret" not in entities[0].content
    assert "their chat" not in entities[0].content


def test_fingerprint_changes_when_conversation_grows(partner_tree: Path) -> None:
    pdir = partner_tree / "partners" / "bot1"
    pdir.mkdir(parents=True)
    _write_session(pdir / "sessions", "web:s", [("user", "q1"), ("assistant", "a1")])
    fp1 = adapters.read_partner_entities()[0].fingerprint

    # Append another exchange → fingerprint must move so refresh detects it.
    _write_session(
        pdir / "sessions",
        "web:s",
        [("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2")],
    )
    fp2 = adapters.read_partner_entities()[0].fingerprint
    assert fp1 != fp2


# ── Corrupt-file tolerance: skip, warn (with path), keep the rest ────


class _SnapshotPathService(_FakePathService):
    """Fake exposing the notebook / co-writer / book path methods."""

    def get_notebook_dir(self) -> Path:
        return self.workspace_root / "notebook"

    def get_notebook_file(self, notebook_id: str) -> Path:
        return self.get_notebook_dir() / f"{notebook_id}.json"

    def get_notebook_index_file(self) -> Path:
        return self.get_notebook_dir() / "notebooks_index.json"

    def get_co_writer_docs_dir(self) -> Path:
        return self.workspace_root / "co_writer" / "documents"

    def get_book_dir(self) -> Path:
        return self.workspace_root / "book"


@pytest.fixture
def snapshot_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(adapters, "get_path_service", lambda: _SnapshotPathService(tmp_path))
    return tmp_path


def _warn_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        rec.getMessage()
        for rec in caplog.records
        if rec.levelno == logging.WARNING
        and rec.name == "deeptutor.services.memory.snapshot.adapters"
    ]


def test_corrupt_notebook_file_skipped_with_warning(
    snapshot_tree: Path, caplog: pytest.LogCaptureFixture
) -> None:
    index = snapshot_tree / "notebook" / "notebooks_index.json"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({"notebooks": [{"id": "bad", "name": "Bad"}, {"id": "ok", "name": "Ok"}]}),
        encoding="utf-8",
    )
    corrupt = snapshot_tree / "notebook" / "bad.json"
    corrupt.write_text("{ not json", encoding="utf-8")
    good = snapshot_tree / "notebook" / "ok.json"
    good.write_text(
        json.dumps({"records": [{"id": "r1", "title": "T", "output": "O"}]}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        entities = adapters.read_notebook_entities()

    assert [e.id for e in entities] == ["r1"]
    warnings = _warn_records(caplog)
    assert any(str(corrupt) in w for w in warnings)


def test_corrupt_cowriter_manifest_skipped_with_warning(
    snapshot_tree: Path, caplog: pytest.LogCaptureFixture
) -> None:
    docs = snapshot_tree / "co_writer" / "documents"
    bad_dir = docs / "doc_bad"
    bad_dir.mkdir(parents=True)
    corrupt = bad_dir / "manifest.json"
    corrupt.write_text("{ oops", encoding="utf-8")
    good_dir = docs / "doc_ok"
    good_dir.mkdir()
    (good_dir / "manifest.json").write_text(
        json.dumps({"id": "ok", "title": "Doc", "content": "C"}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        entities = adapters.read_cowriter_entities()

    assert [e.id for e in entities] == ["ok"]
    warnings = _warn_records(caplog)
    assert any(str(corrupt) in w for w in warnings)


def test_corrupt_book_manifest_skipped_with_warning(
    snapshot_tree: Path, caplog: pytest.LogCaptureFixture
) -> None:
    books = snapshot_tree / "book"
    bad_dir = books / "book_bad"
    bad_dir.mkdir(parents=True)
    corrupt = bad_dir / "manifest.json"
    corrupt.write_text("[ broken", encoding="utf-8")
    good_dir = books / "book_ok"
    good_dir.mkdir()
    (good_dir / "manifest.json").write_text(
        json.dumps({"id": "ok", "title": "Book", "description": "D"}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        entities = adapters.read_book_entities()

    assert [e.id for e in entities] == ["ok"]
    warnings = _warn_records(caplog)
    assert any(str(corrupt) in w for w in warnings)
