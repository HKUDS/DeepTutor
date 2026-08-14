"""Extract OPF/spine/nav hrefs and map them onto reading sections."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import html
import logging
from pathlib import Path, PurePosixPath
import re
from typing import Iterable
from urllib.parse import unquote
from xml.etree import ElementTree as ET
import zipfile

from deeptutor.immersive_reading.models import ReadingSection

logger = logging.getLogger(__name__)


def _strip_tags(markup: str) -> str:
    """Strip HTML tags and decode entities."""
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()

_SPLIT_SUFFIX_RE = re.compile(r"\s+[–—-]\s+\d+$")
_HREF_ATTR_RE = re.compile(r"""\b(?:href|src)\s*=\s*['"]([^'"]+)['"]""", re.I)
_PRE_PAGINATED_RE = re.compile(r"pre-paginated", re.I)


@dataclass(frozen=True)
class EpubNavItem:
    title: str
    href: str


@dataclass(frozen=True)
class EpubStructure:
    title: str = ""
    author: str = ""
    opf_dir: str = ""
    spine_hrefs: list[str] = field(default_factory=list)
    nav_items: list[EpubNavItem] = field(default_factory=list)
    cover_href: str = ""
    is_pre_paginated: bool = False


def normalize_epub_href(href: str, *, base_dir: str = "", opf_dir: str = "") -> str:
    """Return an OPF-relative href with ``.`` / ``..`` collapsed."""
    raw = unquote((href or "").strip()).replace("\\", "/")
    if not raw or raw.startswith(("http://", "https://", "data:", "mailto:")):
        return ""
    path_part, fragment = (raw.split("#", 1) + [""])[:2]
    path_part = path_part.split("?", 1)[0]
    abs_path = _posix_norm(base_dir, path_part)
    if opf_dir:
        rel = _rel_to(abs_path, opf_dir)
    else:
        rel = abs_path
    rel = rel.lstrip("/")
    if fragment:
        return f"{rel}#{fragment}"
    return rel


def href_path(href: str) -> str:
    return normalize_epub_href(href).split("#", 1)[0]


def hrefs_match(left: str, right: str) -> bool:
    a = href_path(left)
    b = href_path(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if a.endswith("/" + b) or b.endswith("/" + a):
        return True
    return Path(a).name == Path(b).name and bool(Path(a).name)


def parse_epub_structure(source: Path | bytes) -> EpubStructure:
    opener: Path | BytesIO
    if isinstance(source, (bytes, bytearray)):
        opener = BytesIO(source)
    else:
        opener = source
    with zipfile.ZipFile(opener) as archive:
        names = archive.namelist()
        opf_path = _find_opf_path(archive, names)
        if not opf_path:
            raise ValueError("No OPF found in EPUB")
        opf_dir = str(PurePosixPath(opf_path).parent)
        if opf_dir == ".":
            opf_dir = ""
        opf_text = _read_zip_text(archive, opf_path)
        root = _parse_xml(opf_text)
        title, author = _package_identity(root, opf_text)
        manifest = _package_manifest(root, opf_dir)
        spine_ids = _package_spine_ids(root, opf_text)
        spine_hrefs = [
            manifest[item_id][0]
            for item_id in spine_ids
            if item_id in manifest and _is_document_href(*manifest[item_id])
        ]
        cover_href = _package_cover_href(root, manifest, opf_text)
        is_pre_paginated = _package_is_pre_paginated(root, opf_text)
        nav_items = _collect_nav_items(archive, names, root, manifest, opf_dir)
        if not nav_items:
            nav_items = [
                EpubNavItem(title=PurePosixPath(href).stem, href=href) for href in spine_hrefs
            ]
        return EpubStructure(
            title=title,
            author=author,
            opf_dir=opf_dir,
            spine_hrefs=spine_hrefs,
            nav_items=nav_items,
            cover_href=cover_href,
            is_pre_paginated=is_pre_paginated,
        )


def apply_source_hrefs(
    sections: list[ReadingSection],
    source: Path | bytes,
    *,
    reading_mode: str = "chapters",
    overwrite: bool = False,
) -> bool:
    """Fill empty ``source_href`` values. Returns True when any section changed."""
    if not sections:
        return False
    try:
        structure = parse_epub_structure(source)
    except Exception:
        logger.exception("Unable to parse EPUB structure for section href mapping")
        return False

    page_to_spine = (
        _page_index_to_spine_href(source, structure)
        if reading_mode == "chapters" and isinstance(source, Path)
        else []
    )
    assigned = [_existing_href(section, overwrite) for section in sections]
    nav_by_title = _nav_title_map(structure.nav_items)

    for index, section in enumerate(sections):
        if assigned[index]:
            continue
        nav_href = nav_by_title.get(_title_key(section.title), "")
        if nav_href:
            assigned[index] = nav_href

    for index, section in enumerate(sections):
        if assigned[index]:
            continue
        parent_href = _parent_assigned_href(sections, assigned, section)
        if parent_href and _looks_like_split(section.title):
            assigned[index] = parent_href

    for index, section in enumerate(sections):
        if assigned[index] or reading_mode != "chapters":
            continue
        page_index = max(0, int(section.source_start or 1) - 1)
        if 0 <= page_index < len(page_to_spine) and page_to_spine[page_index]:
            assigned[index] = page_to_spine[page_index]

    unused_spine = _unused_spine(structure.spine_hrefs, assigned)
    for index, section in enumerate(sections):
        if assigned[index]:
            continue
        parent_href = _parent_assigned_href(sections, assigned, section)
        if parent_href:
            assigned[index] = parent_href
            continue
        if unused_spine:
            assigned[index] = unused_spine.pop(0)

    for index, section in enumerate(sections):
        if assigned[index]:
            continue
        parent_href = _parent_assigned_href(sections, assigned, section)
        if parent_href:
            assigned[index] = parent_href

    changed = False
    for section, href in zip(sections, assigned, strict=False):
        if href and (overwrite or not section.source_href):
            if section.source_href != href:
                section.source_href = href
                changed = True
    return changed


def resolve_section_titles(
    sections: list[ReadingSection],
    source: Path | bytes,
) -> bool:
    """Replace filename-derived titles with human-readable EPUB chapter titles.

    Calibre-split and similar EPUBs expose spine file stems (e.g.
    ``index_split_004``) as section titles because the reader built titles from
    the spine. This looks up the real label from the EPUB's nav/NCX and, for any
    href still missing a label, from the first heading inside the spine
    document. Titles that already carry a meaningful label are left untouched.
    Returns ``True`` when any title changed.
    """
    if not sections:
        return False
    try:
        structure = parse_epub_structure(source)
    except Exception:
        logger.exception("Unable to parse EPUB structure for title resolution")
        return False

    href_to_title = _href_title_map(structure.nav_items)
    # Fill gaps the nav/NCX did not cover by reading each spine document.
    missing = {
        href_path(section.source_href)
        for section in sections
        if section.source_href and href_path(section.source_href) not in href_to_title
    }
    if missing:
        href_to_title.update(_read_spine_heading_titles(source, structure, missing))
    if not href_to_title:
        return False

    changed = False
    for section in sections:
        key = href_path(section.source_href)
        if not key:
            continue
        real_title = href_to_title.get(key)
        if not real_title:
            continue
        base, suffix = _split_title_suffix(section.title)
        if not _looks_like_stem_title(base, key):
            continue
        new_title = f"{real_title}{suffix}"
        if new_title and new_title != section.title:
            section.title = new_title
            changed = True
    return changed


def section_needs_title(section: ReadingSection) -> bool:
    """True when a section's title is a bare file stem that should be resolved."""
    key = href_path(section.source_href)
    if not key:
        return False
    base, _suffix = _split_title_suffix(section.title)
    return _looks_like_stem_title(base, key)


