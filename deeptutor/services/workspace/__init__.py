"""User-selected content workspace.

Durable private data (settings, databases, memory, knowledge bases, logs, and
presentation snapshots) remains owned by ``PathService``. Short-lived sandbox
state uses a protected ``.deeptutor`` directory below each turn output so the
isolated sidecar can access it; workspace tools and artifact discovery hide it.
"""

from .service import (
    ContentWorkspaceService,
    WorkspaceBinding,
    WorkspaceError,
    WorkspaceItem,
    get_content_workspace_service,
)

__all__ = [
    "ContentWorkspaceService",
    "WorkspaceBinding",
    "WorkspaceError",
    "WorkspaceItem",
    "get_content_workspace_service",
]
