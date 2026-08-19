"""Docling engine config (read-side adapter over the v2 settings slice)."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import (
    DOCLING_MODE_LOCAL,
    DOCLING_MODE_REMOTE,
    DOCUMENT_PARSING_ENGINE_DOCLING,
    load_document_parsing_settings,
)

DEFAULT_DOCLING_SERVER_URL = "http://localhost:5001"


@dataclass(frozen=True)
class DoclingConfig:
    """Validated Docling configuration.

    ``mode`` is ``"local"`` (the ``docling`` package runs in-process) or
    ``"remote"`` (a Docling Serve HTTP server does the conversion). Remote adds
    ``api_base_url`` and an optional ``api_token`` sent as ``X-Api-Key``. The
    remaining fields are parsing knobs the local converter ignores where it
    doesn't support them.
    """

    mode: str = DOCLING_MODE_LOCAL
    api_base_url: str = DEFAULT_DOCLING_SERVER_URL
    api_token: str = ""
    do_ocr: bool = False
    do_table_structure: bool = True
    allow_local_model_download: bool = False

    @property
    def is_local(self) -> bool:
        return self.mode == DOCLING_MODE_LOCAL

    @property
    def is_remote(self) -> bool:
        return self.mode == DOCLING_MODE_REMOTE


def resolve_docling_config() -> DoclingConfig:
    slice_ = (
        load_document_parsing_settings().get("engines", {}).get(DOCUMENT_PARSING_ENGINE_DOCLING, {})
    )
    return DoclingConfig(
        mode=str(slice_.get("mode") or DOCLING_MODE_LOCAL),
        api_base_url=str(slice_.get("api_base_url") or DEFAULT_DOCLING_SERVER_URL).rstrip("/")
        or DEFAULT_DOCLING_SERVER_URL,
        api_token=str(slice_.get("api_token") or ""),
        do_ocr=bool(slice_.get("do_ocr", False)),
        do_table_structure=bool(slice_.get("do_table_structure", True)),
        allow_local_model_download=bool(slice_.get("allow_local_model_download", False)),
    )


__all__ = ["DoclingConfig", "resolve_docling_config"]
