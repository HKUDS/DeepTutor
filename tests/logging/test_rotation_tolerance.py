import logging
from pathlib import Path

import pytest

from deeptutor.logging.configure import TolerantRotatingFileHandler


@pytest.fixture
def handler(tmp_path: Path):
    handler = TolerantRotatingFileHandler(
        tmp_path / "deeptutor.jsonl",
        maxBytes=100,
        backupCount=1,
        encoding="utf-8",
    )
    logger = logging.getLogger("deeptutor.tests.rotation-tolerance")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    handler.close()


def _trigger_rollover(handler: TolerantRotatingFileHandler, message: str) -> None:
    """Emit one record through the handler once the file exceeds maxBytes."""
    logger = logging.getLogger("deeptutor.tests.rotation-tolerance")
    pad = "x" * 120
    logger.info(pad)  # pushes the file past maxBytes so the next emit rotates
    handler.flush()
    logger.info(message)
    handler.flush()


def test_failed_rollover_keeps_writing_and_warns_once(handler, monkeypatch, capsys):
    def failing_rotate(source, dest):
        raise PermissionError(
            32, "The process cannot access the file because it is being used by another process"
        )

    monkeypatch.setattr(handler, "rotate", failing_rotate)

    _trigger_rollover(handler, "first record during broken rotation")
    _trigger_rollover(handler, "second record during broken rotation")

    captured = capsys.readouterr()
    assert captured.err.count("--- Logging warning: log rotation failed") == 1

    written = Path(handler.baseFilename).read_text(encoding="utf-8")
    assert "first record during broken rotation" in written
    assert "second record during broken rotation" in written


def test_rotation_resumes_once_the_other_process_releases_the_file(handler, monkeypatch):
    def failing_rotate(source, dest):
        raise PermissionError(
            32, "The process cannot access the file because it is being used by another process"
        )

    monkeypatch.setattr(handler, "rotate", failing_rotate)
    _trigger_rollover(handler, "written while rotation is broken")

    monkeypatch.undo()
    _trigger_rollover(handler, "written after rotation recovered")

    log_path = Path(handler.baseFilename)
    rotated = Path(handler.baseFilename + ".1")
    assert rotated.exists(), "rotation must resume once the file is free"
    assert "written after rotation recovered" in log_path.read_text(encoding="utf-8")


def test_failed_rollover_does_not_raise_out_of_emit(handler, monkeypatch):
    def failing_rotate(source, dest):
        raise PermissionError(32, "file in use")

    monkeypatch.setattr(handler, "rotate", failing_rotate)

    logger = logging.getLogger("deeptutor.tests.rotation-tolerance")
    try:
        _trigger_rollover(handler, "no traceback escapes")
    except Exception:  # pragma: no cover - the assertion below is the real check
        pytest.fail("emit() must not raise when rollover fails")
