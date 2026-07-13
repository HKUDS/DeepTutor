"""Artifact discovery for sandboxed exec workspaces."""

from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path
from urllib.parse import quote

from deeptutor.services.path_service import PathService, get_path_service


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


def collect_public_artifacts(
    workdir: str | Path,
    *,
    path_service: PathService | None = None,
    max_files: int = 50,
) -> list[SandboxArtifact]:
    """Return files under *workdir* that are safe to expose via /api/outputs."""

    root = Path(workdir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []

    service = path_service or get_path_service()
    public_root = service.get_public_outputs_root().resolve()
    artifacts: list[SandboxArtifact] = []

    for file_path in sorted(p for p in root.rglob("*") if p.is_file()):
        if any(part.startswith(".") for part in file_path.relative_to(root).parts):
            continue
        if not service.is_public_output_path(file_path):
            continue
        try:
            rel = file_path.resolve().relative_to(public_root)
        except ValueError:
            continue
        rel_posix = rel.as_posix()
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        artifacts.append(
            SandboxArtifact(
                filename=file_path.name,
                path=str(file_path.resolve()),
                relative_path=rel_posix,
                url="/api/outputs/" + quote(rel_posix, safe="/"),
                size_bytes=file_path.stat().st_size,
                mime_type=mime_type,
            )
        )
        if len(artifacts) >= max_files:
            break

    return artifacts


def render_artifacts_for_tool(artifacts: list[SandboxArtifact]) -> str:
    """Compact model-facing artifact list. The filename is the handle.

    Each file already shows to the user as a download card. On top of that, the
    UI turns any verbatim mention of one of these filenames in the reply into a
    clickable link that opens the file — so the model just has to write the
    exact filename, no special syntax or URL.
    """

    if not artifacts:
        return ""
    lines = [
        "Generated artifacts (now saved — shown to the user as download cards):",
        *[
            f"- {artifact.filename} ({_format_bytes(artifact.size_bytes)})"
            for artifact in artifacts
        ],
        "",
        "When you refer to one of these files in your reply, write its filename "
        "EXACTLY as listed above (verbatim, including the extension) as plain "
        "text — do NOT wrap it in a markdown link and do NOT paste a URL. The UI "
        "automatically turns the plain filename into a clickable link that opens "
        "the file. Describe what you made in plain language.",
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
    "SandboxArtifact",
    "collect_public_artifacts",
    "render_artifacts_for_tool",
]
