"""Resolved MinerU backend configuration.

This is the single read-side adapter between the persisted
``document_parsing.json`` settings (owned by :class:`RuntimeSettingsService`)
and the MinerU parser
backend in this package. ``load_mineru_settings`` returns the MinerU engine
slice of the v2 document-parsing structure, so this resolver stays unchanged in
shape. The parser code never touches the storage shape directly — it asks for a
:class:`MinerUConfig` and gets validated, ready-to-use values.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import (
    MINERU_MODE_CLOUD,
    MINERU_MODE_LOCAL,
    load_mineru_settings,
)


class MinerUError(RuntimeError):
    """Raised when a MinerU parse fails (local CLI missing, cloud API error,
    misconfiguration). Carries a user-facing message; the capability layer
    surfaces it as a stream error."""


@dataclass(frozen=True)
class MinerUConfig:
    """Validated MinerU parsing configuration.

    ``mode`` is one of ``"local"`` / ``"cloud"``. The cloud branch additionally
    requires ``api_token``; the remaining fields are parsing knobs both
    backends understand (the local CLI ignores the ones it doesn't support).
    """

    mode: str = MINERU_MODE_LOCAL
    api_base_url: str = "https://mineru.net"
    api_token: str = ""
    # Explicit path to a local MinerU executable; "" = auto-detect from PATH.
    local_cli_path: str = ""
    # Local-mode model weight download source + optional custom address
    # (HF_ENDPOINT mirror; "" = the source's official address).
    model_download_source: str = "huggingface"
    model_download_endpoint: str = ""
    model_version: str = "pipeline"
    language: str = "auto"
    enable_formula: bool = True
    enable_table: bool = True
    is_ocr: bool = False
    # When False (default), a local parse fails fast instead of letting the
    # MinerU CLI silently download multi-GB model weights on first run. The user
    # opts in explicitly (Settings → Document Parsing) or via the one-click
    # download button. Cloud mode ignores this (no local models).
    allow_local_model_download: bool = False

    @property
    def is_cloud(self) -> bool:
        return self.mode == MINERU_MODE_CLOUD

    @property
    def is_local(self) -> bool:
        return self.mode == MINERU_MODE_LOCAL

    @property
    def api_language(self) -> str | None:
        """API ``language`` hint. ``"auto"`` maps to ``None`` (let MinerU
        auto-detect) so callers can drop the field from the request body."""
        return None if self.language.lower() == "auto" else self.language


def resolve_mineru_config() -> MinerUConfig:
    """Load the effective MinerU config from ``document_parsing.json`` (+ env overrides)."""
    settings = load_mineru_settings()
    return MinerUConfig(
        mode=str(settings.get("mode") or MINERU_MODE_LOCAL),
        api_base_url=str(settings.get("api_base_url") or "https://mineru.net"),
        api_token=str(settings.get("api_token") or ""),
        local_cli_path=str(settings.get("local_cli_path") or ""),
        model_download_source=str(settings.get("model_download_source") or "huggingface"),
        model_download_endpoint=str(settings.get("model_download_endpoint") or ""),
        model_version=str(settings.get("model_version") or "pipeline"),
        language=str(settings.get("language") or "auto"),
        enable_formula=bool(settings.get("enable_formula", True)),
        enable_table=bool(settings.get("enable_table", True)),
        is_ocr=bool(settings.get("is_ocr", False)),
        allow_local_model_download=bool(settings.get("allow_local_model_download", False)),
    )


__all__ = ["MinerUConfig", "MinerUError", "resolve_mineru_config"]
