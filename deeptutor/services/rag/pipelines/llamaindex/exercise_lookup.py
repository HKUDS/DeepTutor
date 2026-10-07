"""Read-only, structural exercise lookup ahead of semantic retrieval.

Only completed parses of PDFs actually present in the selected KB are read.
No OCR, model call, index write, or global cross-KB search is performed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

from deeptutor.services.parsing.cache import source_hash_from_path

MAX_QUESTIONS = 30
MAX_CONTENT = 24000
_SKIP = {"header", "footer", "page_header", "page_footer", "page_number"}
_PAIR = re.compile(r"(?<![\dA-Za-z.])(\d{1,3})\s*[-.]\s*(\d{1,3})(?!\d|[.-]\d)")
_CHAPTER = re.compile(r"第\s*([零〇一二两三四五六七八九十百\d]+)\s*章")
_START = re.compile(r"^\s*(?:(\d{1,3})\s*[-.]\s*(\d{1,3})[.、]?\s*|(\d{1,3})[.、]\s+)(?=\S)")
_INTENT = re.compile(
    r"习题|思考题|练习题|题干|题目|第.{0,8}题|解答|怎么做|怎么解|problem|exercise", re.I
)


def _normal(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(str.maketrans("—–−－", "----"))


def _number(text: str) -> int:
    if text.isdigit():
        return int(text)
    digits = dict(zip("零〇一二两三四五六七八九", [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    value = current = 0
    for char in text:
        if char in digits:
            current = digits[char]
        elif char in "十百":
            value += (current or 1) * (10 if char == "十" else 100)
            current = 0
    return value + current


def requested_exercises(query: str) -> tuple[list[tuple[int, int]], str | None]:
    """Do not interpret formula/figure/section queries or arithmetic as exercises."""
    query = _normal(query)
    explicit = bool(_INTENT.search(query))
    if not explicit and re.search(
        r"公式|方程|图\s*\d|式\s*\d|节|section|equation|figure", query, re.I
    ):
        return [], None
    matches = list(_PAIR.finditer(query))
    bare = re.sub(r"[\d\s.,、;:()\-]+", "", query) == ""
    lookup_request = bool(re.search(r"找|查找|查一下|查下|搜索|lookup|find", query, re.I))
    if not explicit and not bare and not lookup_request:
        return [], None
    keys = []
    for match in matches:
        key = (int(match[1]), int(match[2]))
        if all(key) and key not in keys:
            keys.append(key)
    chapter = _CHAPTER.search(query)
    if not keys and chapter:
        for match in re.finditer(r"第?\s*(\d{1,3})\s*题", query[chapter.end() :]):
            key = (_number(chapter[1]), int(match[1]))
            if all(key) and key not in keys:
                keys.append(key)
    # Bounded explicit ranges, e.g. 2-13 至 2-15.
    for left, right in zip(matches, matches[1:]):
        if re.fullmatch(r"\s*(?:到|至|~|～)\s*", query[left.end() : right.start()]):
            a, b = (int(left[1]), int(left[2])), (int(right[1]), int(right[2]))
            if a[0] == b[0] and 0 < b[1] - a[1] < MAX_QUESTIONS:
                pos = keys.index(a)
                keys[pos : pos + 1] = [(a[0], n) for n in range(a[1], b[1])]
    kind = (
        "思考题"
        if "思考题" in query
        else "习题"
        if re.search(r"习题|练习题|exercise", query, re.I)
        else None
    )
    return list(dict.fromkeys(keys)), kind


def _text(block: dict[str, Any]) -> str:
    parts = []
    for key in (
        "text",
        "content",
        "body",
        "code_body",
        "table_body",
        "image_caption",
        "image_footnote",
        "table_caption",
        "table_footnote",
    ):
        value = block.get(key)
        if isinstance(value, list):
            value = "\n".join(str(v) for v in value)
        if isinstance(value, str) and value.strip() and value.strip() not in parts:
            parts.append(value.strip())
    return "\n\n".join(parts)


def _page(block: dict[str, Any]) -> int | None:
    try:
        return (
            int(block["original_page"])
            if block.get("original_page") is not None
            else int(block["page_idx"]) + 1
        )
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class Exercise:
    """One numbered exercise and its contiguous parsed source blocks."""

    chapter: int
    number: int
    kind: str
    ordinal: int
    parts: list[str] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    images: bool = False


def collect_exercises(blocks: list[dict[str, Any]]) -> list[Exercise]:
    """Join problem text, equations and tables within exercise sections."""
    chapter = 0
    section_chapter = None
    kind = None
    current = None
    exercises = []
    for ordinal, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("type") in _SKIP:
            continue
        text = _text(block)
        normal = _normal(text)
        compact = re.sub(r"\s+", "", normal)
        # TOC lines are not chapter boundaries or exercise headings.
        toc = "……" in text or "..." in text or "…" in text
        heading = _CHAPTER.match(normal)
        chapter_title = heading and (
            block.get("text_level") or not re.search(r"[\d。,$，]", normal[heading.end() :])
        )
        if chapter_title and not toc and len(text) < 100 and "\n" not in text:
            chapter = _number(heading[1])
            kind = None
            current = None
            continue
        if compact in {"习题", "练习题", "思考题", "Exercises", "Problems"}:
            kind = "思考题" if compact == "思考题" else "习题"
            current = None
            section_chapter = None
            continue
        if not kind:
            continue
        caption = re.fullmatch(r"(?:习题|思考题)\s*(\d+)\s*[-.]\s*(\d+)", normal)
        if caption and block.get("type") != "image":
            # OCR occasionally drops the next question's opening paragraph.
            # A later question's figure caption still gives us a boundary;
            # never append its continuation to the preceding problem.
            if current and int(caption[1]) == current.chapter and int(caption[2]) > current.number:
                current = None
            continue
        # A new numbered section ends the exercise area even when OCR omitted
        # the intervening chapter title (common in image-based title pages).
        if block.get("text_level") and _START.match(normal):
            kind = None
            current = None
            continue
        if block.get("type") == "image":
            if current is not None:
                labels = [(int(m[1]), int(m[2])) for m in _PAIR.finditer(normal)]
                if labels and (current.chapter, current.number) not in labels:
                    if any(c == current.chapter and n > current.number for c, n in labels):
                        current = None
                    continue
                current.images = True
                if _page(block) is not None:
                    current.pages.add(_page(block))
            # Captions are image metadata, never the start of another exercise.
            continue
        if toc:
            current = None
            kind = None
            continue
        if not text or re.fullmatch(r"\d+", text):
            continue
        # Some parsers put consecutive numbered problems in one text block.
        pieces = (
            re.split(r"\n(?=\s*\d{1,3}(?:[-.]\d{1,3}[.、]?\s*|[.、]\s+)\S)", text)
            if block.get("type") == "text"
            else [text]
        )
        for piece in pieces:
            match = _START.match(_normal(piece)) if block.get("type") == "text" else None
            if match:
                c = int(match[1]) if match[1] else chapter
                n = int(match[2] or match[3])
                # A different chapter here is usually a decimal measurement.
                if c and n and (section_chapter is None or c == section_chapter):
                    chapter = c
                    section_chapter = c
                    current = Exercise(c, n, kind, ordinal)
                    exercises.append(current)
            if current is not None:
                current.parts.append(piece)
                if _page(block) is not None:
                    current.pages.add(_page(block))
    return exercises


@lru_cache(maxsize=32)
def _source_hash(path: str, mtime: int, size: int) -> str:
    # mtime and size invalidate the bounded cache when a source changes.
    return source_hash_from_path(Path(path))


@lru_cache(maxsize=8)
def _parsed(path: str, mtime: int, size: int) -> tuple[Exercise, ...]:
    blocks = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(collect_exercises(blocks)) if isinstance(blocks, list) else ()


def _parse_for(source: Path, cache_root: Path) -> Path | None:
    stat = source.stat()
    digest = _source_hash(str(source), stat.st_mtime_ns, stat.st_size)
    root = cache_root / digest[:2] / digest
    manifests = sorted(
        root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
    )
    for manifest in manifests:
        if manifest.parent.name.startswith(".") or not manifest.resolve().is_relative_to(
            cache_root.resolve()
        ):
            continue
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("source_hash") != digest:
                continue
            files = sorted(manifest.parent.rglob("*_content_list.json"))
            files = [
                p
                for p in files
                if not any(s.startswith(".") for s in p.relative_to(manifest.parent).parts)
                and p.resolve().is_relative_to(manifest.parent.resolve())
            ]
            full = [p for p in files if p.name == "full_content_list.json"]
            if full or files:
                return (full or files)[0]
        except (OSError, ValueError, TypeError):
            continue
    return None


def lookup_exercises(query: str, kb_dir: Path, cache_root: Path) -> dict[str, Any] | None:
    """Return exact candidates from ready PDF parses, or allow normal retrieval.

    Sources must belong to the selected KB. Missing structured parses return
    ``None``; supported parses report each number as found, ambiguous or absent.
    No parse, index, embedding or settings files are created or modified.
    """
    keys, kind = requested_exercises(query)
    if not keys:
        return None
    if len(keys) > MAX_QUESTIONS:
        content = f"本次包含 {len(keys)} 个题号，请分批检索，每批不超过 {MAX_QUESTIONS} 题，以免遗漏题干。"
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": [],
            "provider": "llamaindex",
            "retrieval_method": "exercise_exact",
            "exercise_status": [],
        }
    candidates = {key: [] for key in keys}
    supported = False
    raw = kb_dir / "raw"
    for source in sorted(raw.glob("*.pdf")):
        if not source.resolve().is_relative_to(raw.resolve()):
            continue
        try:
            parsed = _parse_for(source, cache_root)
            if parsed is None:
                continue
            stat = parsed.stat()
            exercises = _parsed(str(parsed), stat.st_mtime_ns, stat.st_size)
            if not exercises:
                continue
            supported = True
            for exercise in exercises:
                key = (exercise.chapter, exercise.number)
                if key in candidates and (kind is None or exercise.kind == kind):
                    candidates[key].append((source, exercise))
        except (OSError, ValueError, TypeError):
            continue
    if not supported:
        return None
    parts = [
        "以下按题号定位现有解析原文；未定位到的题目不代表原书不存在，不能用图号、式号或相似题替代。"
    ]
    sources = []
    statuses = []
    for key, matches in candidates.items():
        label = f"{key[0]}-{key[1]}"
        status = "ambiguous" if len(matches) > 1 else "found" if matches else "not_found"
        statuses.append({"question": label, "status": status, "matches": len(matches)})
        if not matches:
            parts.append(
                f"【{label}】未在当前解析的习题/思考题区域定位到；请核对书籍、章节、题型，必要时检查原页。"
            )
            continue
        if len(matches) > 1:
            parts.append(
                f"【{label}】存在 {len(matches)} 个候选，下面分别标明书名与题型，请勿混合题干。"
            )
        for source, exercise in matches[:4]:
            pages = sorted(exercise.pages)
            page_label = ", ".join(map(str, pages)) or "未知"
            text = "\n\n".join(exercise.parts)
            title = f"{source.name}｜{exercise.kind} {label}｜PDF页 {page_label}"
            note = (
                "\n[本题涉及图示；文本不能代替图形条件，请核对上述原PDF页。]"
                if exercise.images
                else ""
            )
            excerpt = f"【{title}】\n{text}{note}"
            if sum(map(len, parts)) + len(excerpt) > MAX_CONTENT:
                parts.append(
                    f"【{label}】内容超出本次返回长度，请缩小题号范围或检查原PDF页 {page_label}。"
                )
                statuses[-1]["status"] = "needs_single_query"
                continue
            parts.append(excerpt)
            chunk_id = (
                "exercise-"
                + hashlib.sha256(
                    f"{source}:{key}:{exercise.kind}:{exercise.ordinal}".encode()
                ).hexdigest()[:20]
            )
            sources.append(
                {
                    "title": title,
                    "content": text[:200],
                    "source": str(source),
                    "page": page_label,
                    "chunk_id": chunk_id,
                    "score": 1.0,
                    "question_number": label,
                    "exercise_kind": exercise.kind,
                    "requires_page_review": exercise.images,
                }
            )
    content = "\n\n".join(parts)
    return {
        "query": query,
        "answer": content,
        "content": content,
        "sources": sources,
        "provider": "llamaindex",
        "retrieval_method": "exercise_exact",
        "exercise_status": statuses,
    }
