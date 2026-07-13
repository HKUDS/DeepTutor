"""MinerU model-readiness probe — the "no silent download" gate.

The MinerU CLI auto-downloads multi-GB model weights on first local parse, and
DeepTutor cannot stop the CLI itself from doing so. So the gate lives one level
up: a local parse is only allowed to start when models are already present *or*
the user explicitly enabled ``allow_local_model_download``. Detection is
best-effort and **fail-closed** — if we cannot confirm models exist, we treat
them as missing so the default stays "no download" (a false negative just costs
one extra click; a false positive would permit the silent pull we are avoiding).
"""

from __future__ import annotations

import os
from pathlib import Path

from ...base import ReadinessReport

# Substrings of HF/ModelScope cache dir names that indicate MinerU's weights.
_MODEL_DIR_HINTS = ("opendatalab", "mineru", "pdf-extract")


def _hf_hub_dir() -> Path:
    hf_home = os.environ.get("HF_HOME")
    base = Path(hf_home).expanduser() if hf_home else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def _modelscope_dir() -> Path:
    ms = os.environ.get("MODELSCOPE_CACHE")
    return Path(ms).expanduser() if ms else Path.home() / ".cache" / "modelscope" / "hub"


def mineru_models_ready(_source: str = "huggingface") -> bool:
    """Best-effort check for already-downloaded MinerU weights (fail-closed)."""
    for root in (_hf_hub_dir(), _modelscope_dir()):
        try:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                name = child.name.lower()
                if (
                    child.is_dir()
                    and any(hint in name for hint in _MODEL_DIR_HINTS)
                    and any(child.iterdir())
                ):
                    return True
        except Exception:
            continue
    return False


def mineru_readiness(config) -> ReadinessReport:
    """Whether a MinerU parse can run now under ``config``."""
    if config.is_cloud:
        if not (config.api_token or "").strip():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message=(
                    "MinerU cloud mode needs an API token. Add it under "
                    "Settings → Document Parsing, or switch to text-only / a local engine."
                ),
            )
        return ReadinessReport(ready=True)

    # Local mode.
    from .backend import local_cli_probe

    if not local_cli_probe(config.local_cli_path).get("found"):
        return ReadinessReport(
            ready=False,
            reason="cli_missing",
            message=(
                "MinerU CLI not found. Install it (`pip install mineru`), set its "
                "path in Settings → Document Parsing, or switch to text-only / "
                "cloud / markitdown."
            ),
        )

    if config.allow_local_model_download or mineru_models_ready(config.model_download_source):
        return ReadinessReport(ready=True)

    return ReadinessReport(
        ready=False,
        reason="models_missing",
        message=(
            "MinerU local models aren't downloaded. Click “Download models”, "
            "enable “Allow local model download”, or switch to text-only / cloud / "
            "markitdown in Settings → Document Parsing."
        ),
    )


__all__ = ["mineru_models_ready", "mineru_readiness"]
