"""Explicit EPUB pairing and source-faithful bilingual revision building."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from html import escape
import io
import json
from pathlib import Path
import re
import tempfile
from typing import Any
import zipfile

from deeptutor.reading.extract import extract_material
from deeptutor.reading.models import MaterialManifest, ReadingError
from deeptutor.reading.sources import FileSourceAdapter
from deeptutor.reading.store import ReadingStore, _atomic_write

PAIRINGS_NAME = "_epub_pairings.json"
_BLOCK_RE = re.compile(r"(<(?:p|li|blockquote)\b[^>]*>.*?</(?:p|li|blockquote)>)", re.I | re.S)
_BODY_CLOSE_RE = re.compile(r"</body\s*>", re.I)
_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")

_DETAIL_CSS = """
<style type="text/css" data-deeptutor-bilingual="true">
details.dt-zh { margin:.4em 0 1em; padding:.45em .75em; border-left:3px solid #2563eb; background:rgba(37,99,235,.06); border-radius:.35em; }
details.dt-zh summary { cursor:pointer; color:#2563eb; font-weight:600; font-size:.9em; }
details.dt-zh .dt-zh-text { line-height:1.75; font-family:"PingFang SC","Noto Serif CJK SC",serif; }
details.dt-zh[data-low-confidence="true"] { border-left-color:#d97706; }
</style>
""".strip()


def _metadata(epub: Path) -> dict[str, str]:
    try:
        with zipfile.ZipFile(epub) as archive:
            opf_name = next(name for name in archive.namelist() if name.lower().endswith(".opf"))
            opf = archive.read(opf_name).decode("utf-8", "replace")
    except Exception:
        return {}

    def value(tag: str) -> str:
        match = re.search(rf"<(?:\w+:)?{tag}\b[^>]*>(.*?)</(?:\w+:)?{tag}>", opf, re.I | re.S)
        return _TAG_RE.sub("", match.group(1)).strip() if match else ""

    return {
        "title": value("title"),
        "author": value("creator"),
        "identifier": value("identifier"),
        "language": value("language"),
    }


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w\u3400-\u9fff]+", value.casefold()))


def recommend_epub_candidates(store: ReadingStore, material_id: str) -> list[dict[str, Any]]:
    source = store.manifest(material_id)
    if source.render_mode != "epub":
        raise ReadingError("EPUB pairing is only available for EPUB materials.")
    source_path = store.raw_path(material_id)
    if source_path is None:
        raise ReadingError("Repair this EPUB before pairing it.")
    source_meta = _metadata(source_path)
    source_titles = {row.title.casefold() for row in store.outline(material_id) if row.title}
    candidates: list[dict[str, Any]] = []
    for candidate in store.list_materials():
        if candidate.material_id == material_id or candidate.render_mode != "epub":
            continue
        path = store.raw_path(candidate.material_id)
        if path is None:
            continue
        metadata = _metadata(path)
        title_a = _tokens(source_meta.get("title") or source.title)
        title_b = _tokens(metadata.get("title") or candidate.title)
        title_score = len(title_a & title_b) / max(1, len(title_a | title_b))
        candidate_titles = {
            row.title.casefold() for row in store.outline(candidate.material_id) if row.title
        }
        toc_score = len(source_titles & candidate_titles) / max(
            1, len(source_titles | candidate_titles)
        )
        identifier_score = float(
            bool(source_meta.get("identifier"))
            and source_meta.get("identifier") == metadata.get("identifier")
        )
        author_score = float(
            bool(source_meta.get("author"))
            and source_meta.get("author").casefold() == metadata.get("author", "").casefold()
        )
        language_bonus = float(
            source_meta.get("language", "").casefold() != metadata.get("language", "").casefold()
        )
        score = (
            0.4 * title_score
            + 0.2 * toc_score
            + 0.2 * identifier_score
            + 0.1 * author_score
            + 0.1 * language_bonus
        )
        candidates.append(
            {
                "material_id": candidate.material_id,
                "title": candidate.title,
                "filename": candidate.filename,
                "language": metadata.get("language", ""),
                "author": metadata.get("author", ""),
                "score": round(score, 4),
                "reasons": {
                    "title": round(title_score, 4),
                    "toc": round(toc_score, 4),
                    "identifier": bool(identifier_score),
                    "author": bool(author_score),
                },
            }
        )
    return sorted(candidates, key=lambda row: (-row["score"], row["title"]))


def _translation_paragraphs(text: str) -> list[str]:
    return [row.strip() for row in re.split(r"\n\s*\n|(?<=。)\s*\n", text) if row.strip()]


def _inject_chapter(source: str, translation_text: str) -> tuple[str, int]:
    translations = _translation_paragraphs(translation_text)
    if not translations:
        return source, 0
    blocks = list(_BLOCK_RE.finditer(source))
    low_confidence = bool(blocks) and len(blocks) != len(translations)
    if not blocks:
        details = "".join(_details(row, low_confidence=True) for row in translations)
        return _BODY_CLOSE_RE.sub(details + "\n</body>", source, count=1), len(translations)
    output: list[str] = []
    cursor = 0
    for index, block in enumerate(blocks):
        output.append(source[cursor : block.end()])
        if index < len(translations):
            output.append(
                "\n" + _details(translations[index], low_confidence=low_confidence)
            )
        cursor = block.end()
    output.append(source[cursor:])
    merged = "".join(output)
    for row in translations[len(blocks) :]:
        merged = _BODY_CLOSE_RE.sub(
            _details(row, low_confidence=True) + "\n</body>", merged, count=1
        )
    if "data-deeptutor-bilingual" not in merged:
        if _HEAD_CLOSE_RE.search(merged):
            merged = _HEAD_CLOSE_RE.sub(_DETAIL_CSS + "\n</head>", merged, count=1)
        else:
            merged = _DETAIL_CSS + "\n" + merged
    return merged, min(len(blocks), len(translations))


def _details(text: str, *, low_confidence: bool = False) -> str:
    warning = " · 请检查对齐" if low_confidence else ""
    confidence = "true" if low_confidence else "false"
    return (
        f'<details class="dt-zh" data-low-confidence="{confidence}">'
        f"<summary>显示中文{warning}</summary>"
        f'<div class="dt-zh-text">{escape(text)}</div></details>'
    )


def build_bilingual_epub(
    english: Path,
    chinese: Path,
    english_units: list[str],
    chinese_units: list[str],
) -> bytes:
    """Copy the English package and replace only its spine XHTML documents."""
    english_extraction = extract_material(english)
    if english_extraction.render_mode != "epub":
        raise ReadingError("The source material is not a readable EPUB.")
    translations = chinese_units
    source_buffer = io.BytesIO()
    with zipfile.ZipFile(english) as source, zipfile.ZipFile(source_buffer, "w") as output:
        for info in source.infolist():
            data = source.read(info.filename)
            ref_index = next(
                (
                    index
                    for index, ref in enumerate(english_extraction.unit_refs)
                    if ref.source_href.lstrip("/") == info.filename.lstrip("/")
                    or ref.source_href.rsplit("/", 1)[-1] == info.filename.rsplit("/", 1)[-1]
                ),
                None,
            )
            if ref_index is not None and ref_index < len(translations):
                xml = data.decode("utf-8", "replace")
                xml, _ = _inject_chapter(xml, translations[ref_index])
                data = xml.encode("utf-8")
            compress = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            output.writestr(info, data, compress_type=compress)
    return source_buffer.getvalue()


def _pairing_path(store: ReadingStore) -> Path:
    return store.root / PAIRINGS_NAME


def list_epub_pairings(store: ReadingStore) -> list[dict[str, Any]]:
    try:
        rows = json.loads(_pairing_path(store).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return rows if isinstance(rows, list) else []


def create_epub_pairing(
    store: ReadingStore,
    english_material_id: str,
    chinese_material_id: str,
) -> tuple[dict[str, Any], MaterialManifest]:
    english = store.manifest(english_material_id)
    chinese = store.manifest(chinese_material_id)
    if english.render_mode != "epub" or chinese.render_mode != "epub":
        raise ReadingError("Both confirmed pairing sources must be EPUB materials.")
    english_path = store.raw_path(english_material_id)
    chinese_path = store.raw_path(chinese_material_id)
    if english_path is None or chinese_path is None:
        raise ReadingError("Repair both EPUB sources before creating a bilingual pairing.")
    raw = build_bilingual_epub(
        english_path,
        chinese_path,
        [text for _, text in store.iter_units(english_material_id)],
        [text for _, text in store.iter_units(chinese_material_id)],
    )
    pairing_id = hashlib.sha256(
        f"{english_material_id}\0{chinese_material_id}".encode()
    ).hexdigest()[:16]
    with tempfile.TemporaryDirectory(prefix="dt-bilingual-epub-") as temp:
        path = Path(temp) / f"{Path(english.filename).stem}-bilingual.epub"
        path.write_bytes(raw)
        base = FileSourceAdapter(path).build()
    payload = replace(
        base,
        source_type="derived_epub",
        source_ref=f"bilingual-epub:{pairing_id}",
        title=f"{english.title} — Bilingual",
        filename=f"{Path(english.filename).stem}-bilingual.epub",
        bilingual_languages=("en", "zh"),
        bilingual_pairing_ids=(pairing_id,),
    )
    material = store.ingest_source(payload)
    row = {
        "pairing_id": pairing_id,
        "english_material_id": english_material_id,
        "chinese_material_id": chinese_material_id,
        "material_id": material.material_id,
        "revision_id": material.revision_id,
        "status": "ready",
    }
    rows = [item for item in list_epub_pairings(store) if item.get("pairing_id") != pairing_id]
    rows.append(row)
    _atomic_write(_pairing_path(store), json.dumps(rows, ensure_ascii=False, indent=2))
    return row, material


def delete_epub_pairing(store: ReadingStore, pairing_id: str) -> bool:
    rows = list_epub_pairings(store)
    remaining = [row for row in rows if row.get("pairing_id") != pairing_id]
    if len(remaining) == len(rows):
        return False
    _atomic_write(_pairing_path(store), json.dumps(remaining, ensure_ascii=False, indent=2))
    return True


__all__ = [
    "build_bilingual_epub",
    "create_epub_pairing",
    "delete_epub_pairing",
    "list_epub_pairings",
    "recommend_epub_candidates",
]
