"""MinerU engine adapter implementing the ``Parser`` protocol.

Thin wrapper over the existing ``parse_pdf_to_workdir`` (local CLI / cloud
dispatch). The readiness gate (``readiness.py``) enforces "no silent model
download" before a local parse runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from .._versions import package_version
from .config import MinerUConfig, resolve_mineru_config
from .readiness import mineru_readiness


class MinerUParser:
    """PDF → multimodal ``content_list`` via the MinerU CLI or cloud API."""

    name = "mineru"
    needs_local_models = True

    @classmethod
    def is_available(cls) -> bool:
        # MinerU is an external CLI (local) or hosted API (cloud); the adapter
        # has no hard Python import. It is always "available" — readiness gates
        # whether a parse can actually run.
        return True

    def resolve_config(self) -> MinerUConfig:
        return resolve_mineru_config()

    def supported_formats(self) -> frozenset[str]:
        return frozenset({".pdf"})

    def signature(self, config: MinerUConfig) -> ParserSignature:
        version = f"cloud:{config.api_base_url}" if config.is_cloud else package_version("mineru")
        return ParserSignature.build(
            "mineru",
            version,
            {
                "mode": config.mode,
                "model_version": config.model_version,
                "language": config.language,
                "enable_formula": config.enable_formula,
                "enable_table": config.enable_table,
                "is_ocr": config.is_ocr,
            },
        )

    def is_ready(self, config: MinerUConfig) -> ReadinessReport:
        return mineru_readiness(config)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: MinerUConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        from .backend import parse_pdf_to_workdir

        # Writes ``<workdir>/<stem>/...`` (markdown + content_list + images);
        # ParseService loads the IR from ``workdir`` afterwards.
        parse_pdf_to_workdir(source_path, workdir, config=config, on_output=on_output)


__all__ = ["MinerUParser"]
