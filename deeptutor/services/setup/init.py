#!/usr/bin/env python
"""
System Setup and Initialization
Combines user directory initialization and port configuration management.
"""

import json
from pathlib import Path

import yaml

from deeptutor.logging import get_logger
from deeptutor.services.config import get_env_store
from deeptutor.services.path_service import get_path_service

# Initialize logger for setup operations
_setup_logger = None

DEFAULT_INTERFACE_SETTINGS = {
    "theme": "light",
    "language": "en",
    "sidebar_description": "✨ Data Intelligence Lab @ HKU",
    "sidebar_nav_order": {
        "start": ["/", "/history", "/knowledge", "/notebook"],
        "learnResearch": ["/question", "/solver", "/guide", "/research", "/co_writer"],
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
    "personalization": {
        "auto_update": True,
        "max_react_rounds": 6,
        "agents": {
            "reflection": True,
            "summary": True,
            "weakness": True,
        },
    },
    "tools": {
        "run_code": {
            "allowed_roots": ["./data/user"],
        },
        "web_search": {
            "enabled": True,
            "consolidation": "template",
            "consolidation_template": "",
        },
    },
    "capabilities": {
        "question": {
            "rag_query_count": 3,
            "max_parallel_questions": 1,
            "idea_loop": {"max_rounds": 3, "ideas_per_round": 5},
            "generation": {"max_retries": 2},
        },
        "solve": {
            "max_react_iterations": 10,
            "max_plan_steps": 10,
            "max_replans": 2,
            "observation_max_tokens": 2000,
            "enable_citations": True,
            "save_intermediate_results": True,
            "detailed_answer": True,
        },
        "research": {
            "researching": {
                "note_agent_mode": "auto",
                "tool_timeout": 60,
                "tool_max_retries": 2,
                "paper_search_years_limit": 3,
            },
            "rag": {},
        },
    },
}

DEFAULT_AGENTS_SETTINGS = {
    "capabilities": {
        "solve": {"temperature": 0.3, "max_tokens": 8192},
        "research": {"temperature": 0.5, "max_tokens": 12000},
        "question": {"temperature": 0.7, "max_tokens": 4096},
        "guide": {"temperature": 0.5, "max_tokens": 16192},
        "co_writer": {"temperature": 0.7, "max_tokens": 4096},
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
        _setup_logger = get_logger("Setup")
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
        ├── guide/
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
# Ports are configured via environment variables in .env file:
#   BACKEND_PORT=8001   (default: 8001)
#   FRONTEND_PORT=3782  (default: 3782)
# ============================================================================


def get_backend_port(project_root: Path | None = None) -> int:
    """
    Get backend port from environment variable.

    Configure in .env file: BACKEND_PORT=8001

    Returns:
        Backend port number (default: 8001)
    """
    env_port = get_env_store().get("BACKEND_PORT", "8001")
    try:
        return int(env_port)
    except ValueError:
        logger = _get_setup_logger()
        logger.warning(f"Invalid BACKEND_PORT: {env_port}, using default 8001")
        return 8001


def get_frontend_port(project_root: Path | None = None) -> int:
    """
    Get frontend port from environment variable.

    Configure in .env file: FRONTEND_PORT=3782

    Returns:
        Frontend port number (default: 3782)
    """
    env_port = get_env_store().get("FRONTEND_PORT", "3782")
    try:
        return int(env_port)
    except ValueError:
        logger = _get_setup_logger()
        logger.warning(f"Invalid FRONTEND_PORT: {env_port}, using default 3782")
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
    # Port configuration (from .env)
    "get_backend_port",
    "get_frontend_port",
    "get_ports",
]
