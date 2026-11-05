"""Read-only server folder navigation for the workspace picker."""

from __future__ import annotations

import os
from pathlib import Path

from .models import WorkspaceError
from .service import ContentWorkspaceService


def browse_folders(service: ContentWorkspaceService, path: str = "") -> dict:
    """List readable subfolders within the requesting user's browsing roots."""
    configured = os.environ.get("DEEPTUTOR_WORKSPACE_BROWSER_ROOTS", "").strip()
    candidates = (
        [Path(value).expanduser().resolve() for value in configured.split(os.pathsep) if value]
        if configured
        else list(service._allowed_roots())
    )
    roots = []
    for root in candidates:
        try:
            service._assert_allowed_root(root)
            if root.is_dir() and os.access(root, os.R_OK | os.X_OK) and root not in roots:
                roots.append(root)
        except (WorkspaceError, OSError):
            continue
    if not roots:
        raise WorkspaceError("No browsable workspace folders are configured.")
    try:
        if "\x00" in path:
            raise ValueError("Invalid path")
        current = Path(path).expanduser().resolve() if path else roots[0]
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkspaceError("The server folder path is invalid.") from exc
    # Picker confinement applies even to admins. Resolve symlinks before checking.
    containing = [root for root in roots if current.is_relative_to(root)]
    if not containing:
        raise WorkspaceError("This folder is outside the configured browsing roots.")
    root = max(containing, key=lambda item: len(item.parts))
    folders = []
    scanned = 0
    try:
        with os.scandir(current) as entries:
            for entry in entries:
                scanned += 1
                if scanned > 10000:
                    break
                if entry.name.startswith("."):
                    continue
                try:
                    target = Path(entry.path).resolve()
                    if (
                        entry.is_dir()
                        and target != current
                        and target.is_relative_to(root)
                        and os.access(target, os.R_OK | os.X_OK)
                    ):
                        folders.append({"name": entry.name, "path": str(target)})
                except (OSError, RuntimeError):
                    continue
    except OSError as exc:
        raise WorkspaceError("The selected server folder cannot be opened.") from exc
    folders.sort(key=lambda entry: (entry["name"].casefold(), entry["name"]))
    return {
        "roots": [{"name": item.name or str(item), "path": str(item)} for item in roots],
        "path": str(current),
        "name": current.name or str(current),
        "parent": str(current.parent) if current != root else None,
        "folders": folders[:500],
        "truncated": len(folders) > 500 or scanned > 10000,
    }
