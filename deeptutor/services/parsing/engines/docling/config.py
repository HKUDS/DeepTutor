"""Docling engine config (read-side adapter over the v2 settings slice)."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import (
    DOCUMENT_PARSING_ENGINE_DOCLING,
    load_document_parsing_settings,
)


@dataclass(frozen=True)
class DoclingConfig:
    do_ocr: bool = False
    do_table_structure: bool = True
    # See ``allow_local_model_download`` on MinerU — gates the first-run weight
    # download (default off → no silent pull).
    allow_local_model_download: bool = False


def resolve_docling_config() -> DoclingConfig:
    slice_ = (
        load_document_parsing_settings().get("engines", {}).get(DOCUMENT_PARSING_ENGINE_DOCLING, {})
    )
    return DoclingConfig(
        do_ocr=bool(slice_.get("do_ocr", False)),
        do_table_structure=bool(slice_.get("do_table_structure", True)),
        allow_local_model_download=bool(slice_.get("allow_local_model_download", False)),
    )


__all__ = ["DoclingConfig", "resolve_docling_config"]
