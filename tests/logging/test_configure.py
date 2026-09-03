import importlib
import json
import logging
import os
from pathlib import Path
import stat

import pytest

from deeptutor.logging import LoggingConfig, bind_log_context


@pytest.fixture(autouse=True)
def _clean_logging_handlers():
    configure_module = importlib.import_module("deeptutor.logging.configure")
    configure_module._remove_managed_handlers(logging.getLogger())
    yield
    configure_module._remove_managed_handlers(logging.getLogger())


def _flush_root_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_configure_logging_writes_jsonl_and_respects_level(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("deeptutor.logging.configure")
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="WARNING",
            console_output=False,
            file_output=True,
            log_dir=str(tmp_path),
            max_bytes=1024 * 1024,
            backup_count=1,
        ),
    )

    configure_module.configure_logging(force=True)
    logger = logging.getLogger("deeptutor.tests.config")
    with bind_log_context(request_id="req-1", task_id="task-1"):
        logger.info("filtered")
        logger.warning("written")
    _flush_root_handlers()

    lines = (tmp_path / "deeptutor.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "deeptutor.tests.config"
    assert entry["message"] == "written"
    assert entry["context"] == {"request_id": "req-1", "task_id": "task-1"}


def test_configure_logging_uses_rotation_settings(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("deeptutor.logging.configure")
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="INFO",
            console_output=False,
            file_output=True,
            log_dir=str(tmp_path),
            max_bytes=220,
            backup_count=1,
        ),
    )

    configure_module.configure_logging(force=True)
    logger = logging.getLogger("deeptutor.tests.rotation")
    for index in range(20):
        logger.info("rotation line %02d %s", index, "x" * 40)
    _flush_root_handlers()

    assert (tmp_path / "deeptutor.jsonl").exists()
    assert (tmp_path / "deeptutor.jsonl.1").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not authoritative")
def test_configure_logging_uses_private_directory_and_file_modes(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("deeptutor.logging.configure")
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="INFO",
            console_output=False,
            file_output=True,
            log_dir=str(log_dir),
            max_bytes=1024,
            backup_count=1,
        ),
    )

    configure_module.configure_logging(force=True)

    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((log_dir / "deeptutor.jsonl").stat().st_mode) == 0o600
