"""Turn raw KB files into plain-text input for GraphRAG.

GraphRAG's graph engine is text-only — it has no document parser of its own
(its optional ``markitdown`` reader is just a converter). So DeepTutor owns the
"document → text" step and hands GraphRAG ready ``.txt`` files. We deliberately
reuse DeepTutor's existing extraction primitives here so multimodal/parsing
stays a DeepTutor-side concern (matching how the LlamaIndex pipeline already
handles documents) rather than pulling a second parser into the tree.

This is intentionally the one swappable seam: the rest of the GraphRAG pipeline
consumes ``input/*.txt`` regardless of which parser produced the text.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from deeptutor.services.rag.file_routing import FileTypeRouter

from . import storage

logger = logging.getLogger(__name__)


def _unique_txt_path(target_dir: Path, source: Path, used: set[str]) -> Path:
    """Pick a collision-free ``<stem>.txt`` name inside ``target_dir``."""
    stem = source.stem or "document"
    candidate = f"{stem}.txt"
    suffix = 1
    while candidate in used:
        candidate = f"{stem}_{suffix}.txt"
        suffix += 1
    used.add(candidate)
    return target_dir / candidate


def _extract_parser_text(path: Path) -> str:
    from deeptutor.services.parsing import ParserError, get_parse_service

    try:
        parsed = get_parse_service().parse(path)
    except ParserError as exc:
        logger.error("GraphRAG ingestion: failed to parse %s: %s", path.name, exc)
        return ""
    text = parsed.markdown.strip()
    if text:
        return text
    if parsed.blocks:
        parts = [
            str(block.get("text") or block.get("content") or "").strip()
            for block in parsed.blocks
            if isinstance(block, dict)
        ]
        return "\n\n".join(part for part in parts if part)
    return ""


async def prepare_input(file_paths: Iterable[str], root_dir: Path) -> int:
    """Write parsed text for each supported file into ``root_dir/input``.

    Returns the number of non-empty text documents written. Parser-backed files
    go through the shared document-parse bridge, so the active settings engine
    (text-only, MinerU, Docling, markitdown) owns conversion before GraphRAG
    sees text.
    Image files are skipped in this text-first path; unsupported files are
    logged and ignored.
    """
    target_dir = storage.input_dir(root_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    classification = FileTypeRouter.classify_files([str(p) for p in file_paths])
    used: set[str] = {p.name for p in target_dir.glob("*.txt")}
    written = 0

    for file_path_str in classification.parser_files:
        path = Path(file_path_str)
        text = _extract_parser_text(path)
        written += _write_doc(target_dir, path, text, used)

    for file_path_str in classification.text_files:
        path = Path(file_path_str)
        try:
            text = await FileTypeRouter.read_text_file(str(path))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("GraphRAG ingestion: failed to read text %s: %s", path.name, exc)
            text = ""
        written += _write_doc(target_dir, path, text, used)

    for file_path_str in classification.image_files:
        logger.warning(
            "GraphRAG ingestion skips image file (text-only engine): %s",
            Path(file_path_str).name,
        )
    for file_path_str in classification.unsupported:
        logger.warning("GraphRAG ingestion skips unsupported file: %s", Path(file_path_str).name)

    return written


def _write_doc(target_dir: Path, source: Path, text: str, used: set[str]) -> int:
    if not text.strip():
        logger.warning("GraphRAG ingestion: empty document skipped: %s", source.name)
        return 0
    dest = _unique_txt_path(target_dir, source, used)
    dest.write_text(text, encoding="utf-8")
    logger.info("GraphRAG ingestion: wrote %s (%d chars)", dest.name, len(text))
    return 1


__all__ = ["prepare_input"]
