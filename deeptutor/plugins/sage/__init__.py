"""SAGE memory companion plugin for DeepTutor."""

from deeptutor.plugins.sage.capability import (
    PRE_RUN_TARGETS,
    SageMemoryCompanion,
    install_hooks,
    uninstall_hooks,
)
from deeptutor.plugins.sage.client import SageClient, get_sage_client

__all__ = [
    "PRE_RUN_TARGETS",
    "SageClient",
    "SageMemoryCompanion",
    "get_sage_client",
    "install_hooks",
    "uninstall_hooks",
]
