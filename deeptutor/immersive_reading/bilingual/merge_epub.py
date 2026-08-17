"""Generate a bilingual EPUB (English primary + expandable Chinese panels).

Wraps the alignment core into a full EPUB build: extract the English EPUB,
inject expandable Chinese translation blocks into each mapped chapter, add
CSS, rewrite OPF metadata, and repackage. The English package stays intact
(cover, images, English-only pages, navigation).
"""

from __future__ import annotations

from dataclasses import replace
import html
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, List, Literal, Sequence, Tuple
from urllib.parse import unquote
import xml.etree.ElementTree as ET
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

# Additional rules shared by all export styles. Keeping this separate makes
# reader customization additive and avoids replacing a book's existing CSS.
STYLE_EXTENSION_CSS = """
:root { --dt-bilingual-font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Heiti TC", "Microsoft JhengHei", "Noto Serif CJK TC", serif; }
details.zh-details .zh-content p, details.zh-details .zh-content blockquote, .zh-alternate, .zh-column { font-family: var(--dt-bilingual-font-family); }
.zh-alternate { margin: .35em 0 1.1em; padding: .45em .75em; background: #f8f9fa; border-left: 3px solid #0066cc; border-radius: 4px; line-height: 1.7; color: #1e293b; }
.bilingual-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1em; align-items: start; margin: 0 0 1.1em; break-inside: avoid; }
.bilingual-row > .en-column { line-height: 1.65; }
.bilingual-row > .zh-column { padding: .45em .65em; background: #f8f9fa; border-left: 3px solid #0066cc; border-radius: 4px; line-height: 1.7; color: #1e293b; }
@media (prefers-color-scheme: dark) { .zh-alternate, .bilingual-row > .zh-column { background: #1e293b; border-left-color: #38bdf8; color: #e2e8f0; } }
"""

BilingualExportStyle = Literal["folded", "alternating", "two_column"]


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


def _translation_markup(unit: ZhUnit, style: BilingualExportStyle, label: str) -> str:
    content = (
        (unit.heading_html + "\n" if unit.heading_html else "")
        + f"<{unit.tag}{unit.attrs}>{unit.inner}</{unit.tag}>"
    )
    if style == "folded":
        return _make_details(unit, label)
    if style == "alternating":
        return f'<div class="zh-alternate">{content}</div>\n'
    return f'<div class="zh-column">{content}</div>\n'


def _two_column_row(en_markup: str, zh_markup: Sequence[str]) -> str:
    return (
        '<div class="bilingual-row">\n'
        f'  <div class="en-column">{en_markup}</div>\n'
        f'  <div class="zh-column">{"".join(zh_markup)}</div>\n'
        "</div>\n"
    )


def _render_group(
    group: Group,
    en: Sequence[EnPara],
    zh: Sequence[ZhUnit],
    label: str,
    style: BilingualExportStyle = "folded",
    translation_override: str | None = None,
) -> List[Tuple[int, str]]:
    """Render one aligned group into XHTML markup fragments keyed by EN paragraph index."""
    en_group = en[group.en_start:group.en_end]
    zh_group = zh[group.zh_start:group.zh_end]
    if translation_override is not None and zh_group:
        zh_group = [
            replace(
                zh_group[0],
                heading_html="",
                heading_text="",
                inner="<br/>".join(
                    html.escape(line, quote=False) for line in translation_override.splitlines()
                ),
                text=translation_override,
            )
        ]
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
            if style == "two_column":
                return [
                    (
                        group.en_start,
                        _two_column_row(
                            _make_en(para, inner, index),
                            [_translation_markup(unit, style, label)],
                        ),
                    )
                    for index, (inner, unit) in enumerate(zip(inners, zh_group))
                ]
            return [
                (
                    group.en_start,
                    _make_en(para, inner, index)
                    + "\n"
                    + _translation_markup(unit, style, label),
                )
                for index, (inner, unit) in enumerate(zip(inners, zh_group))
            ]
    if len(en_group) == len(zh_group):
        if style == "two_column":
            return [
                (
                    group.en_start + index,
                    _two_column_row(
                        _make_en(item, item.inner),
                        [_translation_markup(unit, style, label)],
                    ),
                )
                for index, (item, unit) in enumerate(zip(en_group, zh_group))
            ]
        return [
            (
                group.en_start + index,
                _make_en(item, item.inner)
                + "\n"
                + _translation_markup(unit, style, label),
            )
            for index, (item, unit) in enumerate(zip(en_group, zh_group))
        ]
    # Fall back: render all EN paragraphs, attach all ZH details after the last one.
    rendered = [(group.en_start + index, _make_en(item, item.inner)) for index, item in enumerate(en_group)]
    if rendered and zh_group:
        idx, markup = rendered[-1]
        translations = [_translation_markup(unit, style, label) for unit in zh_group]
        rendered[-1] = (
            (idx, _two_column_row(markup, translations))
            if style == "two_column"
            else (idx, markup + "".join(translations))
        )
    return rendered


