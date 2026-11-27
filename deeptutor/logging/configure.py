"""DeepTutor logging bootstrap."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from typing import TextIO

from deeptutor.utils.secret_files import ensure_private_directory, ensure_private_file

from .config import LoggingConfig, load_logging_config
from .formatters import ConsoleFormatter, ContextFilter, JsonlFormatter
from .loguru_bridge import install_loguru_bridge

_CONFIGURED = False
_MANAGED_ATTR = "_deeptutor_managed"


class TolerantRotatingFileHandler(RotatingFileHandler):
    """A ``RotatingFileHandler`` that keeps working when rollover fails.

    Two DeepTutor processes (the CLI launcher and the uvicorn server) can
    install a handler for the same log file. On Windows, renaming a file that
    another process still holds open fails with ``WinError 32``, and the stock
    handler then raises on every subsequent emit: records are dropped and
    stderr floods with ``--- Logging error ---`` tracebacks. When a rollover
    fails, this handler reopens the current file, writes a single warning to
    stderr, and lets the next emit retry the rotation.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._rollover_failure_warned = False

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except OSError:
            self._recover_from_failed_rollover()

    def _recover_from_failed_rollover(self) -> None:
        """Keep the handler usable after a failed rotation.

        ``doRollover`` closes the stream before renaming, so the current file
        must be reopened for subsequent records. The rotation is not marked as
        done: the next emit retries it and succeeds once the other process is
        gone.
        """
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                pass
            self.stream = None
        try:
            self.stream = self._open()
        except OSError:
            pass
        if not self._rollover_failure_warned:
            self._rollover_failure_warned = True
            sys.stderr.write(
                "--- Logging warning: log rotation failed; continuing with the "
                "current log file until it can be rotated ---\n"
            )


def _level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(getattr(logging, str(value).upper(), logging.INFO))


def _managed(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _MANAGED_ATTR, True)
    handler.addFilter(ContextFilter())
    return handler


def _remove_managed_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if getattr(handler, _MANAGED_ATTR, False):
            root.removeHandler(handler)
            handler.close()


def configure_logging(
    force: bool = False, *, console_stream: TextIO | None = None
) -> LoggingConfig:
    """Configure stdlib logging once for the whole process."""
    global _CONFIGURED

    config = load_logging_config()
    root = logging.getLogger()
    if _CONFIGURED and not force:
        return config

    if force:
        _remove_managed_handlers(root)

    level = _level(config.level)
    root.setLevel(logging.DEBUG)

    if config.console_output:
        console = _managed(
            logging.StreamHandler(console_stream if console_stream is not None else sys.stdout)
        )
        console.setLevel(level)
        console.setFormatter(ConsoleFormatter())
        root.addHandler(console)

    if config.file_output:
        log_dir = Path(config.log_dir) if config.log_dir else Path("data/user/logs")
        ensure_private_directory(log_dir)
        log_path = log_dir / "deeptutor.jsonl"
        file_handler = _managed(
            TolerantRotatingFileHandler(
                log_path,
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
                encoding="utf-8",
            )
        )
        ensure_private_file(log_path)
        file_handler.setLevel(level)
        file_handler.setFormatter(JsonlFormatter())
        root.addHandler(file_handler)

    logging.getLogger("deeptutor").setLevel(logging.DEBUG)
    logging.getLogger("deeptutor").propagate = True
    install_loguru_bridge(logging.DEBUG)
    _CONFIGURED = True
    return config
