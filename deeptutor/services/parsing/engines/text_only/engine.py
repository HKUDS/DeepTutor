"""Text-only parser adapter implementing the ``Parser`` protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from deeptutor.runtime.isolated_worker import IsolatedWorkerError, run_in_isolated_process_sync
from deeptutor.utils.document_extractor import SUPPORTED_DOC_EXTENSIONS
from deeptutor.utils.document_validator import DocumentValidator

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError


class TextOnlyParser:
    """Built-in PDF/Office/EPUB/text-file extraction with no external engine."""

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

        stem = Path(source_path).stem
        output_path = workdir / f"{stem}.md"
        try:
            run_in_isolated_process_sync(
                "deeptutor.runtime.worker_tasks:extract_document_to_markdown",
                str(source_path),
                str(output_path),
                kwargs={
                    "max_bytes": DocumentValidator.MAX_FILE_SIZE,
                    "max_chars": None,
                },
            )
        except (IsolatedWorkerError, OSError) as exc:
            raise ParserError(
                f"text-only extraction failed for {Path(source_path).name}: {exc}"
            ) from exc


__all__ = ["TextOnlyParser"]
