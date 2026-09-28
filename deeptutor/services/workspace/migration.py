"""Copy, verify and activate workspace locations without deleting source data."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any
import uuid


def _manifest(root: Path) -> dict[str, tuple[str, str]]:
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = ("link", os.readlink(path))
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                result[relative] = ("file", digest.hexdigest())
            elif path.is_dir():
                result[relative] = ("directory", "")
            else:
                raise ValueError(f"Cannot migrate special file: {relative}")
    return result


def migrate_locations(
    service: Any, moves: list[tuple[dict, Path]], *, new_root: Path | None = None
) -> None:
    from deeptutor.services.workspace.models import WorkspaceError

    prepared: list[tuple[dict, Path]] = []
    owned_destinations: list[Path] = []
    staging: list[Path] = []
    try:
        for row, destination in moves:
            source = Path(row["path"]).resolve()
            destination = destination.expanduser().resolve()
            if source == destination:
                continue
            service._assert_allowed_root(destination)
            if not source.is_dir():
                raise WorkspaceError("The source workspace folder does not exist.")
            if destination.is_relative_to(source) or source.is_relative_to(destination):
                raise WorkspaceError("Source and destination folders cannot contain one another.")
            if destination.exists():
                raise WorkspaceError(
                    "The destination already exists. Choose a new folder to avoid overwriting files."
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.parent / f".{destination.name}.migrate-{uuid.uuid4().hex}"
            staging.append(temporary)
            before = _manifest(source)
            shutil.copytree(source, temporary, symlinks=True)
            if before != _manifest(temporary) or before != _manifest(source):
                raise WorkspaceError(
                    "Workspace files changed during migration. Retry when file writes have stopped."
                )
            # Renaming a fresh sibling directory activates the complete copy.
            temporary.rename(destination)
            staging.remove(temporary)
            owned_destinations.append(destination)
            prepared.append((row, destination))
        # All paths switch together. A failure before commit leaves every old
        # binding valid; immutable published-item URLs are outside these roots.
        with service._catalog_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for row, destination in prepared:
                record = conn.execute(
                    "SELECT payload FROM workspaces WHERE id = ?", (row["workspace_id"],)
                ).fetchone()
                current = json.loads(record[0]) if record else None
                if current is None or current["path"] != row["path"]:
                    raise WorkspaceError(
                        "Workspace location changed during migration. Retry the operation."
                    )
                updated = {
                    **current,
                    "path": str(destination),
                    "follows_root": new_root is not None,
                    "previous_paths": [*row.get("previous_paths", []), row["path"]],
                }
                conn.execute(
                    "UPDATE workspaces SET payload = ? WHERE id = ?",
                    (json.dumps(updated, ensure_ascii=False), row["workspace_id"]),
                )
            if new_root is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO metadata VALUES ('root', ?)",
                    (json.dumps(str(new_root)),),
                )
    except Exception:
        for path in staging + owned_destinations:
            if path.exists():
                shutil.rmtree(path)
        raise
