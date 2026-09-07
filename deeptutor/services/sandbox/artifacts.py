"""Artifact discovery for sandboxed exec workspaces."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

from deeptutor.services.path_service import PathService, get_path_service

ArtifactFileSignature = tuple[int, int, int]
ArtifactSnapshot = dict[str, ArtifactFileSignature]


def _visible_files(root: Path) -> Iterator[Path]:
    """Walk visible regular files without entering hidden or symlinked trees."""

    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for entry in entries:
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                except OSError:
                    continue


@dataclass(frozen=True, slots=True)
class SandboxArtifact:
    filename: str
    path: str
    relative_path: str
    url: str
    size_bytes: int
    mime_type: str

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "path": self.path,
            "relative_path": self.relative_path,
            "url": self.url,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
        }


@dataclass(frozen=True, slots=True)
class SandboxArtifactBatch:
    """A bounded artifact result that preserves the pre-limit count."""

    artifacts: tuple[SandboxArtifact, ...]
    total_count: int

    @property
    def truncated(self) -> bool:
        return self.total_count > len(self.artifacts)


def snapshot_public_artifact_files(workdir: str | Path) -> ArtifactSnapshot:
    """Capture visible file signatures before an execution call.

    The snapshot is deliberately workspace-agnostic: exposure checks still happen
    when artifacts are collected after execution. Hidden runtime files are omitted
    so source wrappers under ``.deeptutor`` never become user-facing artifacts.
    """

    root = Path(workdir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {}

    snapshot: ArtifactSnapshot = {}
    for file_path in _visible_files(root):
        try:
            relative = file_path.relative_to(root)
            stat = file_path.stat()
        except (OSError, ValueError):
            continue
        snapshot[relative.as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
    return snapshot


def collect_public_artifacts(
    workdir: str | Path,
    *,
    path_service: PathService | None = None,
    workspace_id: str = "",
    max_files: int = 50,
    changed_since: ArtifactSnapshot | None = None,
) -> list[SandboxArtifact]:
    """Return files under *workdir* that are safe to expose via /files/outputs."""

    return list(
        collect_public_artifact_batch(
            workdir,
            path_service=path_service,
            workspace_id=workspace_id,
            max_files=max_files,
            changed_since=changed_since,
        ).artifacts
    )


def collect_public_artifact_batch(
    workdir: str | Path,
    *,
    path_service: PathService | None = None,
    workspace_id: str = "",
    max_files: int = 50,
    changed_since: ArtifactSnapshot | None = None,
) -> SandboxArtifactBatch:
    """Collect exposed artifacts, optionally limited to a call-local delta."""

    root = Path(workdir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return SandboxArtifactBatch(artifacts=(), total_count=0)

    content_service = None
    binding = None
    if workspace_id:
        from deeptutor.services.workspace import get_content_workspace_service

        content_service = get_content_workspace_service()
        binding = content_service.binding_by_id(workspace_id)
        public_root = binding.root
    else:
        service = path_service or get_path_service()
        public_root = service.get_public_outputs_root().resolve()
    artifacts: list[SandboxArtifact] = []

    for file_path in _visible_files(root):
        try:
            relative = file_path.relative_to(root)
            stat = file_path.stat()
        except (OSError, ValueError):
            continue
        signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if changed_since is not None and changed_since.get(relative.as_posix()) == signature:
            continue
        if binding is not None and content_service is not None:
            try:
                rel_posix = content_service.relative_path(binding, file_path)
            except ValueError:
                continue
            if not rel_posix.startswith("outputs/"):
                continue
            url = ""
            exposed_path = rel_posix
        else:
            if not service.is_public_output_path(file_path):
                continue
            try:
                rel = file_path.resolve().relative_to(public_root)
            except ValueError:
                continue
            rel_posix = rel.as_posix()
            url = "/files/outputs/" + quote(rel_posix, safe="/")
            exposed_path = str(file_path.resolve())
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        artifacts.append(
            SandboxArtifact(
                filename=file_path.name,
                path=exposed_path,
                relative_path=rel_posix,
                url=url,
                size_bytes=stat.st_size,
                mime_type=mime_type,
            )
        )

    artifacts.sort(key=lambda artifact: artifact.relative_path)
    total_count = len(artifacts)
    bounded = tuple(artifacts[: max(0, max_files)])
    return SandboxArtifactBatch(artifacts=bounded, total_count=total_count)


def render_artifacts_for_tool(
    artifacts: list[SandboxArtifact] | tuple[SandboxArtifact, ...],
    *,
    already_presented: bool = False,
    total_count: int | None = None,
    empty_message: str = "No generated artifacts were found in the workspace.",
) -> str:
    """Compact model-facing artifact list with explicit presentation state."""

    if not artifacts:
        return empty_message
    lines = [
        (
            "Generated artifacts (saved and already presented to the user as openable snapshots):"
            if already_presented
            else "Generated artifacts (saved in the workspace, not yet presented):"
        ),
        *[
            f"- {artifact.relative_path} ({_format_bytes(artifact.size_bytes)})"
            for artifact in artifacts
        ],
        *(
            [f"- … {total_count - len(artifacts)} more changed artifacts were not listed."]
            if total_count is not None and total_count > len(artifacts)
            else []
        ),
        "",
        (
            "These files are already presented. Use the exact workspace-relative path shown "
            "above in Markdown; do not call workspace_present again for the same version and "
            "do not paste an internal download URL."
            if already_presented
            else (
                "Call workspace_present with each exact workspace-relative path above before "
                "linking it in Markdown. Only workspace_present makes the saved version "
                "openable to the user. Do not paste an internal download URL."
            )
        ),
    ]
    return "\n".join(lines)


def _format_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


__all__ = [
    "ArtifactSnapshot",
    "SandboxArtifact",
    "SandboxArtifactBatch",
    "collect_public_artifact_batch",
    "collect_public_artifacts",
    "render_artifacts_for_tool",
    "snapshot_public_artifact_files",
]
