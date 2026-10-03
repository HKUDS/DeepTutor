"""Failure-visibility tests for ``KnowledgeBaseManager.update_kb_status``.

The DT-22 swallow-scan flagged the bare ``except Exception: pass`` around the
ready-transition metadata refresh: when refreshing embedding signatures or
``index_versions`` failed, the failure left no trace and the persisted KB
entry silently diverged from the on-disk index state that the UI renders.

These tests pin the contract that (a) a metadata refresh failure is logged,
(b) a config-persist failure is logged and reported through the return value
instead of only surfacing (or being swallowed) at an arbitrary caller, and
(c) a successful update reports ``True``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager


def test_successful_update_returns_true(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))

    result = manager.update_kb_status(name="kb1", status="processing")

    assert result is True
    assert manager.get_kb_status("kb1")["status"] == "processing"


def test_persist_failure_is_logged_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))

    def _fail_save() -> None:
        raise OSError("disk full")

    monkeypatch.setattr(manager, "_save_config", _fail_save)

    with caplog.at_level(logging.ERROR, logger="deeptutor.knowledge.manager"):
        result = manager.update_kb_status(name="kb1", status="error")

    assert result is False
    assert any(
        "kb1" in record.message and record.levelno == logging.ERROR
        for record in caplog.records
    )


def test_ready_metadata_failure_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from deeptutor.knowledge import manager as manager_module

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    (tmp_path / "kb1").mkdir()
    (tmp_path / "kb1" / "version-1").mkdir()

    def _boom(kb_dir: Path, provider: str) -> list[dict]:
        raise RuntimeError("docstore exploded")

    monkeypatch.setattr(manager_module, "inspect_kb_versions", _boom)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.manager"):
        result = manager.update_kb_status(name="kb1", status="ready")

    # The metadata refresh is best-effort: the status write itself still lands.
    assert result is True
    assert any(
        "kb1" in record.message and record.levelno == logging.WARNING
        for record in caplog.records
    )