def _process_chapter(
    en_xml: str,
    zh_xml: str,
    chapter: str,
    overrides: dict[str, List[dict]],
    label: str,
    style: BilingualExportStyle = "folded",
    translation_overrides: Sequence[str | None] | None = None,
) -> Tuple[str, dict[str, Any]]:
    """Inject bilingual blocks into a single chapter's XHTML."""
    en = extract_en_paragraphs(en_xml)
    zh, zh_footnotes = extract_zh_units(zh_xml)
    if not en or not zh:
        return en_xml, {"chapter": chapter, "pairs": 0, "groups": [], "low_conf": []}
    groups = align_groups(en, zh, chapter, overrides)
    by_para: dict[int, str] = {}
    overrides_by_group = list(translation_overrides or [])
    for group_index, group in enumerate(groups):
        override = (
            overrides_by_group[group_index]
            if group_index < len(overrides_by_group)
            else None
        )
        for index, markup in _render_group(group, en, zh, label, style, override):
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


def _css_string(value: str) -> str:
    return "".join(
        char for char in value.strip() if ord(char) >= 32 and char not in "<>&\\"
    ).replace('"', "'")


def _safe_custom_css(value: str) -> str:
    return (
        re.sub(r"</\s*style\s*>", "", value, flags=re.IGNORECASE)
        .replace("\x00", "")
        .replace("]]>", "\\5d \\5d \\3e ")
        .replace("&", "\\26 ")
        .replace("<", "\\3c ")
    )


