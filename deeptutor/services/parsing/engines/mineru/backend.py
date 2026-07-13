"""Unified MinerU parsing entrypoint.

Hides the local-CLI vs cloud-API split behind one function so callers (the
mimic-mode adapter) never branch on backend. Both branches converge on the
same contract: write MinerU artifacts into a working directory and return its
path. Backend selection comes from ``document_parsing.json`` via
:func:`resolve_mineru_config`.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .config import (
    MinerUConfig,
    MinerUError,
    resolve_mineru_config,
)

logger = logging.getLogger(__name__)

# PATH-lookup order matches ``check_mineru_installed`` in local.py so the
# probe reports the same command the parse subprocess will actually use.
_LOCAL_CLI_COMMANDS = ("magic-pdf", "mineru")


def parse_pdf_to_workdir(
    pdf_path: str | Path,
    output_base: str | Path,
    *,
    config: MinerUConfig | None = None,
    on_output: Callable[[str], None] | None = None,
) -> Path:
    """Parse ``pdf_path`` and return the directory holding MinerU artifacts.

    The returned directory contains the parsed markdown +
    ``*_content_list.json`` (+ ``images/``) in whichever layout the active
    backend produces; :func:`load_parsed_paper` locates the content
    sub-directory regardless. ``on_output`` (if given) receives short progress
    lines from whichever backend runs — raw CLI output locally, task-state
    summaries from the cloud poller. Raises :class:`MinerUError` on failure.
    """
    cfg = config or resolve_mineru_config()
    pdf_path = Path(pdf_path)
    output_base = Path(output_base)
    output_base.mkdir(parents=True, exist_ok=True)

    if cfg.is_cloud:
        from .cloud import parse_cloud

        logger.info("Parsing %s via MinerU cloud API", pdf_path.name)
        return parse_cloud(pdf_path, output_base, cfg, on_progress=on_output)

    return _parse_local(pdf_path, output_base, config=cfg, on_output=on_output)


def local_cli_probe(configured_path: str = "") -> dict[str, Any]:
    """Fast (no-subprocess) check for a local MinerU CLI.

    ``configured_path`` (the ``local_cli_path`` setting) takes precedence over
    PATH lookup so MinerU can live in an isolated env (uv tool / pipx /
    separate conda) without PATH games. Returns ``{found, command, path,
    source}`` where ``source`` is ``"configured"`` or ``"path"``. Cheap enough
    to run on every settings GET; the slower ``--version`` confirmation lives
    in :func:`local_cli_version` and only runs behind the explicit Test button.
    """
    configured = (configured_path or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        found = candidate.is_file() and os.access(candidate, os.X_OK)
        return {
            "found": found,
            "command": candidate.name,
            "path": str(candidate),
            "source": "configured",
        }
    for command in _LOCAL_CLI_COMMANDS:
        path = shutil.which(command)
        if path:
            return {"found": True, "command": command, "path": path, "source": "path"}
    return {"found": False, "command": "", "path": "", "source": "path"}


def local_cli_version(command: str, timeout: float = 60.0) -> str:
    """Run ``<command> --version`` and return the first output line ("" on any
    failure). ``command`` must be a whitelisted name or an existing executable
    path (the validated ``local_cli_path``) — anything else is refused. Heavy
    CLIs import slowly on first run, hence kept out of the settings GET path."""
    if command not in _LOCAL_CLI_COMMANDS:
        candidate = Path(command).expanduser()
        if not (candidate.is_file() and os.access(candidate, os.X_OK)):
            return ""
        command = str(candidate)
    try:
        result = subprocess.run(  # nosec B603 — whitelisted name or validated executable
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0][:120] if output else ""


def _parse_local(
    pdf_path: Path,
    output_base: Path,
    *,
    config: MinerUConfig,
    on_output: Callable[[str], None] | None = None,
) -> Path:
    """Local-CLI branch: delegate to the existing subprocess parser and return
    the deterministic output directory it writes to (``<base>/<stem>``)."""
    from .local import parse_pdf_with_mineru
    from .models import model_env_overrides

    cli_command = None
    if (config.local_cli_path or "").strip():
        probe = local_cli_probe(config.local_cli_path)
        if not probe["found"]:
            raise MinerUError(
                f"Configured MinerU CLI path is not an executable file: {probe['path']}. "
                "Fix it in Settings → MinerU (or clear it to auto-detect from PATH)."
            )
        cli_command = probe["path"]

    # A lazy first-parse model download must honor the configured source and
    # custom address, not just the explicit Download button.
    download_env = model_env_overrides(config.model_download_source, config.model_download_endpoint)

    logger.info("Parsing %s via local MinerU CLI (%s)", pdf_path.name, cli_command or "PATH")
    ok = parse_pdf_with_mineru(
        str(pdf_path),
        str(output_base),
        on_output=on_output,
        cli_command=cli_command,
        extra_env=download_env,
    )
    if not ok:
        raise MinerUError(
            "Local MinerU parsing failed. Ensure MinerU is installed "
            "(`pip install mineru`) or switch to cloud mode in Settings → MinerU."
        )
    working_dir = output_base / pdf_path.stem
    if not working_dir.is_dir():
        # Defensive: the CLI names its output dir after the PDF stem, but fall
        # back to the newest sub-directory if that assumption ever breaks.
        subdirs = sorted(
            (d for d in output_base.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not subdirs:
            raise MinerUError("MinerU produced no output directory.")
        working_dir = subdirs[0]
    return working_dir


__all__ = ["MinerUError", "local_cli_probe", "local_cli_version", "parse_pdf_to_workdir"]
