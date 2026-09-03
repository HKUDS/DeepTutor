"""DeepTutor logging bootstrap."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from deeptutor.utils.secret_files import ensure_private_directory, ensure_private_file

from .config import LoggingConfig, load_logging_config
from .formatters import ConsoleFormatter, ContextFilter, JsonlFormatter
from .loguru_bridge import install_loguru_bridge

_CONFIGURED = False
_MANAGED_ATTR = "_deeptutor_managed"


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


def configure_logging(force: bool = False) -> LoggingConfig:
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
        console = _managed(logging.StreamHandler(sys.stdout))
        console.setLevel(level)
        console.setFormatter(ConsoleFormatter())
        root.addHandler(console)

    if config.file_output:
        log_dir = Path(config.log_dir) if config.log_dir else Path("data/user/logs")
        ensure_private_directory(log_dir)
        log_path = log_dir / "deeptutor.jsonl"
        file_handler = _managed(
            RotatingFileHandler(
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
