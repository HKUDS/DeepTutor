"""Resolve missing Chinese fonts in a temporary PowerPoint rendering copy.

This module also runs as a standalone helper inside the workspace sandbox.
Keep it independent of other DeepTutor modules.
"""

from __future__ import annotations

from copy import copy
from html import escape
import os
from pathlib import Path
import shutil
import subprocess
import sys
from xml.parsers.expat import ExpatError
from zipfile import BadZipFile, ZipFile

from defusedxml import minidom
from defusedxml.common import DefusedXmlException

_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
PPTX_SUFFIXES = frozenset({".pptx", ".pptm"})
_MAX_PACKAGE_BYTES = 128 * 1024 * 1024
_MAX_XML_BYTES = 8 * 1024 * 1024
_MAX_PARTS = 4096
_MACOS_FONT_ASSETS = Path("/System/Library/AssetsV2")

_SIMPLIFIED_SANS = (
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "微软雅黑",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "PingFang SC",
    "Hiragino Sans GB",
    "Heiti SC",
    "SimHei",
    "黑体",
    "WenQuanYi Zen Hei",
)
_SIMPLIFIED_SERIF = (
    "SimSun",
    "宋体",
    "NSimSun",
    "新宋体",
    "Songti SC",
    "Noto Serif CJK SC",
    "Noto Serif SC",
)
_TRADITIONAL_SANS = (
    "Microsoft JhengHei",
    "Microsoft JhengHei UI",
    "微軟正黑體",
    "Noto Sans CJK TC",
    "Noto Sans TC",
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
)
_TRADITIONAL_SERIF = (
    "PMingLiU",
    "新細明體",
    "MingLiU",
    "細明體",
    "Songti TC",
    "Noto Serif CJK TC",
    "Noto Serif TC",
)


def _installed_families() -> set[str]:
    """Read family names from the same system where the converter runs."""
    if sys.platform == "darwin":
        command = [
            "/usr/bin/osascript",
            "-l",
            "JavaScript",
            "-e",
            'ObjC.import("AppKit"); ObjC.deepUnwrap($.NSFontManager.sharedFontManager'
            '.availableFontFamilies).join("\\n")',
        ]
    elif sys.platform == "win32":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            "Add-Type -AssemblyName System.Drawing; "
            "(New-Object System.Drawing.Text.InstalledFontCollection).Families "
            "| Select-Object -ExpandProperty Name",
        ]
    else:
        command = ["fc-list", "-f", "%{family}\\n"]

    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    output = result.stdout.decode("utf-8-sig", errors="replace")
    return {name.strip().casefold() for line in output.splitlines() for name in line.split(",")}


def chinese_font_substitutions() -> dict[str, str]:
    """Map absent Chinese typefaces to available fonts, preferring the same style and region."""
    installed = _installed_families()
    substitutions = {}
    for requested, candidates in (
        (_SIMPLIFIED_SANS, _SIMPLIFIED_SANS),
        (_SIMPLIFIED_SERIF, _SIMPLIFIED_SERIF + _SIMPLIFIED_SANS),
        (_TRADITIONAL_SANS, _TRADITIONAL_SANS + _SIMPLIFIED_SANS),
        (_TRADITIONAL_SERIF, _TRADITIONAL_SERIF + _TRADITIONAL_SANS + _SIMPLIFIED_SANS),
    ):
        fallback = next((name for name in candidates if name.casefold() in installed), None)
        if fallback:
            missing = (name.casefold() for name in requested if name.casefold() not in installed)
            substitutions.update(dict.fromkeys(missing, fallback))
    return substitutions


