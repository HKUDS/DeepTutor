"""Inspect and clean reproducible Manim files without touching published media."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil

from .models import WorkspaceError, WorkspaceItem
from .service import ContentWorkspaceService


def _chat_exec_output(
    service: ContentWorkspaceService, workspace_id: str, item_id: str
) -> tuple[Path, WorkspaceItem]:
    _, item = service.resolve_published_item(workspace_id, item_id)
    parts = PurePosixPath(item.relative_path).parts
    direct_chat_output = (
        len(parts) == 5 and parts[:2] == ("outputs", "chat") and parts[3].startswith("turn_")
    )
    direct_exec_output = (
        len(parts) == 6
        and parts[:2] == ("outputs", "chat")
        and parts[3].startswith("turn_")
        and parts[4] == "exec"
    )
    if (
        not item.generated
        or not (
            direct_chat_output
            or direct_exec_output
            or (
                len(parts) >= 10
                and parts[:2] == ("outputs", "chat")
                and parts[3].startswith("turn_")
                and parts[4] == "exec"
                and parts[5] == "outputs"
                and parts[6] == "chat"
                and parts[8].startswith("turn_")
            )
        )
        or any(part in {".", ".."} for part in parts)
    ):
        raise WorkspaceError("Only generated chat tool outputs support file actions.")
    binding = service.binding_by_id(workspace_id)
    cursor = binding.root
    for part in parts:
        cursor /= part
        if cursor.is_symlink():
            raise WorkspaceError("Generated output paths cannot contain symbolic links.")
    path = service.resolve(binding, item.relative_path, write=True)
    if not path.is_file():
        raise WorkspaceError("The original generated file is unavailable.")
    return path, item


def inspect_chat_exec_output(
    service: ContentWorkspaceService, workspace_id: str, item_id: str
) -> dict:
    """Describe the workspace copy behind an immutable chat attachment."""
    path, item = _chat_exec_output(service, workspace_id, item_id)
    stat = path.stat()
    fingerprint = hashlib.sha256(
        f"{item.relative_path}\0{stat.st_size}\0{stat.st_mtime_ns}\0{stat.st_ino}".encode()
    ).hexdigest()
    return {"file_path": str(path), "file_bytes": stat.st_size, "fingerprint": fingerprint}


def remove_chat_exec_output(
    service: ContentWorkspaceService, workspace_id: str, item_id: str, fingerprint: str
) -> dict:
    """Remove one unchanged generated workspace copy, keeping its chat snapshot."""
    path, item = _chat_exec_output(service, workspace_id, item_id)
    preview = inspect_chat_exec_output(service, workspace_id, item_id)
    if preview["fingerprint"] != fingerprint:
        raise WorkspaceError("The generated file changed. Review its details again.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != item.sha256:
        raise WorkspaceError("The generated file differs from its chat attachment.")
    path.unlink()
    return {"removed": True, "file_bytes": preview["file_bytes"]}


def _render_paths(
    service: ContentWorkspaceService, workspace_id: str, item_id: str
) -> tuple[Path, Path]:
    _, item = service.resolve_published_item(workspace_id, item_id)
    parts = PurePosixPath(item.relative_path).parts
    if (
        not item.generated
        or len(parts) != 6
        or parts[:2] != ("outputs", "math_animator")
        or parts[4] != "artifacts"
        or any(part in {".", ".."} for part in parts)
    ):
        raise WorkspaceError("Only published Math Animator artifacts support render cleanup.")
    binding = service.binding_by_id(workspace_id)
    cursor = binding.root
    for part in parts:
        cursor /= part
        if cursor.is_symlink():
            raise WorkspaceError("Render storage cannot contain symbolic links.")
    artifact = service.resolve(binding, item.relative_path, write=True)
    if not artifact.is_file():
        raise WorkspaceError("The original artifact is unavailable; render files were preserved.")
    return artifact, artifact.parent.parent / "media"


def _inventory(media: Path) -> dict:
    if media.is_symlink():
        raise WorkspaceError("Render storage cannot contain symbolic links.")
    digest = hashlib.sha256()
    size = count = 0
    if media.exists():
        if not media.is_dir():
            raise WorkspaceError("Render storage is not a directory.")
        for parent, directories, files in os.walk(media, followlinks=False):
            for name in sorted(directories + files):
                path = Path(parent) / name
                if path.is_symlink():
                    raise WorkspaceError("Render storage cannot contain symbolic links.")
                stat = path.stat()
                digest.update(
                    f"{path.relative_to(media)}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode()
                )
                if path.is_file():
                    size += stat.st_size
                    count += 1
            directories.sort()
    return {"cache_bytes": size, "cache_files": count, "fingerprint": digest.hexdigest()}


def inspect_render_storage(
    service: ContentWorkspaceService, workspace_id: str, item_id: str
) -> dict:
    """Describe one published artifact and its rebuildable render directory."""
    artifact, media = _render_paths(service, workspace_id, item_id)
    return {
        "file_path": str(artifact),
        "file_bytes": artifact.stat().st_size,
        "cache_path": str(media),
        **_inventory(media),
    }


def clean_render_storage(
    service: ContentWorkspaceService, workspace_id: str, item_id: str, fingerprint: str
) -> dict:
    """Delete only the unchanged media directory from an approved preview."""
    artifact, media = _render_paths(service, workspace_id, item_id)
    preview = _inventory(media)
    if preview["fingerprint"] != fingerprint:
        raise WorkspaceError("Render files changed. Review the storage preview again.")
    # media 包含分段、字体缓存和渲染副本；最终产物位于相邻的 artifacts 目录。
    if media.exists():
        shutil.rmtree(media)
    return {
        "file_path": str(artifact),
        "freed_bytes": preview["cache_bytes"],
        "removed_files": preview["cache_files"],
        **_inventory(media),
    }
