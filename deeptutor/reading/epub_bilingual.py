"""Explicit EPUB pairing metadata.

Pairing is deliberately two-step: DeepTutor recommends likely language
editions, but a reader explicitly confirms the pair before any downstream
bilingual rendering or study behavior is enabled. This module stores only that
confirmation; derived EPUB generation belongs to a later feature.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import threading
from typing import TYPE_CHECKING, Any
import zipfile

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from deeptutor.reading.models import MaterialManifest, ReadingError
from deeptutor.services.file_io import atomic_write_text as _atomic_write

if TYPE_CHECKING:
    from deeptutor.reading.store import ReadingStore

PAIRINGS_NAME = "_epub_pairings.json"
_PAIRING_WRITE_LOCK = threading.Lock()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _metadata(epub: Path) -> dict[str, str]:
    """Read enough OPF metadata to rank, never to pair automatically."""
    try:
        with zipfile.ZipFile(epub) as archive:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = next(
                element
                for element in container.iter()
                if _local_name(element.tag) == "rootfile" and element.get("full-path")
            )
            opf_name = str(PurePosixPath(rootfile.attrib["full-path"]))
            if opf_name.startswith("/") or ".." in PurePosixPath(opf_name).parts:
                return {}
            root = ET.fromstring(archive.read(opf_name))
    except (
        DefusedXmlException,
        ET.ParseError,
        KeyError,
        OSError,
        StopIteration,
        zipfile.BadZipFile,
    ):
        return {}

    wanted = ("title", "creator", "identifier", "language")
    values: dict[str, str] = {}
    for element in root.iter():
        name = _local_name(element.tag)
        if name in wanted and name not in values:
            values[name] = " ".join((element.text or "").split())
    return values


def _language(value: str) -> str:
    return value.strip().casefold().split("-", 1)[0]


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w\u3400-\u9fff]+", value.casefold()))


def _outline_titles(store: ReadingStore, material_id: str) -> set[str]:
    return {row.title.casefold() for row in store.outline(material_id) if row.title}


def recommend_epub_candidates(store: ReadingStore, material_id: str) -> list[dict[str, Any]]:
    """Return likely alternate-language editions for explicit confirmation."""
    source = store.manifest(material_id)
    _require_epub(source, "EPUB pairing")
    source_path = _raw_epub(store, material_id, "The source EPUB is unavailable.")
    source_meta = _metadata(source_path)
    source_titles = _outline_titles(store, material_id)
    source_language = _language(source_meta.get("language") or "")

    candidates: list[dict[str, Any]] = []
    for candidate in store.list_materials():
        if candidate.material_id == material_id or candidate.render_mode != "epub":
            continue
        try:
            candidate_path = _raw_epub(
                store, candidate.material_id, "The candidate EPUB is unavailable."
            )
        except ReadingError:
            continue
        metadata = _metadata(candidate_path)
        title_a = _tokens(source_meta.get("title") or source.title)
        title_b = _tokens(metadata.get("title") or candidate.title)
        title_score = len(title_a & title_b) / max(1, len(title_a | title_b))
        candidate_titles = _outline_titles(store, candidate.material_id)
        toc_score = len(source_titles & candidate_titles) / max(
            1, len(source_titles | candidate_titles)
        )
        identifier_match = bool(
            source_meta.get("identifier")
            and source_meta.get("identifier") == metadata.get("identifier")
        )
        author_match = bool(
            source_meta.get("creator")
            and source_meta.get("creator", "").casefold() == metadata.get("creator", "").casefold()
        )
        candidate_language = _language(metadata.get("language") or "")
        language_bonus = float(
            bool(source_language)
            and bool(candidate_language)
            and source_language != candidate_language
        )
        score = (
            0.4 * title_score
            + 0.2 * toc_score
            + 0.2 * float(identifier_match)
            + 0.1 * float(author_match)
            + 0.1 * language_bonus
        )
        candidates.append(
            {
                "material_id": candidate.material_id,
                "title": candidate.title,
                "filename": candidate.filename,
                "language": metadata.get("language", ""),
                "author": metadata.get("creator", ""),
                "score": round(score, 4),
                "reasons": {
                    "title": round(title_score, 4),
                    "toc": round(toc_score, 4),
                    "identifier": identifier_match,
                    "author": author_match,
                    "different_language": bool(language_bonus),
                },
            }
        )
    return sorted(candidates, key=lambda row: (-row["score"], row["title"]))


def _require_epub(manifest: MaterialManifest, action: str) -> None:
    if manifest.render_mode != "epub":
        raise ReadingError(f"{action} is only available for EPUB materials.")


def _raw_epub(store: ReadingStore, material_id: str, error: str) -> Path:
    path = store.raw_path(material_id)
    if path is None:
        raise ReadingError(error)
    return path


def _pairing_path(store: ReadingStore) -> Path:
    return store.root / PAIRINGS_NAME


def list_epub_pairings(store: ReadingStore) -> list[dict[str, Any]]:
    try:
        rows = json.loads(_pairing_path(store).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return rows if isinstance(rows, list) else []


def create_epub_pairing(
    store: ReadingStore, english_material_id: str, chinese_material_id: str
) -> dict[str, Any]:
    """Record an explicit reader-confirmed pair without deriving a material."""
    english = store.manifest(english_material_id)
    chinese = store.manifest(chinese_material_id)
    _require_epub(english, "The English pairing source")
    _require_epub(chinese, "The Chinese pairing source")
    if english.material_id == chinese.material_id:
        raise ReadingError("Choose two different EPUB editions.")
    english_path = _raw_epub(store, english.material_id, "The English EPUB is unavailable.")
    chinese_path = _raw_epub(store, chinese.material_id, "The Chinese EPUB is unavailable.")
    english_language = _language(_metadata(english_path).get("language") or "")
    chinese_language = _language(_metadata(chinese_path).get("language") or "")
    if english_language != "en":
        raise ReadingError("The English pairing source must declare an English language.")
    if chinese_language != "zh":
        raise ReadingError("The Chinese pairing source must declare a Chinese language.")

    pairing_id = hashlib.sha256(
        f"{english.material_id}\0{chinese.material_id}".encode("utf-8")
    ).hexdigest()[:16]
    row = {
        "pairing_id": pairing_id,
        "english_material_id": english.material_id,
        "english_title": english.title,
        "english_language": english_language,
        "chinese_material_id": chinese.material_id,
        "chinese_title": chinese.title,
        "chinese_language": chinese_language,
        "status": "confirmed",
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    with _PAIRING_WRITE_LOCK:
        rows = [item for item in list_epub_pairings(store) if item.get("pairing_id") != pairing_id]
        rows.append(row)
        _atomic_write(_pairing_path(store), json.dumps(rows, ensure_ascii=False, indent=2))
    return row


def delete_epub_pairing(store: ReadingStore, pairing_id: str) -> bool:
    """Remove the pairing record while preserving both source materials."""
    with _PAIRING_WRITE_LOCK:
        rows = list_epub_pairings(store)
        remaining = [row for row in rows if row.get("pairing_id") != pairing_id]
        if len(remaining) == len(rows):
            return False
        _atomic_write(_pairing_path(store), json.dumps(remaining, ensure_ascii=False, indent=2))
        return True


def delete_epub_pairings_for_material(store: ReadingStore, material_id: str) -> int:
    """Remove every pairing that would dangle after a material is deleted."""

    with _PAIRING_WRITE_LOCK:
        rows = list_epub_pairings(store)
        remaining = [
            row
            for row in rows
            if row.get("english_material_id") != material_id
            and row.get("chinese_material_id") != material_id
        ]
        removed = len(rows) - len(remaining)
        if removed:
            _atomic_write(_pairing_path(store), json.dumps(remaining, ensure_ascii=False, indent=2))
        return removed


__all__ = [
    "create_epub_pairing",
    "delete_epub_pairing",
    "delete_epub_pairings_for_material",
    "list_epub_pairings",
    "recommend_epub_candidates",
]
