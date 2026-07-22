"""Text-only parser adapter implementing the ``Parser`` protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from deeptutor.utils.document_extractor import (
    SUPPORTED_DOC_EXTENSIONS,
    DocumentExtractionError,
    extract_text_from_path,
)
from deeptutor.utils.document_validator import DocumentValidator

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError


class TextOnlyParser:
    """Built-in PDF/Office/text-file extraction with no external engine."""

    name = "text_only"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    def resolve_config(self) -> dict[str, Any]:
        return {}

    def supported_formats(self) -> frozenset[str]:
        return SUPPORTED_DOC_EXTENSIONS

    def signature(self, _config: dict[str, Any]) -> ParserSignature:
        return ParserSignature.build("text_only", "builtin-v1", {})

    def is_ready(self, _config: dict[str, Any]) -> ReadinessReport:
        return ReadinessReport(ready=True)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: dict[str, Any],
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        del config
        if on_output:
            on_output(f"Extracting plain text from {Path(source_path).name}...")

        try:
            text = extract_text_from_path(
                source_path, max_bytes=DocumentValidator.MAX_FILE_SIZE, max_chars=None
            )
        except (DocumentExtractionError, OSError) as exc:
            raise ParserError(
                f"text-only extraction failed for {Path(source_path).name}: {exc}"
            ) from exc

        stem = Path(source_path).stem
        (workdir / f"{stem}.md").write_text(text, encoding="utf-8")


__all__ = ["TextOnlyParser"]
