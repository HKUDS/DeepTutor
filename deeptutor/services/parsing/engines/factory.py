"""Parser engine registry.

Maps an engine name to its adapter class, mirroring the RAG pipeline factory
(``services/rag/factory.py``). Engine modules import their third-party deps
lazily, so importing this registry is cheap and never fails on a missing
optional dependency.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from deeptutor.services.config.runtime_settings import (
    DOCUMENT_PARSING_ENGINE_DOCLING,
    DOCUMENT_PARSING_ENGINE_MARKITDOWN,
    DOCUMENT_PARSING_ENGINE_MINERU,
    DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM,
    DOCUMENT_PARSING_ENGINE_TEXT_ONLY,
)

from ..base import Parser
from ..types import ParserError


def _mineru_class():
    from .mineru.engine import MinerUParser

    return MinerUParser


def _text_only_class():
    from .text_only.engine import TextOnlyParser

    return TextOnlyParser


def _docling_class():
    from .docling.engine import DoclingParser

    return DoclingParser


def _markitdown_class():
    from .markitdown.engine import MarkItDownParser

    return MarkItDownParser


def _pymupdf4llm_class():
    from .pymupdf4llm.engine import PyMuPDF4LLMParser

    return PyMuPDF4LLMParser


# name -> zero-arg loader returning the engine class.
_ENGINE_LOADERS: Dict[str, Callable[[], Any]] = {
    DOCUMENT_PARSING_ENGINE_TEXT_ONLY: _text_only_class,
    DOCUMENT_PARSING_ENGINE_MINERU: _mineru_class,
    DOCUMENT_PARSING_ENGINE_DOCLING: _docling_class,
    DOCUMENT_PARSING_ENGINE_MARKITDOWN: _markitdown_class,
    DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM: _pymupdf4llm_class,
}

KNOWN_ENGINES = frozenset(_ENGINE_LOADERS)

# Static UI metadata (kept here so list_engines never imports engine deps).
_ENGINE_META: Dict[str, Dict[str, Any]] = {
    DOCUMENT_PARSING_ENGINE_TEXT_ONLY: {
        "name": "Text-only",
        "description": (
            "Built-in plain text extraction for PDF/Office/text files. No "
            "optional parser package, no model download, no layout structure."
        ),
        "needs_local_models": False,
    },
    DOCUMENT_PARSING_ENGINE_MINERU: {
        "name": "MinerU",
        "description": (
            "Highest-fidelity multimodal parsing (layout, tables, formulas). "
            "Local CLI downloads models, or use the hosted cloud API. PDF only."
        ),
        "needs_local_models": True,
    },
    DOCUMENT_PARSING_ENGINE_DOCLING: {
        "name": "Docling",
        "description": (
            "Structured document conversion (layout/tables). Downloads local "
            "models on first run. PDF/Office/HTML/images."
        ),
        "needs_local_models": True,
    },
    DOCUMENT_PARSING_ENGINE_MARKITDOWN: {
        "name": "markitdown",
        "description": (
            "Lightweight, no model downloads — broad format support, Markdown "
            "output. Works out of the box."
        ),
        "needs_local_models": False,
    },
    DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM: {
        "name": "PyMuPDF4LLM",
        "description": (
            "Lightweight, no model downloads or CUDA — runs on low-end / GPU-less "
            "machines. PDF/e-book → Markdown and can extract images. PDF and "
            "e-book formats only."
        ),
        "needs_local_models": False,
    },
}


def _normalize_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def get_parser(name: str) -> Parser:
    """Return an engine instance for ``name`` (raises if unknown)."""
    loader = _ENGINE_LOADERS.get(_normalize_name(name))
    if loader is None:
        raise ParserError(f"Unknown document-parsing engine: {name!r}")
    return loader()()


def is_engine_available(name: str) -> bool:
    loader = _ENGINE_LOADERS.get(_normalize_name(name))
    if loader is None:
        return False
    try:
        return bool(loader().is_available())
    except Exception:
        return False


def list_engines() -> List[Dict[str, Any]]:
    """Describe engines for the settings UI picker (no engine deps imported)."""
    out: List[Dict[str, Any]] = []
    for engine_id, meta in _ENGINE_META.items():
        out.append(
            {
                "id": engine_id,
                "name": meta["name"],
                "description": meta["description"],
                "needs_local_models": meta["needs_local_models"],
                "available": is_engine_available(engine_id),
            }
        )
    return out


__all__ = ["KNOWN_ENGINES", "get_parser", "is_engine_available", "list_engines"]
