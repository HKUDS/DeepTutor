"""Unified source adapters for Immersive Reading.

Adapters stop the reader store from knowing whether text came from an upload,
a web snapshot, or a knowledge-base document.  Every adapter produces the same
locator-addressed payload and provenance fields; the store owns persistence,
revisioning, and annotation migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import time
from typing import Protocol

from deeptutor.reading.extract import Extraction, extract_material, split_into_sections
from deeptutor.reading.models import (
    OutlineEntry,
    RenderMode,
    SourceType,
    UnitKind,
    UnitReference,
)


@dataclass(frozen=True, slots=True)
class ReadingSourcePayload:
    source_type: SourceType
    source_ref: str
    filename: str
    title: str
    units: tuple[str, ...]
    unit: UnitKind = "section"
    outline: tuple[OutlineEntry, ...] = field(default_factory=tuple)
    unit_refs: tuple[UnitReference, ...] = field(default_factory=tuple)
    source_url: str = ""
    kb_name: str = ""
    kb_path: str = ""
    mime: str = "text/markdown"
    extractor: str = "reading-source"
    raw_bytes: bytes = b""
    has_raw_view: bool = False
    render_mode: RenderMode = "text"
    captured_at: float = field(default_factory=time.time)

    @property
    def content_hash(self) -> str:
        digest = hashlib.sha256()
        for unit in self.units:
            digest.update(unit.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()[:16]


class ReadingSourceAdapter(Protocol):
    """Convert a concrete source into a store-ready reading payload."""

    def build(self) -> ReadingSourcePayload: ...


@dataclass(frozen=True, slots=True)
class FileSourceAdapter:
    path: Path
    filename: str = ""
    source_type: SourceType = "upload"
    source_ref: str = ""
    source_url: str = ""
    kb_name: str = ""
    kb_path: str = ""

    def build(self) -> ReadingSourcePayload:
        extraction: Extraction = extract_material(self.path)
        filename = self.filename or self.path.name
        raw = self.path.read_bytes()
        return ReadingSourcePayload(
            source_type=self.source_type,
            source_ref=self.source_ref or f"upload:{hashlib.sha256(raw).hexdigest()}",
            filename=filename,
            title=extraction.title or Path(filename).stem,
            units=extraction.units,
            unit=extraction.unit,
            outline=extraction.outline,
            unit_refs=extraction.unit_refs,
            source_url=self.source_url,
            kb_name=self.kb_name,
            kb_path=self.kb_path,
            extractor=extraction.extractor,
            raw_bytes=raw,
            has_raw_view=extraction.has_raw_view,
            render_mode=extraction.render_mode,
        )


def markdown_payload(
    *,
    source_type: SourceType,
    source_ref: str,
    title: str,
    markdown: str,
    filename: str,
    source_url: str = "",
    kb_name: str = "",
    kb_path: str = "",
    outline: tuple[OutlineEntry, ...] = (),
) -> ReadingSourcePayload:
    """Build a Markdown payload, preserving supplied tutorial structure."""
    units = split_into_sections(markdown)
    return ReadingSourcePayload(
        source_type=source_type,
        source_ref=source_ref,
        filename=filename,
        title=title,
        units=units,
        unit="section",
        outline=outline,
        source_url=source_url,
        kb_name=kb_name,
        kb_path=kb_path,
        raw_bytes=markdown.encode("utf-8"),
        has_raw_view=False,
    )


__all__ = [
    "FileSourceAdapter",
    "ReadingSourceAdapter",
    "ReadingSourcePayload",
    "markdown_payload",
]
