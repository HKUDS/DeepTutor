"""markitdown engine adapter implementing the ``Parser`` protocol."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .._versions import package_version
from .config import MarkItDownConfig, resolve_markitdown_config
from .formats import (
    MIN_MARKITDOWN_VERSION,
    installed_markitdown_version,
    markitdown_supported_formats,
    markitdown_version_is_current,
)


class MarkItDownParser:
    """Any-format → Markdown via Microsoft markitdown (no model downloads)."""

    name = "markitdown"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("markitdown") is not None

    def resolve_config(self) -> MarkItDownConfig:
        return resolve_markitdown_config()

    def supported_formats(self) -> frozenset[str]:
        return markitdown_supported_formats()

    def signature(self, config: MarkItDownConfig) -> ParserSignature:
        return ParserSignature.build(
            "markitdown",
            package_version("markitdown"),
            {"llm_image": config.enable_llm_image_description},
        )

    def is_ready(self, config: MarkItDownConfig) -> ReadinessReport:
        if not self.is_available():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="markitdown isn't installed (pip install deeptutor[parse-markitdown]).",
            )
        version = installed_markitdown_version()
        if not markitdown_version_is_current(version):
            return ReadinessReport(
                ready=False,
                reason="update_required",
                message=(
                    f"Installed markitdown {version or 'unknown'} is too old. DeepTutor needs "
                    f"markitdown >= {MIN_MARKITDOWN_VERSION} with all format extras. Update it "
                    "under Settings → Document Parsing."
                ),
            )
        return ReadinessReport(ready=True)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: MarkItDownConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        from markitdown import MarkItDown

        if on_output:
            on_output(f"Converting {Path(source_path).name} via markitdown…")
        try:
            converter = MarkItDown()
            result = converter.convert(str(source_path))
        except Exception as exc:  # noqa: BLE001 - surface as a parser error
            raise ParserError(f"markitdown failed to convert {Path(source_path).name}: {exc}")

        text = getattr(result, "text_content", None) or getattr(result, "markdown", None) or ""
        stem = Path(source_path).stem
        (workdir / f"{stem}.md").write_text(str(text), encoding="utf-8")


__all__ = ["MarkItDownParser"]
