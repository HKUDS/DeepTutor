# -*- coding: utf-8 -*-
"""
Logging Configuration
=====================

Unified logging configuration for the entire DeepTutor system.
A single `level` parameter controls all logging (including RAG modules).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class LoggingConfig:
    """Configuration for the logging system."""

    # Global log level (controls entire system including RAG modules)
    level: str = "DEBUG"

    # Output settings
    console_output: bool = True
    file_output: bool = True

    # Log directory (relative to project root or absolute)
    log_dir: Optional[str] = None

    # RAG module logger name mapping
    rag_logger_names: Optional[Dict[str, str]] = None

    # File rotation settings
    max_bytes: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


def get_default_log_dir() -> Path:
    """Get the default log directory."""
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "data" / "user" / "logs"


def get_global_log_level() -> str:
    """
    Get the global log level from config/main.yaml -> logging.level
    Default: DEBUG
    """
    try:
        from src.services.config import load_config_with_main

        project_root = Path(__file__).resolve().parent.parent.parent
        config = load_config_with_main("solve_config.yaml", project_root)
        logging_config = config.get("logging", {})
        return logging_config.get("level", "DEBUG").upper()
    except Exception:
        return "DEBUG"


def load_logging_config() -> LoggingConfig:
    """
    Load logging configuration from config files.

    Returns:
        LoggingConfig instance with loaded or default values.
    """
    try:
        from src.services.config import get_path_from_config, load_config_with_main

        project_root = Path(__file__).resolve().parent.parent.parent
        config = load_config_with_main("solve_config.yaml", project_root)

        logging_config = config.get("logging", {})
        level = get_global_log_level()

        return LoggingConfig(
            level=level,
            console_output=logging_config.get("console_output", True),
            file_output=logging_config.get("save_to_file", True),
            log_dir=get_path_from_config(config, "user_log_dir"),
            rag_logger_names=logging_config.get("rag_logger_names"),
        )
    except Exception:
        return LoggingConfig()