def validate_custom_css(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Custom CSS contains NUL")
    if re.search(r"(?i)\b@import\b", value):
        raise ValueError("Custom CSS cannot use @import")
    if re.search(r"(?i)url\s*\(\s*['\"]?\s*(?:https?:|//)", value):
        raise ValueError("Custom CSS cannot reference external network URLs")
    return value


def _style_css(font_family: str = "", custom_css: str = "") -> str:
    css = CSS.lstrip() + "\n" + STYLE_EXTENSION_CSS.lstrip()
    if font_family.strip():
        css = css.replace(
            "--dt-bilingual-font-family:",
            f'--dt-bilingual-font-family: "{_css_string(font_family)}",',
            1,
        )
    custom = _safe_custom_css(custom_css).strip()
    if custom:
        css += "\n/* custom reader stylesheet */\n" + custom + "\n"
    return css


def _inject_css(
    work: Path,
    chapter_paths: Sequence[Path],
    *,
    font_family: str = "",
    custom_css: str = "",
    font_path: Path | None = None,
    font_media_type: str = "",
) -> None:
    root = work.resolve()
    css_path = root / "bilingual.css"
    css = _style_css(font_family, validate_custom_css(custom_css))
    font_href = ""
    if font_path is not None and font_path.is_file():
        font_dir = root / "fonts"
        font_dir.mkdir(exist_ok=True)
        embedded_font = font_dir / font_path.name
        shutil.copyfile(font_path, embedded_font)
        font_href = f"fonts/{embedded_font.name}"
        css = (
            f'@font-face {{ font-family: "{_css_string(font_family or "DeepTutor Reader")}"; '
            f'src: url("{font_href}") format("{_font_format(font_media_type)}"); }}\n'
            + css
        )
    css_path.write_text(css, encoding="utf-8")

    xhtml_ns = "http://www.w3.org/1999/xhtml"
    ET.register_namespace("", xhtml_ns)
    for chapter_path in chapter_paths:
        tree = ET.parse(chapter_path)
        head = tree.getroot().find(f"{{{xhtml_ns}}}head")
        if head is None:
            continue
        href = Path(os.path.relpath(css_path, chapter_path.parent)).as_posix()
        link = ET.Element(f"{{{xhtml_ns}}}link")
        link.set("rel", "stylesheet")
        link.set("type", "text/css")
        link.set("href", href)
        head.append(link)
        tree.write(chapter_path, encoding="utf-8", xml_declaration=True)


def _font_format(media_type: str) -> str:
    return {
        "font/woff2": "woff2",
        "font/woff": "woff",
        "font/otf": "opentype",
        "font/ttf": "truetype",
    }.get(media_type, "truetype")


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


def _direct_child(element: ET.Element, local_name: str) -> ET.Element | None:
    for child in element:
        if child.tag.split("}", 1)[-1] == local_name:
            return child
    return None


def _update_opf(
    work: Path,
    *,
    source_lang: str,
    target_lang: str,
    translator: str,
    title_suffix: str,
    font_path: Path | None,
    font_media_type: str,
) -> None:
    opf_path = _find_package_opf(work)
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    tree = ET.parse(opf_path)
    root = tree.getroot()
    metadata = _direct_child(root, "metadata")
    manifest = _direct_child(root, "manifest")
    if metadata is None or manifest is None:
        raise ValueError("Invalid EPUB OPF package")

    title = _direct_child(metadata, "title")
    if title is not None and title_suffix and title_suffix not in (title.text or ""):
        title.text = f"{title.text or ''}{title_suffix}"
    languages = {
        (child.text or "").strip()
        for child in metadata
        if child.tag.split("}", 1)[-1] == "language"
    }
    dc_ns = "http://purl.org/dc/elements/1.1/"
    if source_lang not in languages:
        ET.SubElement(metadata, f"{{{dc_ns}}}language").text = source_lang
    if target_lang not in languages:
        ET.SubElement(metadata, f"{{{dc_ns}}}language").text = target_lang
    if translator and not any(
        child.tag.split("}", 1)[-1] == "contributor" and child.text == translator
        for child in metadata
    ):
        contributor = ET.SubElement(metadata, f"{{{dc_ns}}}contributor")
        contributor.set("id", "deep-tutor-translator")
        contributor.text = translator
        role = ET.SubElement(metadata, "meta")
        role.set("property", "role")
        role.set("refines", "#deep-tutor-translator")
        role.set("scheme", "marc:relators")
        role.text = "trl"

    existing_hrefs = {item.get("href") for item in manifest}
    css_href = Path(os.path.relpath(work / "bilingual.css", opf_path.parent)).as_posix()
    if css_href not in existing_hrefs:
        css_item = ET.SubElement(manifest, "item")
        css_item.set("id", "deep-tutor-bilingual-css")
        css_item.set("href", css_href)
        css_item.set("media-type", "text/css")
    if font_path is not None and font_path.is_file():
        font_href = Path(
            os.path.relpath(work / "fonts" / font_path.name, opf_path.parent)
        ).as_posix()
        if font_href not in existing_hrefs:
            font_item = ET.SubElement(manifest, "item")
            font_item.set("id", "deep-tutor-reader-font")
            font_item.set("href", font_href)
            font_item.set("media-type", font_media_type)

    ET.indent(tree, space="  ")
    tree.write(opf_path, encoding="utf-8", xml_declaration=True)


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
    style: BilingualExportStyle = "folded",
    font_family: str = "",
    custom_css: str = "",
    translation_overrides: dict[str, Sequence[str | None]] | None = None,
    work_dir: Path | None = None,
    font_path: Path | None = None,
    font_media_type: str = "",
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
    group_translations = translation_overrides or {}
    owned_work = work_dir is None
    work_parent = work_dir or Path(tempfile.mkdtemp(
        prefix=f".bilingual-{output.stem}-", dir=output.parent
    ))
    work = Path(work_parent)
    output.parent.mkdir(parents=True, exist_ok=True)

    def extract_safe(archive: zipfile.ZipFile) -> None:
        root = work.resolve()
        for member in archive.infolist():
            destination = (work / member.filename).resolve()
            try:
                destination.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"Unsafe EPUB entry: {member.filename}") from exc
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)

    try:
        with zipfile.ZipFile(english_epub) as archive:
            extract_safe(archive)

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
                    style,
                    group_translations.get(str(chapter)),
                )
                path.write_text(xml, encoding="utf-8")
                processed_paths.append(path)
                stats.append(stat)

        _inject_css(
            work,
            processed_paths,
            font_family=font_family,
            custom_css=custom_css,
            font_path=font_path,
            font_media_type=font_media_type,
        )
        _update_opf(
            work,
            source_lang=source_lang,
            target_lang=target_lang,
            translator=translator,
            title_suffix=title_suffix,
            font_path=font_path,
            font_media_type=font_media_type,
        )

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w") as archive:
                mimetype = work / "mimetype"
                if mimetype.exists():
                    archive.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
                for root, _, names in os.walk(work):
                    for name in names:
                        p = Path(root) / name
                        relative = p.relative_to(work).as_posix()
                        if relative != "mimetype":
                            archive.write(p, relative, compress_type=zipfile.ZIP_DEFLATED)
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
        return stats
    finally:
        if owned_work:
            shutil.rmtree(work, ignore_errors=True)
