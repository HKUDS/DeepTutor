"""ConsoleFormatter must surface exc_info, not swallow it.

Previously it printed only ``record.getMessage()``, so ``logger.error(...,
exc_info=True)`` produced a one-line summary on the console with no traceback —
hiding the real cause of failures (the stale SSL_CERT_FILE crash was diagnosed
only because the JSONL file handler still wrote the exception).
"""

from __future__ import annotations

import logging
import sys

from deeptutor.logging.formatters import ConsoleFormatter


def _make_record(msg: str, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="deeptutor.test.formatter",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
        func="fn",
    )


def test_console_formatter_without_exc_info_has_no_traceback() -> None:
    out = ConsoleFormatter().format(_make_record("hello"))
    assert "hello" in out
    assert "Traceback" not in out


def test_console_formatter_appends_traceback() -> None:
    try:
        raise ValueError("kaboom")
    except ValueError:
        exc_info = sys.exc_info()
    out = ConsoleFormatter().format(_make_record("boom", exc_info=exc_info))
    assert "boom" in out
    assert "Traceback" in out
    assert "ValueError" in out
    assert "kaboom" in out
