"""Tika engine adapter implementing the ``Parser`` protocol.

Remote-only: a Tika server extracts text, which is written as Markdown for the
canonical IR. There is no local package or model download.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from .config import TikaConfig, resolve_tika_config

_SUPPORTED = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".pptx",
        ".ppt",
        ".xlsx",
        ".xls",
        ".odt",
        ".ods",
        ".odp",
        ".html",
        ".htm",
        ".csv",
        ".json",
        ".xml",
        ".txt",
        ".md",
        ".rtf",
        ".epub",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".tif",
        ".tiff",
    }
)


class TikaParser:
    name = "tika"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    def resolve_config(self) -> TikaConfig:
        return resolve_tika_config()

    def supported_formats(self) -> frozenset[str]:
        return _SUPPORTED

    def signature(self, config: TikaConfig) -> ParserSignature:
        return ParserSignature.build("tika", f"remote:{config.server_url}", {})

    def is_ready(self, config: TikaConfig) -> ReadinessReport:
        if not (config.server_url or "").strip():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="Tika has no server URL configured.",
            )
        return ReadinessReport(ready=True)

    def verify(self, config: TikaConfig) -> tuple[bool, str]:
        """Live connectivity check for the Settings “Test” button."""
        from .remote import verify_remote

        return verify_remote(config)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: TikaConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        from .remote import parse_remote

        parse_remote(source_path, workdir, config=config, on_output=on_output)


__all__ = ["TikaParser"]