def pptx_render_environment(work_directory: Path) -> dict[str, str] | None:
    """Give macOS headless converters a Fontconfig view of the system fonts."""
    if sys.platform != "darwin" or os.environ.get("FONTCONFIG_FILE"):
        return None

    font_directories = [
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path.home() / "Library" / "Fonts",
    ]
    # Modern macOS can install PingFang as a system font asset outside Library/Fonts.
    pingfang_assets = _MACOS_FONT_ASSETS.glob(
        "com_apple_MobileAsset_Font*/*.asset/AssetData/PingFang.ttc"
    )
    font_directories.extend(path.parent for path in sorted(pingfang_assets))
    directories = "".join(f"<dir>{escape(str(path))}</dir>" for path in font_directories)
    cache_directory = escape(str(work_directory / "fontconfig-cache"))
    config = work_directory / "fonts.conf"
    config.write_text(
        f"<fontconfig>{directories}<cachedir>{cache_directory}</cachedir></fontconfig>\n",
        encoding="utf-8",
    )
    return {**os.environ, "FONTCONFIG_FILE": str(config), "FONTCONFIG_PATH": str(work_directory)}


def _embedded_fonts(package: ZipFile) -> set[str]:
    try:
        part = package.getinfo("ppt/presentation.xml")
    except KeyError:
        return set()
    if part.file_size > _MAX_XML_BYTES:
        raise ValueError("Presentation metadata is too large to inspect")
    with minidom.parseString(package.read(part), forbid_dtd=True) as doc:
        return {
            font.getAttribute("typeface").strip().casefold()
            for font in doc.getElementsByTagNameNS(_PRESENTATION_NS, "font")
            if font.parentNode.localName == "embeddedFont"
        }


def _replace_chinese_fonts(xml: bytes, substitutions: dict[str, str]) -> bytes | None:
    # DOM serialization keeps the OOXML prefixes referenced by mc:Ignorable.
    with minidom.parseString(xml, forbid_dtd=True) as doc:
        changed = False
        for tag in ("ea", "font"):
            for font in doc.getElementsByTagNameNS(_DRAWING_NS, tag):
                if tag == "font" and font.getAttribute("script") not in {"Hans", "Hant"}:
                    continue
                replacement = substitutions.get(font.getAttribute("typeface").strip().casefold())
                if replacement:
                    font.setAttribute("typeface", replacement)
                    changed = True
        return doc.toxml(encoding="utf-8") if changed else None


def pptx_for_rendering(
    source: Path, destination: Path, *, substitutions: dict[str, str] | None = None
) -> Path:
    """Return a disposable copy with resolved fonts, or the original when no edits apply.

    Use a fresh destination in a caller-owned temporary directory. Only the
    renderer reads this copy. The generated or uploaded PPTX stays editable.
    """
    if source.suffix.lower() not in PPTX_SUFFIXES:
        return source
    if substitutions is None:
        substitutions = chinese_font_substitutions()
    if not substitutions:
        return source

    try:
        with ZipFile(source) as package:
            parts = package.infolist()
            if len(parts) > _MAX_PARTS:
                return source
            if sum(part.file_size for part in parts) > _MAX_PACKAGE_BYTES:
                return source
            if len({part.filename for part in parts}) != len(parts):
                return source
            embedded = _embedded_fonts(package)
            substitutions = {
                name: font for name, font in substitutions.items() if name not in embedded
            }
            if not substitutions:
                return source

            modified = {}
            for part in parts:
                name = part.filename
                if not name.startswith("ppt/") or not name.endswith(".xml"):
                    continue
                if part.file_size > _MAX_XML_BYTES:
                    return source
                xml = _replace_chinese_fonts(package.read(part), substitutions)
                if xml is not None:
                    modified[name] = xml
            if not modified:
                return source

            with ZipFile(destination, "x") as render_package:
                for part in parts:
                    xml = modified.get(part.filename)
                    if xml is not None:
                        render_package.writestr(copy(part), xml)
                    else:
                        with (
                            package.open(part) as original,
                            render_package.open(copy(part), "w") as target,
                        ):
                            shutil.copyfileobj(original, target)
    except (
        BadZipFile,
        DefusedXmlException,
        ExpatError,
        NotImplementedError,
        RuntimeError,
        ValueError,
    ):
        # Let the converter handle packages this optional rewrite cannot parse.
        return source
    return destination
