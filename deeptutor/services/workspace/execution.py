"""Workspace-local environment for model-authored programs."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


def logicalize_workspace_text(value: str, workspace_root: str | Path | None) -> str:
    """Replace the physical workspace prefix with model-facing relative paths."""
    text = str(value or "")
    if not workspace_root:
        return text
    root = Path(workspace_root).expanduser().resolve()
    prefixes = {str(root), root.as_posix()}
    # A Windows subprocess can report either slash spelling regardless of the
    # spelling Python used to construct the path.
    prefixes.update({prefix.replace("\\", "/") for prefix in tuple(prefixes)})
    prefixes.update({prefix.replace("/", "\\") for prefix in tuple(prefixes)})
    for prefix in sorted(prefixes, key=len, reverse=True):
        text = text.replace(prefix + "/", "")
        text = text.replace(prefix + "\\", "")
        text = text.replace(prefix, ".")
    return text


def logical_workspace_path(path: str | Path, workspace_root: str | Path | None) -> str:
    """Return a POSIX workspace-relative path without leaking a host prefix."""
    candidate = Path(path).resolve()
    if not workspace_root:
        return candidate.name
    try:
        relative = candidate.relative_to(Path(workspace_root).expanduser().resolve())
    except ValueError:
        return candidate.name
    return PurePosixPath(*relative.parts).as_posix()


def prepare_workspace_execution_env(
    turn_output_dir: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, str]:
    """Return one shared execution environment for a turn.

    Source and shell modes deliberately receive the same package target, HOME,
    caches, and temporary directory. The caller also gives all exec calls in a
    turn one stable writable working directory, so later calls can revise files
    created by earlier calls.

    Mutable runtime files stay in a hidden directory under the turn output.
    That location is available to the isolated sidecar (which only mounts
    ``outputs/``), while workspace tools and artifact discovery exclude it.
    """
    turn_root = Path(turn_output_dir).expanduser().resolve()
    turn_root.mkdir(parents=True, exist_ok=True)
    root = turn_root / ".deeptutor" / "execution"
    cursor = turn_root
    for part in (".deeptutor", "execution"):
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("Workspace execution state cannot contain symbolic links.")
        cursor.mkdir(exist_ok=True)
    locations = {
        "home": root / "home",
        "tmp": root / "tmp",
        "cache": root / "cache",
        "python": root / "python-packages",
        "npm": root / "npm",
        "cargo": root / "cargo",
        "go": root / "go",
    }
    for path in locations.values():
        path.mkdir(parents=True, exist_ok=True)

    python_path = str(locations["python"])
    env = {
        "HOME": str(locations["home"]),
        "TMPDIR": str(locations["tmp"]),
        "TMP": str(locations["tmp"]),
        "TEMP": str(locations["tmp"]),
        "XDG_CACHE_HOME": str(locations["cache"]),
        "PIP_CACHE_DIR": str(locations["cache"] / "pip"),
        # PIP_TARGET makes a plain `pip install package` workspace-local even
        # when a source install is running DeepTutor from a writable venv.
        "PIP_TARGET": python_path,
        "PYTHONPATH": python_path,
        "PYTHONUSERBASE": str(root / "python-user"),
        "npm_config_cache": str(locations["cache"] / "npm"),
        "npm_config_prefix": str(locations["npm"]),
        "CARGO_HOME": str(locations["cargo"]),
        "GOPATH": str(locations["go"]),
        "HF_HOME": str(locations["cache"] / "huggingface"),
        "TORCH_HOME": str(locations["cache"] / "torch"),
        "MPLCONFIGDIR": str(locations["cache"] / "matplotlib"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if workspace_root:
        # A stable symbolic handle for model-authored code that needs to open
        # an existing binary workspace file. Prompts teach the model to append
        # an exact workspace-relative path and never reveal the physical value.
        env["DEEPTUTOR_WORKSPACE_ROOT"] = str(Path(workspace_root).expanduser().resolve())
    return env


__all__ = [
    "logical_workspace_path",
    "logicalize_workspace_text",
    "prepare_workspace_execution_env",
]
