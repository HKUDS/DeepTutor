"""Migration-lock liveness unlocking in WorkspaceCatalogMixin.assert_available."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
from typing import Any
from unittest import mock
import uuid

import pytest

from deeptutor.services.workspace import catalog
from deeptutor.services.workspace.catalog import WorkspaceCatalogMixin
from deeptutor.services.workspace.models import WorkspaceError

_HOST = socket.gethostname()
_BLOCKED = "being migrated"


class _SafeOS:
    """os proxy that forbids real signal delivery; liveness is always stubbed."""

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    @staticmethod
    def kill(pid: int, sig: int) -> None:
        raise AssertionError("tests must not deliver real signals")


class _StubCatalog(WorkspaceCatalogMixin):
    def __init__(self, database: Path) -> None:
        self._database = database

    def _catalog_file(self) -> Path:
        return self._database


def _probe(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> mock.Mock:
    probe = mock.Mock(**kwargs)
    monkeypatch.setattr(catalog, "probe_process_liveness", probe, raising=False)
    return probe


def _marker(pid: Any = 12345, host: str | None = None) -> dict[str, Any]:
    return {"id": uuid.uuid4().hex, "pid": pid, "host": host or _HOST}


def _seed(service: _StubCatalog, key: str, value: str) -> None:
    with service._catalog_connection() as conn:
        conn.execute("INSERT INTO metadata VALUES (?, ?)", (key, value))


def _metadata(service: _StubCatalog) -> dict[str, str]:
    with service._catalog_connection() as conn:
        return dict(conn.execute("SELECT key, value FROM metadata").fetchall())


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _StubCatalog:
    monkeypatch.setattr(catalog, "os", _SafeOS())
    return _StubCatalog(tmp_path / "workspaces.sqlite3")


def test_missing_marker_never_probes(service, monkeypatch):
    probe = _probe(monkeypatch, return_value="dead")
    _seed(service, "root", json.dumps("/tmp/workspaces"))
    assert service.assert_available() is None
    probe.assert_not_called()
    assert "migration" not in _metadata(service)


def test_absent_database_returns_without_probing_or_creating(service, monkeypatch):
    probe = _probe(monkeypatch, return_value="dead")
    assert service.assert_available() is None
    probe.assert_not_called()
    assert not service._catalog_file().exists()


def test_same_host_dead_deletes_exact_marker_and_unlocks(service, monkeypatch):
    probe = _probe(monkeypatch, return_value="dead")
    _seed(service, "root", json.dumps("/tmp/workspaces"))
    _seed(service, "migration", json.dumps(_marker()))
    assert service.assert_available() is None
    probe.assert_called_once_with(12345)
    stored = _metadata(service)
    assert "migration" not in stored
    assert stored["root"] == json.dumps("/tmp/workspaces")


@pytest.mark.parametrize("state", ["alive", "unknown", None, False, "zombie"])
def test_same_host_unconfirmed_states_retain_marker(service, monkeypatch, state):
    probe = _probe(monkeypatch, return_value=state)
    raw = json.dumps(_marker())
    _seed(service, "migration", raw)
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_called_once_with(12345)
    assert _metadata(service)["migration"] == raw


@pytest.mark.parametrize("exc", [PermissionError, OSError, RuntimeError])
def test_helper_failures_retain_marker_and_block(service, monkeypatch, exc):
    probe = _probe(monkeypatch, side_effect=exc("probe failed"))
    raw = json.dumps(_marker())
    _seed(service, "migration", raw)
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_called_once_with(12345)
    assert _metadata(service)["migration"] == raw


def test_other_host_blocks_without_probing(service, monkeypatch):
    probe = _probe(monkeypatch, return_value="dead")
    raw = json.dumps(_marker(host="other-host"))
    _seed(service, "migration", raw)
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_not_called()
    assert _metadata(service)["migration"] == raw


def test_marker_replaced_during_probe_stays_blocked(service, monkeypatch):
    replacement = json.dumps(_marker(pid=4242))

    def replace_then_report_dead(pid):
        with service._catalog_connection() as conn:
            conn.execute("DELETE FROM metadata WHERE key = 'migration'")
            conn.execute("INSERT INTO metadata VALUES ('migration', ?)", (replacement,))
        return "dead"

    probe = _probe(monkeypatch, side_effect=replace_then_report_dead)
    _seed(service, "migration", json.dumps(_marker()))
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_called_once_with(12345)
    assert _metadata(service)["migration"] == replacement


def test_marker_removed_by_probe_stays_blocked_then_unlocks(service, monkeypatch):
    def remove_then_report_dead(pid):
        with service._catalog_connection() as conn:
            conn.execute("DELETE FROM metadata WHERE key = 'migration'")
        return "dead"

    probe = _probe(monkeypatch, side_effect=remove_then_report_dead)
    _seed(service, "migration", json.dumps(_marker()))
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_called_once_with(12345)
    assert "migration" not in _metadata(service)
    assert service.assert_available() is None
    probe.assert_called_once_with(12345)


@pytest.mark.parametrize("style", ["indent", "compact"])
def test_noncanonical_marker_unlocks_by_deleting_identical_bytes(service, monkeypatch, style):
    probe = _probe(monkeypatch, return_value="dead")
    marker = _marker()
    raw = (
        json.dumps(marker, indent=2)
        if style == "indent"
        else json.dumps(marker, separators=(",", ":"))
    )
    _seed(service, "migration", raw)
    assert service.assert_available() is None
    probe.assert_called_once_with(12345)
    assert "migration" not in _metadata(service)


def test_rewritten_marker_with_same_data_but_different_bytes_stays_blocked(service, monkeypatch):
    marker = _marker()
    original = json.dumps(marker)
    rewritten = json.dumps(marker, indent=2)

    def rewrite_then_report_dead(pid):
        with service._catalog_connection() as conn:
            conn.execute("UPDATE metadata SET value = ? WHERE key = 'migration'", (rewritten,))
        return "dead"

    probe = _probe(monkeypatch, side_effect=rewrite_then_report_dead)
    _seed(service, "migration", original)
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_called_once_with(12345)
    assert _metadata(service)["migration"] == rewritten


@pytest.mark.parametrize(
    "marker",
    [
        {"id": "m", "host": _HOST},
        {"id": "m", "pid": "not-a-pid", "host": _HOST},
    ],
    ids=["missing-pid", "non-numeric-pid"],
)
def test_malformed_marker_is_retained_and_blocks(service, monkeypatch, marker):
    probe = _probe(monkeypatch, return_value="unknown")
    raw = json.dumps(marker)
    _seed(service, "migration", raw)
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_not_called()
    assert _metadata(service)["migration"] == raw


@pytest.mark.parametrize(
    "raw",
    ["not-json{", "null", "[]", "{}"],
    ids=["malformed-json", "json-null", "json-list", "empty-object"],
)
def test_non_dict_marker_raw_retained_and_blocks_without_probing(service, monkeypatch, raw):
    probe = _probe(monkeypatch, return_value="dead")
    _seed(service, "migration", raw)
    with pytest.raises(WorkspaceError, match=_BLOCKED):
        service.assert_available()
    probe.assert_not_called()
    assert _metadata(service)["migration"] == raw


def test_windows_kill_winerror87_regression(service, monkeypatch):
    probe = _probe(monkeypatch, return_value="dead")
    _seed(service, "migration", json.dumps(_marker()))
    kill = mock.Mock(side_effect=OSError(22, "WinError 87"))

    class _WindowsOS(_SafeOS):
        @staticmethod
        def kill(pid: int, sig: int) -> None:
            kill(pid, sig)

    monkeypatch.setattr(catalog, "os", _WindowsOS())
    assert service.assert_available() is None
    probe.assert_called_once_with(12345)
    assert "migration" not in _metadata(service)
    kill.assert_not_called()