def resolve_section_for_href(
    sections: Iterable[ReadingSection],
    href: str,
    *,
    preferred_section_id: str = "",
) -> ReadingSection | None:
    matches = [section for section in sections if hrefs_match(section.source_href, href)]
    if not matches:
        return None
    if preferred_section_id:
        for section in matches:
            if section.id == preferred_section_id:
                return section
    for section in matches:
        if section.checkpoint_kind != "none":
            return section
    return matches[0]


def _existing_href(section: ReadingSection, overwrite: bool) -> str:
    if overwrite:
        return ""
    return section.source_href or ""


def _parent_assigned_href(
    sections: list[ReadingSection], assigned: list[str], section: ReadingSection
) -> str:
    if not section.parent_id:
        return ""
    for index, candidate in enumerate(sections):
        if candidate.id == section.parent_id:
            return assigned[index]
    return ""


def _looks_like_split(title: str) -> bool:
    return bool(_SPLIT_SUFFIX_RE.search(title or ""))


def _title_key(title: str) -> str:
    cleaned = _SPLIT_SUFFIX_RE.sub("", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().casefold()
    return cleaned


def _nav_title_map(items: list[EpubNavItem]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in items:
        key = _title_key(item.title)
        if key and key not in mapping:
            mapping[key] = item.href
    return mapping


def _unused_spine(spine_hrefs: list[str], assigned: list[str]) -> list[str]:
    used = {href_path(href) for href in assigned if href}
    unused: list[str] = []
    seen: set[str] = set()
    for href in spine_hrefs:
        key = href_path(href)
        if not key or key in used or key in seen:
            continue
        unused.append(href)
        seen.add(key)
    return unused


def _page_index_to_spine_href(source: Path, structure: EpubStructure) -> list[str]:
    try:
        import pymupdf as fitz
    except ImportError:
        return []
    try:
        document = fitz.open(source)
    except Exception:
        return []
    try:
        mapping: list[str] = []
        chapter_count = int(getattr(document, "chapter_count", 0) or 0)
        for chapter_index in range(chapter_count):
            href = (
                structure.spine_hrefs[chapter_index]
                if chapter_index < len(structure.spine_hrefs)
                else ""
            )
            try:
                page_count = int(document.chapter_page_count(chapter_index))
            except Exception:
                page_count = 1
            mapping.extend([href] * max(1, page_count))
        return mapping
    finally:
        document.close()


def _find_opf_path(archive: zipfile.ZipFile, names: list[str]) -> str:
    container = "META-INF/container.xml"
    if container in names:
        text = _read_zip_text(archive, container)
        match = re.search(r'full-path\s*=\s*[\'"]([^\'"]+)[\'"]', text, re.I)
        if match:
            return unquote(match.group(1))
    for name in names:
        if name.lower().endswith(".opf"):
            return name
    return ""


def _package_identity(root: ET.Element | None, opf_text: str) -> tuple[str, str]:
    title = ""
    author = ""
    if root is not None:
        for el in root.iter():
            local = _local(el.tag)
            if local == "title" and not title:
                title = "".join(el.itertext()).strip()
            elif local == "creator" and not author:
                author = "".join(el.itertext()).strip()
    if not title:
        match = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf_text, re.I | re.S)
        if match:
            title = _strip_tags(match.group(1))
    if not author:
        match = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", opf_text, re.I | re.S)
        if match:
            author = _strip_tags(match.group(1))
    return title, author


def _package_manifest(root: ET.Element | None, opf_dir: str) -> dict[str, tuple[str, str, str]]:
    manifest: dict[str, tuple[str, str, str]] = {}
    if root is None:
        return manifest
    for el in root.iter():
        if _local(el.tag) != "item":
            continue
        item_id = el.attrib.get("id") or ""
        href = normalize_epub_href(el.attrib.get("href") or "", opf_dir=opf_dir)
        if not item_id or not href:
            continue
        media = el.attrib.get("media-type") or el.attrib.get("media-type".replace("-", "")) or ""
        properties = el.attrib.get("properties") or ""
        manifest[item_id] = (href, media, properties)
    return manifest


def _package_spine_ids(root: ET.Element | None, opf_text: str) -> list[str]:
    ids: list[str] = []
    if root is not None:
        for el in root.iter():
            if _local(el.tag) != "itemref":
                continue
            idref = el.attrib.get("idref") or ""
            if idref:
                ids.append(idref)
    if ids:
        return ids
    for match in re.finditer(r"<itemref\b([^>]*)/?>", opf_text, re.I):
        idref = re.search(r"""\bidref\s*=\s*['"]([^'"]+)['"]""", match.group(1), re.I)
        if idref:
            ids.append(idref.group(1))
    return ids


def _package_cover_href(
    root: ET.Element | None,
    manifest: dict[str, tuple[str, str, str]],
    opf_text: str,
) -> str:
    for item_id, (href, _media, properties) in manifest.items():
        tokens = set(properties.split())
        if "cover-image" in tokens or item_id.lower() in {"cover", "cover-image", "coverimage"}:
            return href
    cover_id = ""
    if root is not None:
        for el in root.iter():
            if _local(el.tag) != "meta":
                continue
            name = (el.attrib.get("name") or "").lower()
            if name == "cover":
                cover_id = el.attrib.get("content") or ""
                break
    if not cover_id:
        match = re.search(
            r"""<meta\b[^>]*name=['"]cover['"][^>]*content=['"]([^'"]+)['"]""",
            opf_text,
            re.I,
        )
        if match:
            cover_id = match.group(1)
    if cover_id and cover_id in manifest:
        return manifest[cover_id][0]
    return ""


def _package_is_pre_paginated(root: ET.Element | None, opf_text: str) -> bool:
    if root is not None:
        for el in root.iter():
            if _local(el.tag) != "meta":
                continue
            prop = el.attrib.get("property") or ""
            name = el.attrib.get("name") or ""
            content = (el.attrib.get("content") or "".join(el.itertext())).strip()
            if "rendition:layout" in {prop, name} and _PRE_PAGINATED_RE.search(content):
                return True
    return bool(_PRE_PAGINATED_RE.search(opf_text))


def _collect_nav_items(
    archive: zipfile.ZipFile,
    names: list[str],
    root: ET.Element | None,
    manifest: dict[str, tuple[str, str, str]],
    opf_dir: str,
) -> list[EpubNavItem]:
    items: list[EpubNavItem] = []
    nav_href = ""
    for href, _media, properties in manifest.values():
        if "nav" in properties.split():
            nav_href = href
            break
    if nav_href:
        zip_name = _zip_name(opf_dir, href_path(nav_href), names)
        if zip_name:
            items.extend(
                _parse_nav_xhtml(
                    _read_zip_text(archive, zip_name),
                    base_dir=str(PurePosixPath(zip_name).parent),
                    opf_dir=opf_dir,
                )
            )
    if items:
        return items
    ncx_href = ""
    for href, media, _properties in manifest.values():
        if "ncx" in media or href.lower().endswith(".ncx"):
            ncx_href = href
            break
    if not ncx_href:
        for name in names:
            if name.lower().endswith(".ncx"):
                ncx_href = _rel_to(name, opf_dir)
                break
    if ncx_href:
        zip_name = _zip_name(opf_dir, href_path(ncx_href), names)
        if zip_name:
            items.extend(
                _parse_ncx(
                    _read_zip_text(archive, zip_name),
                    base_dir=str(PurePosixPath(zip_name).parent),
                    opf_dir=opf_dir,
                )
            )
    return items


def _parse_nav_xhtml(text: str, *, base_dir: str, opf_dir: str) -> list[EpubNavItem]:
    root = _parse_xml(text)
    items: list[EpubNavItem] = []
    if root is None:
        for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", text, re.I | re.S):
            href_match = re.search(r"""\bhref\s*=\s*['"]([^'"]+)['"]""", match.group(1), re.I)
            title = _strip_tags(match.group(2))
            if not href_match or not title:
                continue
            href = normalize_epub_href(href_match.group(1), base_dir=base_dir, opf_dir=opf_dir)
            if href:
                items.append(EpubNavItem(title=title, href=href))
        return items

    toc_nav: ET.Element | None = None
    for el in root.iter():
        if _local(el.tag) != "nav":
            continue
        nav_type = " ".join(
            [
                el.attrib.get("type") or "",
                el.attrib.get("{http://www.idpf.org/2007/ops}type") or "",
            ]
        )
        if "toc" in nav_type.split() or toc_nav is None:
            toc_nav = el
            if "toc" in nav_type.split():
                break
    scope = toc_nav if toc_nav is not None else root
    for el in scope.iter():
        if _local(el.tag) != "a":
            continue
        title = "".join(el.itertext()).strip()
        href = normalize_epub_href(el.attrib.get("href") or "", base_dir=base_dir, opf_dir=opf_dir)
        if title and href:
            items.append(EpubNavItem(title=title, href=href))
    return items


def _parse_ncx(text: str, *, base_dir: str, opf_dir: str) -> list[EpubNavItem]:
    root = _parse_xml(text)
    items: list[EpubNavItem] = []
    if root is None:
        for block in re.finditer(r"<navPoint\b.*?</navPoint>", text, re.I | re.S):
            label = re.search(r"<text[^>]*>(.*?)</text>", block.group(0), re.I | re.S)
            src = re.search(r"""<content\b[^>]*src\s*=\s*['"]([^'"]+)['"]""", block.group(0), re.I)
            if not label or not src:
                continue
            title = _strip_tags(label.group(1))
            href = normalize_epub_href(src.group(1), base_dir=base_dir, opf_dir=opf_dir)
            if title and href:
                items.append(EpubNavItem(title=title, href=href))
        return items

    def walk(node: ET.Element) -> None:
        for child in list(node):
            if _local(child.tag) != "navPoint":
                walk(child)
                continue
            title = ""
            href = ""
            for grandchild in child.iter():
                local = _local(grandchild.tag)
                if local == "text" and not title:
                    title = "".join(grandchild.itertext()).strip()
                elif local == "content" and not href:
                    href = normalize_epub_href(
                        grandchild.attrib.get("src") or "",
                        base_dir=base_dir,
                        opf_dir=opf_dir,
                    )
            if title and href:
                items.append(EpubNavItem(title=title, href=href))
            walk(child)

    walk(root)
    return items


def _is_document_href(href: str, media: str, _properties: str = "") -> bool:
    path = href_path(href).lower()
    media_l = (media or "").lower()
    if "xhtml" in media_l or "html" in media_l or "dtbook" in media_l:
        return True
    return path.endswith((".xhtml", ".html", ".htm", ".xml"))


def _zip_name(opf_dir: str, href: str, names: list[str]) -> str:
    candidate = _posix_norm(opf_dir, href)
    lookup = {name: name for name in names}
    if candidate in lookup:
        return candidate
    lowered = {name.lower(): name for name in names}
    if candidate.lower() in lowered:
        return lowered[candidate.lower()]
    basename = Path(href).name.lower()
    for name in names:
        if Path(name).name.lower() == basename:
            return name
    return ""


def _read_zip_text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8", errors="replace")


def _parse_xml(text: str) -> ET.Element | None:
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        try:
            return ET.fromstring(re.sub(r"&(?!#?\w+;)", "&amp;", text))
        except ET.ParseError:
            return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _posix_norm(*parts: str) -> str:
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        for token in str(part).replace("\\", "/").split("/"):
            if not token or token == ".":
                continue
            if token == "..":
                if tokens:
                    tokens.pop()
                continue
            tokens.append(token)
    return "/".join(tokens)


def _rel_to(path: str, base: str) -> str:
    path_parts = [part for part in _posix_norm(path).split("/") if part]
    base_parts = [part for part in _posix_norm(base).split("/") if part]
    if base_parts and path_parts[: len(base_parts)] == base_parts:
        remainder = path_parts[len(base_parts) :]
        return "/".join(remainder) if remainder else path_parts[-1]
    return "/".join(path_parts)


def _href_title_map(items: list[EpubNavItem]) -> dict[str, str]:
    """Map ``href_path -> title`` from nav items, skipping spine-stem fallbacks.

    ``parse_epub_structure`` synthesizes stem labels when no real nav/NCX
    exists, so those are excluded (they carry no useful information).
    """
    mapping: dict[str, str] = {}
    for item in items:
        key = href_path(item.href)
        title = (item.title or "").strip()
        if not key or not title:
            continue
        if title.casefold() == PurePosixPath(key).stem.casefold():
            continue
        mapping.setdefault(key, title)
    return mapping


def _read_spine_heading_titles(
    source: Path | bytes,
    structure: EpubStructure,
    needed: set[str],
) -> dict[str, str]:
    """Read spine documents and extract a heading title for each needed href."""
    titles: dict[str, str] = {}
    opener: Path | BytesIO = BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    try:
        with zipfile.ZipFile(opener) as archive:
            names = archive.namelist()
            for href in structure.spine_hrefs:
                key = href_path(href)
                if not key or key in titles or key not in needed:
                    continue
                zip_name = _zip_name(structure.opf_dir, href, names)
                if not zip_name:
                    continue
                heading = _extract_html_heading(_read_zip_text(archive, zip_name))
                if not heading:
                    continue
                stem = PurePosixPath(key).stem.casefold()
                if heading.casefold() == stem:
                    continue
                if structure.title and heading.casefold() == structure.title.casefold():
                    continue
                titles[key] = heading
    except Exception:
        logger.exception("Unable to read EPUB spine documents for heading titles")
    return titles


def _extract_html_heading(text: str) -> str:
    """Return the first h1/h2/h3 heading text, falling back to the ``<title>`` tag."""
    for tag in ("h1", "h2", "h3"):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", text, re.I | re.S)
        if match:
            cleaned = _strip_tags(match.group(1))
            if cleaned:
                return cleaned
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if title_match:
        return _strip_tags(title_match.group(1))
    return ""


def _split_title_suffix(title: str) -> tuple[str, str]:
    """Split a chunk-style ``title – N`` into ``(base, suffix)``."""
    cleaned = (title or "").strip()
    match = _SPLIT_SUFFIX_RE.search(cleaned)
    if match:
        return cleaned[: match.start()].strip(), cleaned[match.start():]
    return cleaned, ""


def _looks_like_stem_title(base: str, key: str) -> bool:
    """True when *base* is empty or equals the file stem of *key*."""
    if not base:
        return True
    return base.casefold() == PurePosixPath(key).stem.casefold()


__all__ = [
    "EpubNavItem",
    "EpubStructure",
    "apply_source_hrefs",
    "href_path",
    "hrefs_match",
    "normalize_epub_href",
    "parse_epub_structure",
    "resolve_section_titles",
    "resolve_section_for_href",
    "section_needs_title",
]
