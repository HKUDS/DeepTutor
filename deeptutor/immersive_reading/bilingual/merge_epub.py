"""Generate a bilingual EPUB (English primary + expandable Chinese panels).

Wraps the alignment core into a full EPUB build: extract the English EPUB,
inject expandable Chinese translation blocks into each mapped chapter, add
CSS, rewrite OPF metadata, and repackage. The English package stays intact
(cover, images, English-only pages, navigation).
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Any, List, Sequence, Tuple
from urllib.parse import unquote
import zipfile

from deeptutor.immersive_reading.bilingual.align import (
    ID_RE,
    EnPara,
    Group,
    ZhUnit,
    _prefix_zh_ids,
    align_groups,
    extract_en_paragraphs,
    extract_zh_units,
    fragment_inner,
    sentence_partitions,
    split_sentences,
)

CSS = """
/* epub-bilingual-translator */
/* Bilingual expandable blocks */
details.zh-details { margin: .35em 0 1.1em; padding: .45em .75em; background: #f8f9fa; border-left: 3px solid #0066cc; border-radius: 4px; }
details.zh-details summary { cursor: pointer; color: #0066cc; font-weight: 600; font-size: .92em; }
details.zh-details[open] { background: #f1f5f9; }
details.zh-details[open] summary::after { content: " \u00b7 \u6536\u8d77\u4e2d\u6587"; color: #64748b; font-weight: 500; }
details.zh-details .zh-content p, details.zh-details .zh-content blockquote { line-height: 1.7; color: #1e293b; font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Heiti TC", "Microsoft JhengHei", "Noto Serif CJK TC", serif; font-size: .95em; }
details.zh-details .zh-subheading { font-size: 1.02em; font-weight: 700; color: #0f172a; }
div.zh-footnotes { margin-top: 2em; padding-top: 1em; border-top: 1px solid #cbd5e1; font-size: .9em; }
@media (prefers-color-scheme: dark) { details.zh-details { background: #1e293b; border-left-color: #38bdf8; } details.zh-details[open] { background: #0f172a; } details.zh-details summary { color: #38bdf8; } details.zh-details .zh-content p, details.zh-details .zh-content blockquote { color: #e2e8f0; } }
"""


def _outer_attrs(attrs: str, fragment_index: int) -> str:
    from deeptutor.immersive_reading.bilingual.align import attr_id

    if fragment_index == 0 or not attr_id(attrs):
        return attrs
    original = attr_id(attrs)
    return ID_RE.sub(
        lambda m: f'id={m.group(1)}{original}-bilingual-{fragment_index + 1}{m.group(1)}', attrs, count=1
    )


def _make_en(para: EnPara, inner: str, fragment_index: int = 0) -> str:
    return f"<{para.tag}{_outer_attrs(para.attrs, fragment_index)}>{inner}</{para.tag}>"


def _make_details(unit: ZhUnit, label: str) -> str:
    content = (unit.heading_html + "\n" if unit.heading_html else "") + f"<{unit.tag}{unit.attrs}>{unit.inner}</{unit.tag}>"
    return (
        f'<details class="zh-details">\n'
        f'  <summary class="zh-summary">{label}</summary>\n'
        f'  <div class="zh-content">{content}</div>\n'
        f"</details>\n"
    )


def _render_group(group: Group, en: Sequence[EnPara], zh: Sequence[ZhUnit], label: str) -> List[Tuple[int, str]]:
    """Render one aligned group into XHTML markup fragments keyed by EN paragraph index."""
    en_group, zh_group = en[group.en_start:group.en_end], zh[group.zh_start:group.zh_end]
    # 1 EN paragraph mapped to N ZH units: split into sentence fragments and interleave.
    if len(en_group) == 1 and len(zh_group) > 1:
        para = en_group[0]
        sentences = split_sentences(para.text)
        parts = sentence_partitions(sentences, zh_group)
        if len(parts) == len(zh_group):
            ends, cursor = [], 0
            for _, end in parts:
                cursor = end
                ends.append(sum(len(s) for s in sentences[:cursor]) + max(0, cursor - 1))
            inners = fragment_inner(para.inner, ends)
            return [
                (group.en_start, _make_en(para, inner, index) + "\n" + _make_details(unit, label))
                for index, (inner, unit) in enumerate(zip(inners, zh_group))
            ]
    if len(en_group) == len(zh_group):
        return [
            (group.en_start + index, _make_en(item, item.inner) + "\n" + _make_details(unit, label))
            for index, (item, unit) in enumerate(zip(en_group, zh_group))
        ]
    # Fall back: render all EN paragraphs, attach all ZH details after the last one.
    rendered = [(group.en_start + index, _make_en(item, item.inner)) for index, item in enumerate(en_group)]
    if rendered and zh_group:
        idx, markup = rendered[-1]
        rendered[-1] = (idx, markup + "".join(_make_details(unit, label) for unit in zh_group))
    return rendered


def _process_chapter(
    en_xml: str, zh_xml: str, chapter: str, overrides: dict[str, List[dict]], label: str
) -> Tuple[str, dict[str, Any]]:
    """Inject bilingual blocks into a single chapter's XHTML."""
    en = extract_en_paragraphs(en_xml)
    zh, zh_footnotes = extract_zh_units(zh_xml)
    if not en or not zh:
        return en_xml, {"chapter": chapter, "pairs": 0, "groups": [], "low_conf": []}
    groups = align_groups(en, zh, chapter, overrides)
    by_para: dict[int, str] = {}
    for group in groups:
        for index, markup in _render_group(group, en, zh, label):
            by_para[index] = by_para.get(index, "") + markup
    chunks: List[str] = []
    cursor = en[0].start
    for index, para in enumerate(en):
        chunks.append(en_xml[cursor:para.start])
        chunks.append(by_para.get(index, para.source))
        cursor = para.end
    chunks.append(en_xml[cursor:en[-1].end])
    output = en_xml[:en[0].start] + "".join(chunks) + en_xml[en[-1].end:]
    if zh_footnotes:
        footnote_markup = _prefix_zh_ids(zh_footnotes)
        footnote_markup = re.sub(r"^[^<]+", "", footnote_markup.strip())
        footnote_markup = re.sub(r"</div>\s*</body>.*$", "", footnote_markup, flags=re.DOTALL)
        footnote_markup = re.sub(r"</body>.*$", "", footnote_markup, flags=re.DOTALL)
        output = output.replace("</body>", f'\n<div class="zh-footnotes">\n<hr/>\n{footnote_markup}\n</div>\n</body>', 1)
    low_conf = []
    report_groups = []
    for group in groups:
        en_slice = en[group.en_start:group.en_end]
        zh_slice = zh[group.zh_start:group.zh_end]
        en_len = sum(item.feats["len"] for item in en_slice)
        zh_len = sum(item.feats["len"] for item in zh_slice)
        ratio = en_len / max(1, zh_len)
        shape = f"{group.en_end - group.en_start}:{group.zh_end - group.zh_start}"
        record = {
            "shape": shape,
            "cost": round(group.cost, 3),
            "len_ratio": round(ratio, 3),
            "forced": group.forced,
            "en": " ".join(item.text for item in en_slice)[:180],
            "zh": " ".join(item.text for item in zh_slice)[:180],
        }
        if shape != "1:1" or abs(group.cost) > 1.2 or ratio > 3.5 or ratio < 0.28:
            low_conf.append(record)
        if shape != "1:1" or group.forced:
            report_groups.append(record)
    return output, {"chapter": chapter, "pairs": len(zh), "groups": report_groups, "low_conf": low_conf}


def _stylesheet_hrefs(chapter_xml: str) -> List[str]:
    hrefs = []
    for match in re.finditer(r"<link\b[^>]*>", chapter_xml, flags=re.IGNORECASE):
        tag = match.group(0)
        rel = re.search(r"\brel\s*=\s*['\"]([^'\"]+)['\"]", tag, flags=re.IGNORECASE)
        href = re.search(r"\bhref\s*=\s*['\"]([^'\"]+)['\"]", tag, flags=re.IGNORECASE)
        if rel and href and "stylesheet" in rel.group(1).lower():
            hrefs.append(href.group(1).split("#", 1)[0].split("?", 1)[0])
    return hrefs


_CSS_TAG_MARKER = "epub-bilingual-translator"


def _inject_css(work: Path, chapter_paths: Sequence[Path]) -> None:
    linked: set[Path] = set()
    inline: List[Tuple[Path, str]] = []
    root = work.resolve()
    for chapter_path in chapter_paths:
        xml = chapter_path.read_text(encoding="utf-8")
        chapter_css: List[Path] = []
        for href in _stylesheet_hrefs(xml):
            if not href or href.startswith(("http:", "https:", "data:")):
                continue
            candidate = (chapter_path.parent / unquote(href)).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_file() and candidate.suffix.lower() == ".css":
                chapter_css.append(candidate)
                linked.add(candidate)
        if not chapter_css:
            inline.append((chapter_path, xml))
    for css_path in sorted(linked):
        css = css_path.read_text(encoding="utf-8")
        if _CSS_TAG_MARKER not in css:
            css_path.write_text(css.rstrip() + "\n\n" + CSS.lstrip(), encoding="utf-8")
    for chapter_path, xml in inline:
        if _CSS_TAG_MARKER in xml:
            continue
        style = f'<style type="text/css">{CSS}</style>'
        if re.search(r"</head\s*>", xml, flags=re.IGNORECASE):
            xml = re.sub(r"</head\s*>", style + "\n</head>", xml, count=1, flags=re.IGNORECASE)
        else:
            xml = style + "\n" + xml
        chapter_path.write_text(xml, encoding="utf-8")


def _find_package_opf(work: Path) -> Path:
    container = work / "META-INF" / "container.xml"
    if container.exists():
        match = re.search(r"full-path\s*=\s*['\"]([^'\"]+)['\"]", container.read_text(encoding="utf-8"))
        if match:
            candidate = work / unquote(match.group(1))
            if candidate.exists():
                return candidate
    candidates = sorted(work.rglob("*.opf"))
    if not candidates:
        raise FileNotFoundError(f"No OPF package found under {work}")
    return candidates[0]


def build_bilingual_epub(
    english_epub: Path,
    translation_epub: Path,
    chapter_map_data: List[Any],
    output: Path,
    *,
    source_lang: str = "en",
    target_lang: str = "zh-Hant",
    translator: str = "",
    title_suffix: str = " (Bilingual Expandable)",
    summary_label: str = "\u5c55\u5f00\u4e2d\u6587",
    alignment_overrides: dict[str, List[dict]] | None = None,
    work_dir: Path | None = None,
) -> List[dict]:
    """Build a bilingual EPUB from an English base + official translation.

    Args:
        english_epub: path to the English EPUB (becomes the package base).
        translation_epub: path to the official Chinese translation EPUB.
        chapter_map_data: list of ``[chapter_id, en_xhtml_path, zh_xhtml_path]``
            or ``{"id":..., "english":..., "translation":...}`` entries.
        output: destination ``.epub`` path.
        target_lang: target language code (``zh-Hant`` or ``zh-Hans``).
        translator: optional translator name for OPF metadata.
        Returns: per-chapter alignment stats for the report.
    """
    overrides = alignment_overrides or {}
    work = work_dir or Path(output.parent) / f".bilingual_work_{output.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    with zipfile.ZipFile(english_epub) as archive:
        archive.extractall(work)

    processed_paths: List[Path] = []
    stats: List[dict] = []
    with zipfile.ZipFile(translation_epub) as zh_archive:
        for entry in chapter_map_data:
            if isinstance(entry, dict):
                chapter, en_file, zh_file = entry["id"], entry["english"], entry["translation"]
            else:
                chapter, en_file, zh_file = entry[0], entry[1], entry[2]
            path = work / en_file
            if not path.exists():
                continue
            try:
                zh_content = zh_archive.read(zh_file).decode("utf-8")
            except KeyError:
                continue
            xml, stat = _process_chapter(
                path.read_text(encoding="utf-8"),
                zh_content,
                chapter,
                overrides,
                summary_label,
            )
            path.write_text(xml, encoding="utf-8")
            processed_paths.append(path)
            stats.append(stat)

    _inject_css(work, processed_paths)

    # Update OPF metadata.
    opf_path = _find_package_opf(work)
    opf = opf_path.read_text(encoding="utf-8")
    if f"<dc:language>{target_lang}</dc:language>" not in opf:
        source = f"<dc:language>{source_lang}</dc:language>"
        if source in opf:
            opf = opf.replace(source, source + f"\n    <dc:language>{target_lang}</dc:language>")
        else:
            opf = opf.replace("</metadata>", f"<dc:language>{source_lang}</dc:language>\n<dc:language>{target_lang}</dc:language>\n</metadata>")
    if translator and translator not in opf:
        opf = opf.replace(
            "</metadata>",
            f'  <dc:contributor id="trans1">{translator}</dc:contributor>\n  <meta property="role" refines="#trans1" scheme="marc:relators">trl</meta>\n</metadata>',
        )
    if title_suffix and title_suffix not in opf:
        opf = re.sub(r"(<dc:title[^>]*>)(.*?)(</dc:title>)", rf"\1\2{title_suffix}\3", opf, count=1)
    opf_path.write_text(opf, encoding="utf-8")

    # Repackage EPUB.
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w") as archive:
        mimetype = work / "mimetype"
        if mimetype.exists():
            archive.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        for root, _, names in os.walk(work):
            for name in names:
                p = Path(root) / name
                relative = p.relative_to(work).as_posix()
                if relative != "mimetype":
                    archive.write(p, relative, compress_type=zipfile.ZIP_DEFLATED)

    shutil.rmtree(work, ignore_errors=True)
    return stats
