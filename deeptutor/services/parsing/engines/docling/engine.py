"""Docling engine adapter implementing the ``Parser`` protocol.

Docling's structured conversion is exported to Markdown for the canonical IR.
Structured ``content_list`` mapping is intentionally deferred — markdown is a
valid IR (consumers fall back to it), and a faithful block mapping depends on
the Docling document API, which is best pinned when we wire LightRAG.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .._versions import package_version
from .config import DoclingConfig, resolve_docling_config
from .formats import (
    MIN_DOCLING_VERSION,
    docling_supported_formats,
    docling_version_is_current,
    installed_docling_version,
)

# HF cache dir-name substrings for Docling's layout/table models.
_MODEL_DIR_HINTS = ("docling", "ds4sd")


def _dir_nonempty(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except Exception:
        return False


def docling_models_dir() -> Path:
    """Docling's default model cache, where ``docling-tools models download``
    writes (honors the ``DOCLING_CACHE_DIR`` override; default ~/.cache/docling).

    Resolved without importing docling (heavy) so the readiness probe stays
    cheap — it mirrors docling's own ``settings.cache_dir / "models"``."""
    cache = os.environ.get("DOCLING_CACHE_DIR")
    base = Path(cache).expanduser() if cache else Path.home() / ".cache" / "docling"
    return base / "models"


def _docling_models_ready() -> bool:
    """Best-effort, fail-closed check for downloaded Docling models."""
    artifacts = os.environ.get("DOCLING_ARTIFACTS_PATH")
    if artifacts and _dir_nonempty(Path(artifacts).expanduser()):
        return True
    # The location `docling-tools models download` populates (and that docling
    # auto-loads from at parse time).
    if _dir_nonempty(docling_models_dir()):
        return True
    hf_home = os.environ.get("HF_HOME")
    hub = (
        Path(hf_home).expanduser() if hf_home else Path.home() / ".cache" / "huggingface"
    ) / "hub"
    try:
        if hub.is_dir():
            for child in hub.iterdir():
                name = child.name.lower()
                if (
                    child.is_dir()
                    and any(h in name for h in _MODEL_DIR_HINTS)
                    and any(child.iterdir())
                ):
                    return True
    except Exception:
        return False
    return False


class DoclingParser:
    name = "docling"
    needs_local_models = True

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("docling") is not None

    def resolve_config(self) -> DoclingConfig:
        return resolve_docling_config()

    def supported_formats(self) -> frozenset[str]:
        return docling_supported_formats()

    def signature(self, config: DoclingConfig) -> ParserSignature:
        version = package_version("docling")
        if config.is_remote:
            version = f"remote-{MIN_DOCLING_VERSION}:{config.api_base_url}"
        return ParserSignature.build(
            "docling",
            version,
            {"do_ocr": config.do_ocr, "do_table_structure": config.do_table_structure},
        )

    def is_ready(self, config: DoclingConfig) -> ReadinessReport:
        # Remote mode needs no local package or models.
        if config.is_remote:
            if not (config.api_base_url or "").strip():
                return ReadinessReport(
                    ready=False,
                    reason="not_configured",
                    message="Docling remote mode has no server URL configured.",
                )
            return ReadinessReport(ready=True)
        if not self.is_available():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="Docling isn't installed (pip install deeptutor[parse-docling]).",
            )
        installed_version = installed_docling_version()
        if not docling_version_is_current(installed_version):
            return ReadinessReport(
                ready=False,
                reason="update_required",
                message=(
                    f"Docling {installed_version or 'unknown'} is too old. DeepTutor needs "
                    f"Docling >= {MIN_DOCLING_VERSION} for the current document formats. "
                    "Use the package update button below."
                ),
            )
        if config.allow_local_model_download or _docling_models_ready():
            return ReadinessReport(ready=True)
        return ReadinessReport(
            ready=False,
            reason="models_missing",
            message=(
                "Docling models aren't downloaded. Enable “Allow automatic model "
                "download” in Settings → Document Parsing (or pre-fetch with "
                "`docling-tools models download`), or switch to text-only / markitdown."
            ),
        )

    def verify(self, config: DoclingConfig) -> tuple[bool, str]:
        """Live connectivity check for the Settings “Test” button (remote only).
        No-op for local mode."""
        if config.is_remote:
            from .remote import verify_remote

            return verify_remote(config)
        return self.is_ready(config).ready, ""

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: DoclingConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        if config.is_remote:
            from .remote import parse_remote

            parse_remote(source_path, workdir, config=config, on_output=on_output)
            return
        if on_output:
            on_output(f"Converting {Path(source_path).name} via Docling…")
        try:
            from .local_worker import parse_local

            parse_local(source_path, workdir, config=config, on_output=on_output)
        except Exception as exc:  # noqa: BLE001 - surface as a parser error
            raise ParserError(f"Docling failed to convert {Path(source_path).name}: {exc}")


__all__ = ["DoclingParser"]
