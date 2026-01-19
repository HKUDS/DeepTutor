# -*- coding: utf-8 -*-
"""
File Log Handlers
=================

File-based logging with rotation support.
"""

import asyncio
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler as BaseRotatingFileHandler
from pathlib import Path
from typing import Optional

# Import FileFormatter from the main logger module to avoid duplication
from ..logger import FileFormatter


class FileHandler(logging.FileHandler):
    """
    File handler with detailed formatting.
    """

    def __init__(
        self,
        filename: str,
        level: int = logging.DEBUG,
        encoding: str = "utf-8",
    ):
        """
        Initialize file handler.

        Args:
            filename: Path to log file
            level: Minimum log level
            encoding: File encoding
        """
        # Ensure directory exists
        Path(filename).parent.mkdir(parents=True, exist_ok=True)

        super().__init__(filename, encoding=encoding)
        self.setLevel(level)
        self.setFormatter(FileFormatter())


class RotatingFileHandler(BaseRotatingFileHandler):
    """
    Rotating file handler with size-based rotation.
    """

    def __init__(
        self,
        filename: str,
        level: int = logging.DEBUG,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        encoding: str = "utf-8",
    ):
        """
        Initialize rotating file handler.

        Args:
            filename: Path to log file
            level: Minimum log level
            max_bytes: Maximum file size before rotation
            backup_count: Number of backup files to keep
            encoding: File encoding
        """
        # Ensure directory exists
        Path(filename).parent.mkdir(parents=True, exist_ok=True)

        super().__init__(
            filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
        )
        self.setLevel(level)
        self.setFormatter(FileFormatter())


class JSONFileHandler(logging.Handler):
    """
    A logging handler that writes structured JSON logs to a file.
    Each line is a valid JSON object (JSONL format).

    Useful for:
    - LLM call logging
    - Structured analysis
    - Log parsing and analysis
    """

    def __init__(
        self,
        filepath: str,
        level: int = logging.DEBUG,
        encoding: str = "utf-8",
    ):
        """
        Initialize JSON file handler.

        Args:
            filepath: Path to log file
            level: Minimum log level
            encoding: File encoding
        """
        super().__init__()

        # Ensure directory exists
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        self.filepath = filepath
        self.encoding = encoding
        self.setLevel(level)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord):
        """Emit a log record as JSON."""
        try:
            # Build JSON entry
            entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "module": getattr(record, "module_name", record.name),
                "message": self.format(record),
            }

            # Add extra fields if present
            for key in ["display_level", "tool_name", "elapsed_ms", "tokens"]:
                if hasattr(record, key):
                    entry[key] = getattr(record, key)

            # Write to file
            with open(self.filepath, "a", encoding=self.encoding) as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        except Exception:
            self.handleError(record)


def create_task_logger(
    task_id: str,
    module_name: str,
    log_dir: str,
    queue: Optional["asyncio.Queue"] = None,
) -> logging.Logger:
    """
    Create a logger for a specific task with file and optional WebSocket output.

    Args:
        task_id: Unique task identifier
        module_name: Module name (e.g., "Solver", "Research")
        log_dir: Directory for log files
        queue: Optional asyncio.Queue for WebSocket streaming

    Returns:
        Configured logger
    """
    from .websocket import WebSocketLogHandler

    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Create logger
    logger = logging.getLogger(f"deeptutor.{module_name}.{task_id}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    # File handler
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"{module_name}_{task_id}_{timestamp}.log"

    file_handler = FileHandler(str(log_file))
    logger.addHandler(file_handler)

    # WebSocket handler if queue provided
    if queue is not None:
        ws_handler = WebSocketLogHandler(queue)
        ws_handler.setLevel(logging.INFO)
        logger.addHandler(ws_handler)

    return logger
