"""
Setup Service
=============

System setup and initialization for DeepTutor.

Port configuration is done via data/user/settings/system.json.

Usage:
    from deeptutor.services.setup import init_user_directories, get_backend_port

    # Initialize user directories
    init_user_directories()

    # Get server ports
    backend_port = get_backend_port()
    frontend_port = get_frontend_port()
"""

from .init import (
    get_backend_port,
    get_frontend_port,
    get_ports,
    init_user_directories,
)

__all__ = [
    "init_user_directories",
    "get_backend_port",
    "get_frontend_port",
    "get_ports",
]
