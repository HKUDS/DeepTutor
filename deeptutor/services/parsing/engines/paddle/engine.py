"""PaddleOCR (飞桨) engine adapter implementing the ``Parser`` protocol.

Cloud-only: parses PDFs and images through the PaddleOCR AI Studio API
(``PaddleOCR-VL-1.6`` VLM document parsing), the same backend the official
``paddleocr-mcp`` server uses. No local models, no CUDA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from .config import PaddleConfig, resolve_paddle_config
from .cloud import parse_cloud

# PDF + common image formats. PaddleOCR-VL is a VLM document parser; Office
# formats are not supported by the cloud API.
_SUPPORTED_FORMATS = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
)


class PaddleParser:
    """PDF/image → Markdown via the PaddleOCR AI Studio cloud API (飞桨)."""

    name = "paddle"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        # Cloud backend — no hard Python import; readiness gates whether a
        # parse can actually run (token configured).
        return True

    def resolve_config(self) -> PaddleConfig:
        return resolve_paddle_config()

    def supported_formats(self) -> frozenset[str]:
        return _SUPPORTED_FORMATS

    def signature(self, config: PaddleConfig) -> ParserSignature:
        # Token and timeouts never change the output bytes, so they stay out of
        # the signature; model + parsing knobs do.
        return ParserSignature.build(
            "paddle",
            f"cloud:{config.model}",
            {
                "model": config.model,
                "use_layout_detection": config.use_layout_detection,
                "use_chart_recognition": config.use_chart_recognition,
                "use_ocr_for_image_block": config.use_ocr_for_image_block,
                "use_doc_orientation_classify": config.use_doc_orientation_classify,
                "use_doc_unwarping": config.use_doc_unwarping,
                "layout_threshold": config.layout_threshold,
            },
        )

    def is_ready(self, config: PaddleConfig) -> ReadinessReport:
        if not config.api_keys:
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message=(
                    "PaddleOCR needs an AI Studio access token "
                    "(https://aistudio.baidu.com/account/accessToken) — set it "
                    "in Settings → Document Parsing → PaddleOCR."
                ),
            )
        return ReadinessReport(ready=True)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: PaddleConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        # Writes ``<stem>.md`` + ``images/`` into ``workdir``; ParseService
        # loads the IR afterwards via ``load_ir``.
        parse_cloud(source_path, workdir, config=config, on_progress=on_output)


__all__ = ["PaddleParser"]
