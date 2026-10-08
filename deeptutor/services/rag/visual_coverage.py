"""Inspect extraction limits without equating emitted assets with whole-book coverage."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.visual_assets import (
    MAX_IMAGE_BYTES,
    VisualAssetCandidate,
    VisualAssetStore,
    _image_bytes,
    _sha256_file,
    source_key_for,
)


def record_coverage(
    parsed: ParsedDocument, source: Path, kb_dir: Path, candidates: list[VisualAssetCandidate]
) -> None:
    source_path = source_key_for(kb_dir, source)
    if not source.resolve().is_relative_to((kb_dir / "raw").resolve()):
        return
    issues = []
    if parsed.asset_dir and parsed.asset_dir.is_dir() and not parsed.asset_dir.is_symlink():
        for path in sorted(parsed.asset_dir.iterdir()):
            if path.suffix.casefold() not in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
                ".svg",
                ".bmp",
                ".tiff",
            }:
                continue
            reason = ""
            status = "skipped"
            try:
                if path.is_symlink():
                    reason = "symbolic_link"
                elif path.stat().st_size > MAX_IMAGE_BYTES:
                    reason = "exceeds_5_mib"
                elif _image_bytes(path) is None:
                    reason = "unsupported_or_invalid_pixels"
            except OSError:
                reason, status = "asset_read_failed", "failed"
            if reason:
                issues.append({"asset": path.name, "status": status, "reason": reason})
    for index, block in enumerate(parsed.blocks or []):
        if not isinstance(block, dict):
            continue
        raw_page = block.get("page_idx")
        page = raw_page + 1 if isinstance(raw_page, int) else block.get("page")
        if str(block.get("type") or "").casefold() == "table":
            issues.append(
                {
                    "page": page,
                    "locator": f"blocks.json#/{index}",
                    "status": "unverified",
                    "reason": "table_structure_requires_source_verification",
                    "structured_table_available": bool(
                        block.get("table_body") or block.get("table_html")
                    ),
                }
            )
        raw_image = block.get("img_path") or block.get("path")
        if raw_image and not any(
            c.record.get("source_locator") == f"blocks.json#/{index}" for c in candidates
        ):
            issues.append(
                {
                    "page": page,
                    "locator": f"blocks.json#/{index}",
                    "status": "unverified",
                    "reason": "referenced_image_not_retained",
                }
            )
    report = {
        "source_path": source_path,
        "source_document_id": _sha256_file(source),
        "parser_engine": parsed.engine,
        "parser_signature": parsed.parser_signature,
        "validated_count": len(candidates),
        "issues": issues,
        "whole_document_verified": False,
        "coverage_reason": "Parser-emitted assets do not prove complete visual coverage. Inspect original pages for vector drawings, missing crops or unreadable labels.",
        "page_fallback": source.suffix.casefold() == ".pdf",
    }
    root = VisualAssetStore(kb_dir).root
    if root.is_symlink():
        raise OSError("Visual coverage directory is unsafe")
    report_dir = root / "coverage"
    if report_dir.is_symlink():
        raise OSError("Visual coverage directory is unsafe")
    atomic_write_json(report_dir / (sha256(source_path.encode()).hexdigest() + ".json"), report)


def coverage_overview(
    kb_dir: Path, *, source_path: str = "", offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    store = VisualAssetStore(kb_dir)
    records = store._read_manifest()
    root = kb_dir / "raw"
    if root.is_symlink():
        raise OSError("Raw source directory is unsafe")
    reports = []
    files = (
        [root / source_path] if source_path else sorted(root.rglob("*")) if root.is_dir() else []
    )
    for path in files:
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
        ):
            continue
        key = path.relative_to(root).as_posix()
        digest = _sha256_file(path)
        report_file = store.root / "coverage" / (sha256(key.encode()).hexdigest() + ".json")
        try:
            if (
                store.root.is_symlink()
                or report_file.parent.is_symlink()
                or report_file.is_symlink()
            ):
                raise ValueError("unsafe coverage path")
            report = json.loads(report_file.read_text())
            if not isinstance(report, dict) or report.get("source_document_id") != digest:
                raise ValueError("outdated coverage")
        except (OSError, ValueError):
            report = {
                "source_path": key,
                "source_document_id": digest,
                "whole_document_verified": False,
                "issues": [{"status": "unverified", "reason": "extraction_coverage_unknown"}],
                "page_fallback": path.suffix.casefold() == ".pdf",
            }
        retained = [
            r
            for r in records.values()
            if r.get("source_path") == key and r.get("source_document_id") == digest
        ]
        reports.append(
            {
                **report,
                "retained_count": len({r.get("source_locator") for r in retained}),
                "indexing_status": "not_verified_by_extraction_report",
            }
        )
    assets = [r for r in records.values() if not source_path or r.get("source_path") == source_path]
    # Return a bounded catalog and total; retention itself remains unbounded.
    return {
        "documents": reports,
        "assets": assets[offset : offset + limit],
        "total_assets": len(assets),
        "offset": offset,
        "limit": limit,
        "model_image_limit": 2,
    }
