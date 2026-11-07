#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
System Setup and Initialization
Combines user directory initialization and port configuration management.
"""

import json
import os
from pathlib import Path

from src.logging import get_logger
from src.services.path_service import get_path_service

# Initialize logger for setup operations
_setup_logger = None


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
    ├── agent/                    # All Agent interaction history
    │   ├── solve/
    │   ├── chat/
    │   ├── question/
    │   ├── research/
    │   │   └── reports/
    │   ├── co-writer/
    │   │   ├── audio/
    │   │   └── tool_calls/
    │   ├── guide/
    │   ├── run_code_workspace/
    │   └── logs/
    │
    ├── workspace/
    │   ├── notebook/
    │   └── memory/               # Personalization memory storage
    │
    └── settings/
        └── interface.json

    Args:
        project_root: Project root directory (ignored, kept for API compatibility)
    """
    # Use PathService for all paths
    path_service = get_path_service()
    
    # Only initialize essential configuration files
    # Directories will be created on-demand when files are saved
    _ensure_essential_settings(path_service)


def _ensure_essential_settings(path_service) -> None:
    """
    Ensure essential settings files exist.
    
    This is the minimal initialization needed at startup.
    All other directories are created on-demand when files are saved.
    """
    # Only create settings/interface.json if it doesn't exist
    # This is needed because it contains default UI settings
    interface_file = path_service.get_settings_file("interface")
    if not interface_file.exists():
        try:
            # Create settings directory
            interface_file.parent.mkdir(parents=True, exist_ok=True)
            # Create default interface settings
            initial_settings = {"theme": "light", "language": "en", "output_language": "en"}
            with open(interface_file, "w", encoding="utf-8") as f:
                json.dump(initial_settings, f, indent=2, ensure_ascii=False)
            logger = _get_setup_logger()
            logger.info(f"Created default settings: {interface_file}")
        except Exception as e:
            logger = _get_setup_logger()
            logger.warning(f"Failed to create settings/interface.json: {e}")


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
    env_port = os.environ.get("BACKEND_PORT", "8001")
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
    env_port = os.environ.get("FRONTEND_PORT", "3782")
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
