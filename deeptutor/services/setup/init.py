#!/usr/bin/env python
"""
System Setup and Initialization
Combines user directory initialization and port configuration management.
"""

import json
import logging
from pathlib import Path

import yaml

from deeptutor.services.path_service import get_path_service

# Initialize logger for setup operations
_setup_logger = None

DEFAULT_INTERFACE_SETTINGS = {
    # "snow" is the pure-white neutral theme, shown as "Default" in the UI.
    "theme": "snow",
    "language": "en",
    "sidebar_description": "✨ Data Intelligence Lab @ HKU",
    "sidebar_nav_order": {
        "start": ["/", "/history", "/knowledge", "/notebook"],
        "learnResearch": ["/question", "/solver", "/research", "/co_writer"],
    },
}

DEFAULT_MAIN_SETTINGS = {
    "system": {
        "language": "en",
    },
    "logging": {
        "level": "WARNING",
        "save_to_file": True,
        "console_output": True,
    },
    "tools": {
        "run_code": {
            "allowed_roots": ["./data/user"],
        },
        "web_search": {
            "enabled": True,
        },
    },
    "capabilities": {
        "solve": {
            "max_rounds": 12,
            "max_replans": 2,
        },
        "research": {
            "researching": {
                "note_agent_mode": "auto",
                "tool_timeout": 60,
                "tool_max_retries": 2,
                "paper_search_years_limit": 3,
            },
        },
        "question": {
            "exploring": {
                "max_iterations": 8,
                "tool_summarizer": {
                    "enabled": True,
                    "max_tokens": 800,
                },
            },
        },
    },
}

DEFAULT_AGENTS_SETTINGS = {
    "capabilities": {
        "solve": {"temperature": 0.3, "max_tokens": 8192},
        "research": {"temperature": 0.5, "max_tokens": 12000},
        "question": {"temperature": 0.7, "max_tokens": 4096},
        "co_writer": {"temperature": 0.7, "max_tokens": 4096},
        "visualize": {"temperature": 0.4, "max_tokens": 16384},
        "chat": {
            "temperature": 0.2,
            "responding": {"max_tokens": 8000},
        },
    },
    "tools": {
        "brainstorm": {"temperature": 0.8, "max_tokens": 2048},
    },
    "services": {
        "personalization": {"temperature": 0.5, "max_tokens": 8192},
    },
    "plugins": {
        "vision_solver": {"temperature": 0.3, "max_tokens": 12000},
        "math_animator": {"temperature": 0.4, "max_tokens": 12000},
    },
}


def _get_setup_logger():
    """Get logger for setup operations"""
    global _setup_logger
    if _setup_logger is None:
        _setup_logger = logging.getLogger(__name__)
    return _setup_logger


# ============================================================================
# User Directory Initialization
# ============================================================================


def init_user_directories(project_root: Path | None = None) -> None:
    """
    Initialize essential user data files if they don't exist.

    This function uses lazy initialization - directories are created on-demand
    when files are saved, rather than pre-creating all directories at startup.

    Only essential configuration files (like settings/interface.json) are
    created at startup if they don't exist.

    Directory structure (created on-demand by each module):
    data/user/
    ├── chat_history.db
    ├── logs/
    ├── settings/
    │   ├── interface.json
    │   ├── main.yaml
    │   └── agents.yaml
    └── workspace/
        ├── notebook/
        ├── memory/
        ├── co-writer/
        ├── book/
        └── chat/
            ├── chat/
            ├── deep_solve/
            ├── deep_question/
            ├── deep_research/
            ├── math_animator/
            └── _detached_code_execution/

    Args:
        project_root: Project root directory (ignored, kept for API compatibility)
    """
    # Use PathService for all paths
    path_service = get_path_service()
    path_service.ensure_all_directories()

    # Only initialize essential configuration files
    # Directories will be created on-demand when files are saved
    _ensure_essential_settings(path_service)


def _ensure_essential_settings(path_service) -> None:
    """
    Ensure essential settings files exist.

    This is the minimal initialization needed at startup.
    All other directories are created on-demand when files are saved.
    """
    interface_file = path_service.get_settings_file("interface")
    _write_json_if_missing(interface_file, DEFAULT_INTERFACE_SETTINGS)

    main_file = path_service.get_runtime_config_file("main")
    _write_yaml_if_missing(main_file, DEFAULT_MAIN_SETTINGS)

    agents_file = path_service.get_runtime_config_file("agents")
    _write_yaml_if_missing(agents_file, DEFAULT_AGENTS_SETTINGS)

    try:
        from deeptutor.services.config import ensure_runtime_settings_files

        ensure_runtime_settings_files()
    except Exception as e:
        _get_setup_logger().warning(f"Failed to initialise runtime JSON settings: {e}")


def _write_json_if_missing(file_path: Path, payload: dict) -> None:
    """Write JSON defaults once; never overwrite user-managed files."""
    if file_path.exists():
        return
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        _get_setup_logger().info(f"Created default settings: {file_path}")
    except Exception as e:
        _get_setup_logger().warning(f"Failed to create default JSON file {file_path}: {e}")


def _write_yaml_if_missing(file_path: Path, payload: dict) -> None:
    """Write YAML defaults once; never overwrite user-managed files."""
    if file_path.exists():
        return
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        _get_setup_logger().info(f"Created default settings: {file_path}")
    except Exception as e:
        _get_setup_logger().warning(f"Failed to create default YAML file {file_path}: {e}")


# ============================================================================
# Port Configuration Management
# ============================================================================
# Ports are configured via data/user/settings/system.json.
# ============================================================================


def get_backend_port(project_root: Path | None = None) -> int:
    """
    Get backend port from runtime settings.

    Returns:
        Backend port number (default: 8001)
    """
    try:
        from deeptutor.services.config.launch_settings import load_launch_settings

        return load_launch_settings(project_root).backend_port
    except Exception as exc:
        logger = _get_setup_logger()
        logger.warning(f"Failed to load backend port from runtime settings: {exc}")
        return 8001


def get_frontend_port(project_root: Path | None = None) -> int:
    """
    Get frontend port from runtime settings.

    Returns:
        Frontend port number (default: 3782)
    """
    try:
        from deeptutor.services.config.launch_settings import load_launch_settings

        return load_launch_settings(project_root).frontend_port
    except Exception as exc:
        logger = _get_setup_logger()
        logger.warning(f"Failed to load frontend port from runtime settings: {exc}")
        return 3782


def get_ports(project_root: Path | None = None) -> tuple[int, int]:
    """
    Get both backend and frontend ports from configuration.

    Args:
        project_root: Project root directory (if None, will try to detect)

    Returns:
        Tuple of (backend_port, frontend_port)

    Raises:
        SystemExit: If ports are not configured
    """
    backend_port = get_backend_port(project_root)
    frontend_port = get_frontend_port(project_root)
    return (backend_port, frontend_port)


__all__ = [
    # User directory initialization
    "init_user_directories",
    # Port configuration
    "get_backend_port",
    "get_frontend_port",
    "get_ports",
]
