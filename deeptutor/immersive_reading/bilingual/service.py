"""Pairing and alignment service for bilingual reading.

Manages the lifecycle of a bilingual pairing: create from two imported reading
documents, auto-build chapter map, run paragraph alignment, serve aligned data
for in-app rendering, and export a bilingual EPUB.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import html
import json
from pathlib import Path
import re
import shutil
import time
from typing import Any
from urllib.parse import unquote
import uuid
import zipfile

from deeptutor.immersive_reading.bilingual.align import extract_align_pairs
from deeptutor.immersive_reading.bilingual.merge_epub import build_bilingual_epub
from deeptutor.services.path_service import get_path_service


def _strip_tags(markup: str) -> str:
    """Strip HTML tags and decode entities."""
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Chapter map normalization ──────────────────────────────────────────

def _chapter_entry_to_dict(entry: list | dict) -> dict[str, Any]:
    """Normalize a chapter map entry (list or dict) to dict form for the API."""
    if isinstance(entry, dict):
        return entry
    return {
        "id": entry[0],
        "english": entry[1] if len(entry) > 1 else "",
        "translation": entry[2] if len(entry) > 2 else "",
        "en_title": entry[3] if len(entry) > 3 else "",
        "zh_title": entry[4] if len(entry) > 4 else "",
    }


def _chapter_entry_to_list(entry: list | dict) -> list:
    """Normalize a chapter map entry (dict or list) to list form for storage."""
    if isinstance(entry, list):
        return entry
    return [
        entry.get("id", ""),
        entry.get("english", ""),
        entry.get("translation", ""),
        entry.get("en_title", ""),
        entry.get("zh_title", ""),
    ]


# ── EPUB structure reading ──────────────────────────────────────────────


def _read_epub_chapters(epub_path: Path) -> tuple[str, list[dict[str, str]]]:
    """Read an EPUB's spine + TOC to get ordered chapters.

    Returns (book_title, [{title, href}, ...]).
    """
    with zipfile.ZipFile(epub_path) as archive:
        names = archive.namelist()

        # Find OPF via container.xml.
        opf_path = None
        container = "META-INF/container.xml"
        if container in names:
            text = archive.read(container).decode("utf-8", errors="replace")
            match = re.search(r"full-path\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                opf_path = unquote(match.group(1))
        if not opf_path:
            for name in names:
                if name.endswith(".opf"):
                    opf_path = name
                    break
        if not opf_path:
            raise ValueError(f"No OPF found in {epub_path.name}")

        opf_dir = Path(opf_path).parent
        opf_text = archive.read(opf_path).decode("utf-8", errors="replace")

        # Extract book title.
        title = ""
        title_match = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf_text, re.DOTALL | re.IGNORECASE)
        if title_match:
            title = _strip_tags(title_match.group(1))

        # Build manifest: id -> (href, media-type).
        manifest: dict[str, tuple[str, str]] = {}
        for m in re.finditer(r"<item\b([^>]*?)/?>", opf_text, re.IGNORECASE):
            attrs = m.group(1)
            item_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs)
            href = re.search(r'\bhref\s*=\s*["\']([^"\']+)["\']', attrs)
            media = re.search(r'\bmedia-type\s*=\s*["\']([^"\']+)["\']', attrs)
            if item_id and href:
                manifest[item_id.group(1)] = (
                    unquote(href.group(1)),
                    media.group(1) if media else "",
                )

        # Build spine order.
        spine_ids: list[str] = []
        for m in re.finditer(r"<itemref\b([^>]*)/>", opf_text, re.IGNORECASE):
            attrs = m.group(1)
            idref = re.search(r'\bidref\s*=\s*["\']([^"\']+)["\']', attrs)
            if idref:
                spine_ids.append(idref.group(1))

        # Collect XHTML spine items with content metadata.
        chapters: list[dict[str, Any]] = []
        for sid in spine_ids:
            if sid not in manifest:
                continue
            href, media = manifest[sid]
            if "xhtml" not in media and not href.endswith((".html", ".xhtml", ".htm")):
                continue
            full_path = (opf_dir / href).as_posix()
            try:
                chapter_text = archive.read(full_path).decode("utf-8", errors="replace")
            except KeyError:
                continue
            # Extract first heading as chapter title.
            chap_title = ""
            for hmatch in re.finditer(r"<h[1-4][^>]*>(.*?)</h[1-4]>", chapter_text, re.DOTALL | re.IGNORECASE):
                chap_title = _strip_tags(hmatch.group(1))
                if chap_title:
                    break
            # Extract first <p> text (often contains chapter number in EN EPUBs).
            first_p = ""
            pmatch = re.search(r"<p\b[^>]*>(.*?)</p>", chapter_text, re.DOTALL | re.IGNORECASE)
            if pmatch:
                first_p = _strip_tags(pmatch.group(1))
            if not chap_title:
                chap_title = Path(href).stem
            # Count content paragraphs and total text length.
            p_count = len(re.findall(r"<p\b", chapter_text, re.IGNORECASE))
            text_len = len(_strip_tags(chapter_text))
            is_content = p_count >= 1 or text_len >= 200
            chapters.append({
                "title": chap_title,
                "href": full_path,
                "first_p": first_p,
                "p_count": p_count,
                "text_len": text_len,
                "is_content": is_content,
            })

        # Resolve content hrefs for split-chapter EPUBs where a title-only
        # page (heading but no <p> tags) is immediately followed by a separate
        # content file.  Point title-only pages at the next content-bearing
        # spine item so alignment reads actual paragraph text.
        for _ci, _ch in enumerate(chapters):
            if _ch.get("is_content", True) or _ch.get("p_count", 0) >= 1:
                _ch["content_href"] = _ch["href"]
                continue
            _ch["content_href"] = _ch["href"]
            for _cj in range(_ci + 1, len(chapters)):
                if chapters[_cj].get("p_count", 0) >= 1:
                    _ch["content_href"] = chapters[_cj]["href"]
                    break

        # If spine gave nothing useful, try NCX/nav.
        if not chapters:
            for name in names:
                if name.endswith(".ncx"):
                    ncx_text = archive.read(name).decode("utf-8", errors="replace")
                    for nmatch in re.finditer(r"<navPoint\b.*?</navPoint>", ncx_text, re.DOTALL | re.IGNORECASE):
                        label_match = re.search(r"<text[^>]*>(.*?)</text>", nmatch.group(0), re.DOTALL | re.IGNORECASE)
                        content_match = re.search(r'<content\b[^>]*src\s*=\s*["\']([^"\']+)["\']', nmatch.group(0), re.IGNORECASE)
                        if label_match and content_match:
                            chapters.append({
                                "title": _strip_tags(label_match.group(1)),
                                "href": (opf_dir / unquote(content_match.group(1))).as_posix(),
                                "first_p": "",
                                "p_count": 0,
                                "text_len": 0,
                                "is_content": True,
                                "content_href": (opf_dir / unquote(content_match.group(1))).as_posix(),
                            })

    return title, chapters


# ── Chapter map building ────────────────────────────────────────────────

# Chinese numeral mapping for 第N章 detection.
_ZH_NUMS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "１": 1, "２": 2, "３": 3, "４": 4, "５": 5, "６": 6,
            "７": 7, "８": 8, "９": 9, "０": 0}


def _parse_zh_number(s: str) -> int | None:
    """Parse Chinese numeral or fullwidth digit string to int."""
    s = s.strip()
    if not s:
        return None
    # Handle traditional Chinese numerals with 十 first (二十, 三十, etc.).
    if "十" in s:
        parts = s.split("十")
        tens_str = parts[0].strip()
        ones_str = parts[1].strip() if len(parts) > 1 else ""
        tens = _ZH_NUMS.get(tens_str, 1) if tens_str else 1
        ones = _ZH_NUMS.get(ones_str[:1], 0) if ones_str else 0
        return tens * 10 + ones
    # Handle 百 (hundred): 一百, 二百, etc.
    if "百" in s:
        parts = s.split("百")
        hundreds = _ZH_NUMS.get(parts[0].strip(), 1) if parts[0].strip() else 1
        remainder = parts[1].strip() if len(parts) > 1 else ""
        base = hundreds * 100
        if remainder:
            sub = _parse_zh_number(remainder)
            if sub is not None:
                base += sub
        return base
    # Try fullwidth / regular digits.
    digits = ""
    for ch in s:
        if ch in _ZH_NUMS and _ZH_NUMS[ch] < 10:
            digits += str(_ZH_NUMS[ch])
        elif ch.isdigit():
            digits += ch
        else:
            break
    if digits:
        try:
            return int(digits)
        except ValueError:
            pass
    return _ZH_NUMS.get(s)


def _extract_chapter_ordinal(chapter: dict[str, Any]) -> tuple[int | None, str]:
    """Extract a chapter ordinal number and a semantic label from a chapter dict.

    Returns (ordinal, label) where ordinal is None if undetectable.
    Label is one of: "chapter", "prologue", "epilogue", "front", "back", "".
    """
    title = chapter.get("title", "")
    first_p = chapter.get("first_p", "")

    # Check for prologue/epilogue in title or first_p.
    combined = f"{title} {first_p}".lower()
    if any(w in combined for w in ["prologue", "preface", "序", "開場白", "前言", "導讀"]):
        return 0, "prologue"
    if any(w in combined for w in ["epilogue", "afterword", "結語", "跋", "後記", "尾聲"]):
        return -1, "epilogue"

    # Check for 第N章 in title (Chinese).
    zh_ch = re.search(r"第\s*([０-９\d一二三四五六七八九十百两〇零]+)\s*[章节回]", title)
    if zh_ch:
        num = _parse_zh_number(zh_ch.group(1))
        if num is not None:
            return num, "chapter"

    # Also match bare 第N without 章 (e.g. "第十九" without suffix).
    zh_bare = re.search(r"^第\s*([０-９\d一二三四五六七八九十百两〇零]+)\s*$", title.strip())
    if zh_bare:
        num = _parse_zh_number(zh_bare.group(1))
        if num is not None:
            return num, "chapter"

    # Check for "Chapter N" or "CHAPTER N" in title.
    en_ch = re.search(r"chapter\s*(\d+)", title, re.IGNORECASE)
    if en_ch:
        return int(en_ch.group(1)), "chapter"

    # Check for "Chapter One" style (English word numbers).
    _EN_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                 "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
                 "nineteen": 19, "twenty": 20}
    en_word = re.search(r"chapter\s+(\w+)", title, re.IGNORECASE)
    if en_word and en_word.group(1).lower() in _EN_WORDS:
        return _EN_WORDS[en_word.group(1).lower()], "chapter"

    # Check if first <p> starts with just a number (common in Calibre exports).
    if first_p and re.fullmatch(r"\d{1,3}", first_p.strip()):
        return int(first_p.strip()), "chapter"

    # Check for 第N部 (part separator).
    if re.search(r"第[一二三四五六七八九十\d]+[部卷编]", title):
        return None, "front"

    # Front-matter indicators.
    if any(w in combined for w in ["contents", "目錄", "目录", "index", "索引"]):
        return None, "front"
    if any(w in combined for w in ["copyright", "版權", "版权", "praise", "讚譽", "赞誉",
                                    "acknowledge", "誌謝", "志谢", "about the author",
                                    "作者簡介", "作者简介", "also by", "其他著作",
                                    "dedication", "獻", "献", "brand page"]):
        return None, "back"

    # No signal found.
    return None, ""


def _auto_chapter_map(en_chapters: list[dict[str, Any]], zh_chapters: list[dict[str, Any]]) -> list[list[Any]]:
    """Build a chapter map using content-aware matching.

    Strategy:
    1. Extract chapter ordinals from both sides.
    2. Match content chapters by ordinal (chapter N ↔ chapter N).
    3. Fall back to positional matching for remaining content files.
    4. Skip non-content files (front-matter, back-matter) from matching.
    """
    # Classify chapters on both sides.
    en_classified = [(ch, _extract_chapter_ordinal(ch)) for ch in en_chapters]
    zh_classified = [(ch, _extract_chapter_ordinal(ch)) for ch in zh_chapters]

    # Build ordinal -> chapter index maps for content chapters.
    en_by_ordinal: dict[int, int] = {}
    zh_by_ordinal: dict[int, int] = {}
    en_content: list[tuple[int, dict, int | None, str]] = []
    zh_content: list[tuple[int, dict, int | None, str]] = []

    for i, (ch, (ordinal, label)) in enumerate(en_classified):
        if ch.get("is_content", True) and label not in ("front", "back"):
            en_content.append((i, ch, ordinal, label))
            if ordinal is not None:
                en_by_ordinal[ordinal] = i

    for i, (ch, (ordinal, label)) in enumerate(zh_classified):
        if label not in ("front", "back"):
            zh_content.append((i, ch, ordinal, label))
            if ordinal is not None:
                zh_by_ordinal[ordinal] = i

    pairs: list[list[Any]] = []

    # Phase 1: Match by ordinal.
    matched_en: set[int] = set()
    matched_zh: set[int] = set()
    for ordinal in sorted(set(en_by_ordinal) & set(zh_by_ordinal)):
        en_idx = en_by_ordinal[ordinal]
        zh_idx = zh_by_ordinal[ordinal]
        en_ch = en_chapters[en_idx]
        zh_ch = zh_chapters[zh_idx]
        chapter_id = f"ch{len(pairs) + 1:03d}"
        confidence = 1.0 if ordinal != 0 and ordinal != -1 else 0.8
        pairs.append([
            chapter_id,
            en_ch.get("content_href") or en_ch["href"],
            zh_ch.get("content_href") or zh_ch["href"],
            en_ch["title"], zh_ch["title"], confidence,
        ])
        matched_en.add(en_idx)
        matched_zh.add(zh_idx)

    # Phase 2: Positional fallback for unmatched content chapters.
    remaining_en = [(i, ch) for i, ch, _, _ in en_content if i not in matched_en]
    remaining_zh = [(i, ch) for i, ch, _, _ in zh_content if i not in matched_zh]

    for (en_i, en_ch), (zh_i, zh_ch) in zip(remaining_en, remaining_zh):
        chapter_id = f"ch{len(pairs) + 1:03d}"
        confidence = round(_title_similarity(en_ch["title"], zh_ch["title"]), 2)
        pairs.append([
            chapter_id,
            en_ch.get("content_href") or en_ch["href"],
            zh_ch.get("content_href") or zh_ch["href"],
            en_ch["title"], zh_ch["title"], confidence,
        ])

    return pairs


def _normalize_title(title: str) -> str:
    """Strip common prefixes/suffixes for fuzzy title comparison."""
    t = _strip_tags(title).lower()
    t = re.sub(r"^(chapter|ch|第[〇零一二三四五六七八九十百千两\d]+[章节回部卷]|book|part)\s*[\d.:：\-–—]*\s*", "", t)
    t = re.sub(r"[^\w\s]", "", t).strip()
    return t


def _title_similarity(a: str, b: str) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _detect_target_lang(zh_epub_path: Path) -> str:
    """Auto-detect whether the translation is Traditional or Simplified Chinese."""
    try:
        with zipfile.ZipFile(zh_epub_path) as archive:
            # Sample a few content files.
            sample = ""
            for name in archive.namelist():
                if name.endswith((".html", ".xhtml", ".htm")):
                    try:
                        sample += archive.read(name).decode("utf-8", errors="replace")[:2000]
                    except KeyError:
                        pass
                if len(sample) > 20000:
                    break
        # Count discriminative characters unique to each script variant.
        # These are characters where the traditional and simplified forms are
        # different Unicode codepoints, so they are unambiguous signals.
        trad_chars = frozenset(
            "\u8aaa\u8b80\u9ad4\u6703\u500b\u5f8c\u4f86\u958b\u88e1\u908a"
            "\u9019\u570b\u5b78\u767c\u7d93\u904e\u9084\u5be6\u96e3"
            "\u95dc\u89ba\u89c0\u8a8d\u8b58\u8a18\u8a0e\u8ad6"
            "\u9580\u554f\u8655\u6c92\u6771\u9577\u7576"
        )
        simp_chars = frozenset(
            "\u8bf4\u8bfb\u4f53\u4f1a\u4e2a\u540e\u6765\u5f00\u91cc\u8fb9"
            "\u8fd9\u56fd\u5b66\u53d1\u7ecf\u8fc7\u8fd8\u5b9e\u96be"
            "\u5173\u89c9\u89c2\u8ba4\u8bc6\u8bb0\u8ba8\u8bba"
            "\u95e8\u95ee\u5904\u6ca1\u4e1c\u957f\u5f53"
        )
        trad_only = sum(1 for c in sample if c in trad_chars)
        simp_only = sum(1 for c in sample if c in simp_chars)
        return "zh-Hant" if trad_only >= simp_only else "zh-Hans"
    except Exception:
        return "zh-Hant"


# ── Pairing service ─────────────────────────────────────────────────────


class BilingualPairingService:
    """Manage bilingual pairings between English and Chinese reading documents."""

    def _root(self) -> Path:
        root = get_path_service().get_immersive_reading_bilingual_dir()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _pairing_root(self, pairing_id: str) -> Path:
        return get_path_service().get_immersive_reading_pairing_root(pairing_id)

    def _pairing_path(self, pairing_id: str) -> Path:
        return self._pairing_root(pairing_id) / "pairing.json"

    def _chapter_map_path(self, pairing_id: str) -> Path:
        return self._pairing_root(pairing_id) / "chapter_map.json"

    def _report_path(self, pairing_id: str) -> Path:
        return self._pairing_root(pairing_id) / "report.md"

    def _section_path(self, pairing_id: str, chapter_id: str) -> Path:
        return self._pairing_root(pairing_id) / "sections" / f"{chapter_id}.json"

    def _annotations_path(self, pairing_id: str) -> Path:
        return self._pairing_root(pairing_id) / "annotations.json"

    def _review_export_path(self, pairing_id: str) -> Path:
        return self._pairing_root(pairing_id) / "review_export.md"

    def _original_epub_path(self, document_id: str) -> Path:
        doc_root = get_path_service().get_immersive_reading_document_root(document_id)
        for f in doc_root.iterdir():
            if f.name.startswith("original") and f.suffix == ".epub":
                return f
        raise ValueError(f"No original EPUB found for document {document_id}")

    def _load_pairing(self, pairing_id: str) -> dict[str, Any]:
        data = _read_json(self._pairing_path(pairing_id))
        if not data:
            raise ValueError("Bilingual pairing not found")
        return data

    def _save_pairing(self, pairing_id: str, data: dict[str, Any]) -> None:
        data["updated_at"] = time.time()
        _write_json(self._pairing_path(pairing_id), data)

    def list_pairings(self) -> list[dict[str, Any]]:
        root = self._root()
        result = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not child.name.startswith("pairing_"):
                continue
            pairing_id = child.name[len("pairing_"):]
            data = _read_json(self._pairing_path(pairing_id))
            if data:
                result.append(self._summary(pairing_id, data))
        return result

    def _summary(self, pairing_id: str, data: dict[str, Any]) -> dict[str, Any]:
        aligned = data.get("aligned", False)
        review_count = data.get("review_count", 0)
        chapter_count = data.get("chapter_count")
        if chapter_count is None:
            chapter_map = _read_json(self._chapter_map_path(pairing_id), [])
            chapter_count = len(chapter_map)
        return {
            "pairing_id": pairing_id,
            "en_document_id": data["en_document_id"],
            "zh_document_id": data["zh_document_id"],
            "en_title": data.get("en_title", ""),
            "zh_title": data.get("zh_title", ""),
            "target_lang": data.get("target_lang", "zh-Hant"),
            "translator": data.get("translator", ""),
            "chapter_count": chapter_count,
            "aligned": aligned,
            "review_count": review_count,
            "created_at": data.get("created_at", 0),
            "updated_at": data.get("updated_at", 0),
        }

    def get_pairing(self, pairing_id: str) -> dict[str, Any]:
        data = self._load_pairing(pairing_id)
        chapter_map = _read_json(self._chapter_map_path(pairing_id), [])
        summary = self._summary(pairing_id, data)
        summary["chapter_map"] = [_chapter_entry_to_dict(e) for e in chapter_map]
        return summary

    def pair_documents(
        self, en_document_id: str, zh_document_id: str, target_lang: str | None = None, translator: str = ""
    ) -> dict[str, Any]:
        """Create a bilingual pairing from two imported reading documents."""
        # Deduplicate: reuse an existing pairing for the same document pair
        # instead of creating a second (or third, …) copy.
        for existing in self.list_pairings():
            if (existing["en_document_id"] == en_document_id
                    and existing["zh_document_id"] == zh_document_id):
                return self.get_pairing(existing["pairing_id"])

        en_epub = self._original_epub_path(en_document_id)
        zh_epub = self._original_epub_path(zh_document_id)

        en_title, en_chapters = _read_epub_chapters(en_epub)
        zh_title, zh_chapters = _read_epub_chapters(zh_epub)

        if target_lang is None:
            target_lang = _detect_target_lang(zh_epub)

        chapter_map = _auto_chapter_map(en_chapters, zh_chapters)

        pairing_id = uuid.uuid4().hex[:12]
        root = get_path_service().ensure_immersive_reading_pairing_root(pairing_id)

        data = {
            "pairing_id": pairing_id,
            "en_document_id": en_document_id,
            "zh_document_id": zh_document_id,
            "en_title": en_title,
            "zh_title": zh_title,
            "target_lang": target_lang,
            "translator": translator,
            "aligned": False,
            "chapter_count": len(chapter_map),
            "review_count": 0,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._save_pairing(pairing_id, data)
        _write_json(self._chapter_map_path(pairing_id), chapter_map)

        return self.get_pairing(pairing_id)

    def update_chapter_map(self, pairing_id: str, chapter_map: list[list[str]]) -> dict[str, Any]:
        """Replace the chapter map with a user-edited version."""
        data = self._load_pairing(pairing_id)
        normalized = [_chapter_entry_to_list(e) for e in chapter_map]
        data["aligned"] = False
        data["chapter_count"] = len(normalized)
        self._save_pairing(pairing_id, data)
        _write_json(self._chapter_map_path(pairing_id), normalized)
        # Clear old alignment sections.
        sections_dir = self._pairing_root(pairing_id) / "sections"
        if sections_dir.exists():
            shutil.rmtree(sections_dir)
            sections_dir.mkdir(parents=True, exist_ok=True)
        return self.get_pairing(pairing_id)

    def align(self, pairing_id: str, force: bool = False) -> dict[str, Any]:
        """Run paragraph alignment for every mapped chapter."""
        data = self._load_pairing(pairing_id)
        if data.get("aligned") and not force:
            return self.get_pairing(pairing_id)

        chapter_map = _read_json(self._chapter_map_path(pairing_id), [])
        en_epub = self._original_epub_path(data["en_document_id"])
        zh_epub = self._original_epub_path(data["zh_document_id"])

        total_review = 0
        report_lines = [
            "# Bilingual Alignment Report",
            "",
            "Non-1:1 groups and low-confidence rows are listed for review.",
            "",
        ]

        overrides = self.load_alignment_overrides(pairing_id)

        with zipfile.ZipFile(en_epub) as en_archive, zipfile.ZipFile(zh_epub) as zh_archive:
            for entry in chapter_map:
                chapter_id, en_href, zh_href = entry[0], entry[1], entry[2]
                try:
                    en_xml = en_archive.read(en_href).decode("utf-8", errors="replace")
                except KeyError:
                    continue
                try:
                    zh_xml = zh_archive.read(zh_href).decode("utf-8", errors="replace")
                except KeyError:
                    continue
                chapter_overrides = overrides.get(chapter_id, [])
                result = extract_align_pairs(en_xml, zh_xml, overrides={chapter_id: chapter_overrides} if chapter_overrides else {}, chapter=chapter_id)
                _write_json(self._section_path(pairing_id, chapter_id), result)
                review = result.get("review", [])
                total_review += len(review)
                if review:
                    report_lines.append(f"## {chapter_id}: pairs={result['pairs']}, review={len(review)}")
                    for item in review:
                        report_lines.append(f"- {item['shape']} cost={item['cost']} | EN: {item.get('en_preview', '')[:80]}")
                    report_lines.append("")

        self._report_path(pairing_id).write_text("\n".join(report_lines), encoding="utf-8")
        data["aligned"] = True
        data["review_count"] = total_review
        self._save_pairing(pairing_id, data)
        return self.get_pairing(pairing_id)

    def get_bilingual_section(self, pairing_id: str, chapter_id: str) -> dict[str, Any]:
        """Return aligned paragraph pairs for one chapter."""
        data = self._load_pairing(pairing_id)
        if not data.get("aligned"):
            raise ValueError("Pairing has not been aligned yet")
        section = _read_json(self._section_path(pairing_id, chapter_id))
        if not section:
            raise ValueError(f"Section {chapter_id} not found")
        return section

    def get_report(self, pairing_id: str) -> str:
        """Return the alignment review report as markdown text."""
        report_path = self._report_path(pairing_id)
        if not report_path.exists():
            return "# No alignment report yet\n\nRun alignment first."
        return report_path.read_text(encoding="utf-8")

    def export_epub(self, pairing_id: str) -> Path:
        """Build and return a bilingual EPUB file path."""
        data = self._load_pairing(pairing_id)
        chapter_map = _read_json(self._chapter_map_path(pairing_id), [])
        # Convert to the format expected by build_bilingual_epub: [id, en, zh].
        chapter_map_data = [[e[0], e[1], e[2]] for e in chapter_map]

        en_epub = self._original_epub_path(data["en_document_id"])
        zh_epub = self._original_epub_path(data["zh_document_id"])

        # Determine a label based on target language.
        summary_label = "\u5c55\u5f00\u4e2d\u6587" if data["target_lang"] == "zh-Hans" else "\u5c55\u958b\u4e2d\u6587"
        title_suffix = " (\u53cc\u8bed\u53ef\u5c55\u5f00)" if data["target_lang"] == "zh-Hans" else " (\u96d9\u8a9e\u53ef\u5c55\u958b)"

        output = self._pairing_root(pairing_id) / f"{Path(data.get('en_title', 'book')).stem}_bilingual.epub"
        build_bilingual_epub(
            english_epub=en_epub,
            translation_epub=zh_epub,
            chapter_map_data=chapter_map_data,
            output=output,
            target_lang=data.get("target_lang", "zh-Hant"),
            translator=data.get("translator", ""),
            title_suffix=title_suffix,
            summary_label=summary_label,
            alignment_overrides=self.load_alignment_overrides(pairing_id),
        )
        return output

    # ── Annotations (review feedback loop) ───────────────────────────

    def add_annotation(
        self,
        pairing_id: str,
        chapter_id: str,
        group_index: int,
        issue_type: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Record a user-flagged alignment issue for later review/fix.

        issue_type: misalignment | wrong_chapter | missing_translation | translation_error | other
        """
        data = self._load_pairing(pairing_id)
        annotations = _read_json(self._annotations_path(pairing_id), [])

        # Pull the group context from the stored section for the report.
        section = _read_json(self._section_path(pairing_id, chapter_id), {})
        groups = section.get("groups", [])
        group = groups[group_index] if 0 <= group_index < len(groups) else {}

        annotation = {
            "id": uuid.uuid4().hex[:12],
            "pairing_id": pairing_id,
            "chapter_id": chapter_id,
            "chapter_title": section.get("en_title", chapter_id),
            "group_index": group_index,
            "issue_type": issue_type,
            "note": note.strip(),
            "en_text": " ".join(group.get("en", []))[:500],
            "zh_text": " ".join(group.get("zh", []))[:500],
            "shape": group.get("shape", ""),
            "cost": group.get("cost", 0),
            "status": "open",
            "created_at": time.time(),
        }
        annotations.append(annotation)
        _write_json(self._annotations_path(pairing_id), annotations)

        data["annotation_count"] = len(annotations)
        self._save_pairing(pairing_id, data)
        return annotation

    def list_annotations(self, pairing_id: str, status: str | None = None) -> list[dict[str, Any]]:
        annotations = _read_json(self._annotations_path(pairing_id), [])
        if status:
            annotations = [a for a in annotations if a.get("status") == status]
        return annotations

    def resolve_annotation(self, pairing_id: str, annotation_id: str, resolved: bool = True) -> dict[str, Any]:
        annotations = _read_json(self._annotations_path(pairing_id), [])
        for ann in annotations:
            if ann["id"] == annotation_id:
                ann["status"] = "resolved" if resolved else "open"
                ann["resolved_at"] = time.time() if resolved else None
                break
        _write_json(self._annotations_path(pairing_id), annotations)
        data = self._load_pairing(pairing_id)
        data["annotation_count"] = len([a for a in annotations if a.get("status") == "open"])
        self._save_pairing(pairing_id, data)
        return {"status": "ok"}

    def delete_annotation(self, pairing_id: str, annotation_id: str) -> None:
        annotations = _read_json(self._annotations_path(pairing_id), [])
        annotations = [a for a in annotations if a["id"] != annotation_id]
        _write_json(self._annotations_path(pairing_id), annotations)
        data = self._load_pairing(pairing_id)
        data["annotation_count"] = len([a for a in annotations if a.get("status") == "open"])
        self._save_pairing(pairing_id, data)

    def export_review_report(self, pairing_id: str) -> Path:
        """Export all open annotations as a structured markdown report.

        This file is designed for Codex/agent consumption: each issue lists
        the chapter, group index, EN/ZH text snippets, the user's note, and
        the suggested fix action. An agent can read this, produce alignment
        overrides JSON, and the user can re-align.
        """
        data = self._load_pairing(pairing_id)
        annotations = _read_json(self._annotations_path(pairing_id), [])
        open_issues = [a for a in annotations if a.get("status") == "open"]

        lines = [
            f"# Bilingual Review Report: {data.get('en_title', pairing_id)}",
            "",
            f"Pairing ID: `{pairing_id}`",
            f"Open issues: {len(open_issues)}",
            "",
            "## How to fix",
            "",
            "Each issue below is a paragraph-group the user flagged while reading.",
            "To fix, create alignment overrides in JSON format:",
            "",
            '```json',
            '{"overrides": [{"chapter": "<chapter_id>", "english_ids": ["<id>"], "translation_ids": ["<id>"]}]}',
            '```',
            "",
            "Then call `POST /api/v1/immersive-reading/bilingual/{pairing_id}/align?force=true`",
            "with the overrides applied, or re-run with a corrected chapter map.",
            "",
            "---",
            "",
        ]

        type_labels = {
            "misalignment": "Misaligned paragraphs",
            "wrong_chapter": "Wrong chapter mapping",
            "missing_translation": "Missing translation",
            "translation_error": "Translation quality issue",
            "other": "Other issue",
        }

        for i, ann in enumerate(open_issues, 1):
            label = type_labels.get(ann["issue_type"], ann["issue_type"])
            lines.append(f"### Issue {i}: {label}")
            lines.append(f"- **Chapter**: `{ann['chapter_id']}` ({ann.get('chapter_title', '')})")
            lines.append(f"- **Group index**: {ann['group_index']}")
            lines.append(f"- **Shape**: {ann.get('shape', '?')} (cost: {ann.get('cost', '?')})")
            if ann.get("note"):
                lines.append(f"- **User note**: {ann['note']}")
            lines.append(f"- **English**: {ann.get('en_text', '')[:300]}")
            lines.append(f"- **Chinese**: {ann.get('zh_text', '')[:300]}")
            lines.append("")

        report_path = self._review_export_path(pairing_id)
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    def load_alignment_overrides(self, pairing_id: str) -> dict[str, list[dict]]:
        """Load user-provided alignment overrides JSON for re-alignment."""
        overrides_path = self._pairing_root(pairing_id) / "alignment_overrides.json"
        if not overrides_path.exists():
            return {}
        raw = json.loads(overrides_path.read_text(encoding="utf-8"))
        items = raw.get("overrides", raw) if isinstance(raw, dict) else raw
        result: dict[str, list[dict]] = {}
        for item in items:
            result.setdefault(item["chapter"], []).append(item)
        return result

    def save_alignment_overrides(self, pairing_id: str, overrides_json: str) -> dict[str, Any]:
        """Save alignment overrides JSON (from Codex fix) for the next re-align."""
        overrides_path = self._pairing_root(pairing_id) / "alignment_overrides.json"
        overrides_path.write_text(overrides_json, encoding="utf-8")
        # Mark pairing as needing re-alignment.
        data = self._load_pairing(pairing_id)
        data["aligned"] = False
        self._save_pairing(pairing_id, data)
        return {"status": "saved"}

    def delete_pairing(self, pairing_id: str) -> None:
        root = self._pairing_root(pairing_id)
        if root.exists():
            shutil.rmtree(root)


# Singleton accessor.
_pairing_service: BilingualPairingService | None = None


def get_pairing_service() -> BilingualPairingService:
    global _pairing_service
    if _pairing_service is None:
        _pairing_service = BilingualPairingService()
    return _pairing_service
