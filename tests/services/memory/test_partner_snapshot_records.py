"""Malformed partner records must not erase healthy snapshot entities."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.memory import snapshot
from deeptutor.services.memory.snapshot import adapters
from deeptutor.services.partners.sessions import PartnerSessionStore


@pytest.fixture
def partner_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import deeptutor.multi_user.paths as paths

    service = SimpleNamespace(workspace_root=tmp_path)
    monkeypatch.setattr(adapters, "get_path_service", lambda: service)
    monkeypatch.setattr(paths, "get_admin_path_service", lambda: service)
    return tmp_path / "partners" / "bot1"


def _history(root: Path, key: str = "web:study") -> Path:
    store = PartnerSessionStore(root / "sessions")
    store.append(key, "user", "Explain limits")
    return next((root / "sessions").glob("*.jsonl"))


def _append(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value) + "\n")


@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_invalid_utf8_line_preserves_readable_records_and_other_partners(
    partner_root: Path, monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    path = _history(partner_root)
    _append(path, {"role": "assistant", "content": "Readable reply", "timestamp": "2026-11-01"})
    _history(partner_root.parent / "bot2")
    before = adapters.read_entities("partner")
    monkeypatch.setattr(
        snapshot.store,
        "load_state",
        lambda surface: {"fingerprints": {entity.id: entity.fingerprint for entity in before}},
    )
    lines = path.read_bytes().splitlines(keepends=True)
    index = {"start": 0, "middle": 1, "end": len(lines)}[position]
    lines.insert(index, b'{"role":"user","content":"private-encoding-canary\xff"}\n')
    original = b"".join(lines)
    path.write_bytes(original)

    assert adapters.read_entities("partner") == before
    assert snapshot.pending_changes("partner") == []
    assert path.read_bytes() == original


def test_unreadable_new_session_does_not_create_removals_for_healthy_sessions(
    partner_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _history(partner_root)
    _history(partner_root.parent / "bot2")
    before = adapters.read_entities("partner")
    monkeypatch.setattr(
        snapshot.store,
        "load_state",
        lambda surface: {"fingerprints": {entity.id: entity.fingerprint for entity in before}},
    )
    broken = partner_root / "sessions" / "broken.jsonl"
    broken.write_bytes(b"\xff\xfe private-encoding-canary\n")

    assert adapters.read_entities("partner") == before
    assert [stamp.id for stamp in adapters.read_stamps("partner")] == [
        entity.id for entity in before
    ]
    assert snapshot.pending_changes("partner") == []
    assert broken.read_bytes() == b"\xff\xfe private-encoding-canary\n"


def test_invalid_utf8_warning_names_file_and_line_without_message_body(
    partner_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _history(partner_root)
    with path.open("ab") as stream:
        stream.write(b'{"content":"private-encoding-canary\xff"}\n')

    with caplog.at_level(logging.WARNING, logger=adapters.__name__):
        entities = adapters.read_entities("partner")

    assert len(entities) == 1
    messages = [row.getMessage() for row in caplog.records if row.name == adapters.__name__]
    assert any(str(path) in message and "line 2" in message for message in messages)
    assert "private-encoding-canary" not in caplog.text


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_partner_unicode_and_universal_newlines_remain_exact(
    partner_root: Path, newline: str
) -> None:
    path = _history(partner_root)
    records = [
        {"role": "user", "content": "解释极限 αβ 🧬", "timestamp": "2026-11-01"},
        {"role": "assistant", "content": "Réponse: ε > 0", "timestamp": "2026-11-02"},
    ]
    original = (
        newline.join(json.dumps(row, ensure_ascii=False) for row in records) + newline
    ).encode("utf-8")
    path.write_bytes(original)

    entities = adapters.read_entities("partner")

    assert len(entities) == 1
    assert entities[0].content == "### user\n解释极限 αβ 🧬\n\n### assistant\nRéponse: ε > 0"
    assert entities[0].metadata["message_count"] == 2
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "content", [[{"text": "structured"}], {"text": "object"}, 7, 0, 1.5, True, False, [], {}, None]
)
def test_non_text_records_do_not_change_valid_entities_or_create_removals(
    partner_root: Path, monkeypatch: pytest.MonkeyPatch, content: Any
) -> None:
    path = _history(partner_root)
    _history(partner_root.parent / "bot2")
    before = adapters.read_entities("partner")
    monkeypatch.setattr(
        snapshot.store,
        "load_state",
        lambda surface: {"fingerprints": {entity.id: entity.fingerprint for entity in before}},
    )
    _append(path, {"role": "assistant", "content": content, "timestamp": "2099-01-01T00:00:00Z"})

    assert adapters.read_entities("partner") == before
    assert snapshot.pending_changes("partner") == []


def test_invalid_only_session_does_not_hide_other_sessions(partner_root: Path) -> None:
    _history(partner_root)
    broken = partner_root / "sessions" / "broken.jsonl"
    _append(broken, {"role": "assistant", "content": ["not text"]})

    entities = adapters.read_entities("partner")
    assert [entity.id for entity in entities] == ["bot1:web_study"]


def test_existing_json_line_tolerance_and_missing_content(partner_root: Path) -> None:
    path = _history(partner_root)
    before = adapters.read_entities("partner")
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n{not json\n[]\nnull\n42\n")
    _append(path, {"role": "assistant", "timestamp": "2099-01-01T00:00:00Z"})

    assert adapters.read_entities("partner") == before


def test_non_text_warning_identifies_location_without_message_body(
    partner_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _history(partner_root)
    _append(
        path, {"role": "assistant", "content": {"sensitive-key-canary": "do-not-log-this-payload"}}
    )

    with caplog.at_level(logging.WARNING, logger=adapters.__name__):
        adapters.read_entities("partner")

    warnings = [row.getMessage() for row in caplog.records if row.name == adapters.__name__]
    assert any(str(path) in warning and "2" in warning for warning in warnings)
    assert "do-not-log-this-payload" not in caplog.text
    assert "sensitive-key-canary" not in caplog.text


def test_valid_blank_content_and_archive_state_keep_existing_behavior(partner_root: Path) -> None:
    path = _history(partner_root)
    store = PartnerSessionStore(path.parent)
    store.set_archived("web:study", True)
    _append(path, {"role": "assistant", "content": "  ", "timestamp": "2026-11-02T01:00:00Z"})

    entity = adapters.read_entities("partner")[0]
    assert entity.content == "### user\nExplain limits"
    assert entity.metadata["message_count"] == 1
    assert entity.metadata["archived"] is True
    assert entity.ts == "2026-11-02T01:00:00Z"


def test_read_remains_read_only(partner_root: Path) -> None:
    path = _history(partner_root)
    _append(path, {"role": "assistant", "content": ["malformed"]})
    before = {p: p.read_bytes() for p in partner_root.rglob("*") if p.is_file()}

    assert adapters.read_entities("partner")
    assert {p: p.read_bytes() for p in partner_root.rglob("*") if p.is_file()} == before


def test_private_scope_preserves_own_valid_history_without_reading_admin_content(
    partner_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.multi_user.models import CurrentUser, UserScope
    import deeptutor.multi_user.partner_access as access
    from deeptutor.multi_user.paths import user_context

    _history(partner_root, "admin")
    path = _history(partner_root / "users" / "u1")
    _append(path, {"content": ["bad private record"]})
    _history(partner_root / "users" / "u2", "other")
    monkeypatch.setattr(access, "load_grant", lambda uid: {"partners": [{"partner_id": "bot1"}]})
    root = partner_root.parent.parent / "users" / "u1"
    user = CurrentUser("u1", "alice", "user", UserScope("user", "u1", root))

    with user_context(user):
        entities = adapters.read_entities("partner")

    assert [entity.id for entity in entities] == ["bot1:web_study"]
