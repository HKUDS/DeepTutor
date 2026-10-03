"""Regression tests for workspace_for() meta.json failure handling."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from deeptutor.services.rag.pipelines.lightrag import engine

_ENGINE_LOGGER = "deeptutor.services.rag.pipelines.lightrag.engine"


def _hash_workspace(path: Path) -> str:
    identity = str(path.resolve()).encode("utf-8")
    return f"deeptutor_{hashlib.sha256(identity).hexdigest()[:16]}"


def test_corrupt_meta_json_warns_and_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "meta.json").write_text("{not valid json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=_ENGINE_LOGGER):
        name = engine.workspace_for(tmp_path)
    assert name == _hash_workspace(tmp_path)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a warning when meta.json exists but fails to parse"
    message = warnings[0].getMessage()
    assert "meta.json" in message
    assert "JSONDecodeError" in message


def test_unreadable_meta_json_warns_and_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    meta = tmp_path / "meta.json"
    meta.write_text(
        json.dumps({"provider": "lightrag", "workspace": "deeptutor_abc"}), encoding="utf-8"
    )
    meta.chmod(0o000)
    with caplog.at_level(logging.WARNING, logger=_ENGINE_LOGGER):
        name = engine.workspace_for(tmp_path)
    assert name == _hash_workspace(tmp_path)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a warning when meta.json exists but cannot be read"
    message = warnings[0].getMessage()
    assert "meta.json" in message
    assert "PermissionError" in message


def test_missing_meta_json_stays_silent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_ENGINE_LOGGER):
        name = engine.workspace_for(tmp_path)
    assert name == _hash_workspace(tmp_path)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_valid_meta_json_returns_published_name(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    published = "deeptutor_" + "ab" * 8
    (tmp_path / "meta.json").write_text(
        json.dumps({"provider": "lightrag", "workspace": published}),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger=_ENGINE_LOGGER):
        name = engine.workspace_for(tmp_path)
    assert name == published
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
