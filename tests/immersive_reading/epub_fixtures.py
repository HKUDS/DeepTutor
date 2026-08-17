"""Synthetic EPUB fixtures for immersive-reading tests."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def build_epub(
    *,
    version: str = "2.0",
    title: str = "The Compass Book",
    author: str = "Ada Writer",
    identifier: str = "urn:uuid:compass-book",
    chapters: list[tuple[str, str, str]] | None = None,
    include_ncx: bool = True,
    include_nav: bool = False,
    include_cover: bool = False,
    pre_paginated: bool = False,
    nested_nav: bool = False,
) -> bytes:
    chapters = chapters or [
        (
            "chapter-1.xhtml",
            "Chapter 1: The Observatory",
            "Ada follows the brass compass through the old observatory. ",
        ),
        (
            "chapter-2.xhtml",
            "Chapter 2: The Harbor",
            "At the harbor, Ada maps the compass bearings against the tide. ",
        ),
        (
            "chapter-3.xhtml",
            "Chapter 3: The Library",
            "The library records reveal why the compass points north at dusk. ",
        ),
    ]
    items = []
    spine = []
    if include_cover:
        items.append(
            '<item id="cover-img" href="cover.png" media-type="image/png" properties="cover-image"/>'
        )
        items.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="cover" linear="no"/>')
    if include_ncx:
        items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    if include_nav:
        items.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
    for index, (filename, _title, _text) in enumerate(chapters, start=1):
        items.append(
            f'<item id="chapter-{index}" href="{filename}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="chapter-{index}"/>')

    meta_extra = ""
    if include_cover:
        meta_extra += '<meta name="cover" content="cover-img"/>'
    if pre_paginated:
        meta_extra += '<meta property="rendition:layout">pre-paginated</meta>'

    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    spine_open = '<spine toc="ncx">' if include_ncx else "<spine>"
    package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="{version}" unique-identifier="book-id" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:identifier id="book-id">{identifier}</dc:identifier>
    <dc:language>en</dc:language>
    {meta_extra}
  </metadata>
  <manifest>
    {"".join(items)}
  </manifest>
  {spine_open}
    {"".join(spine)}
  </spine>
</package>"""

    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", package, compress_type=ZIP_DEFLATED)
        if include_ncx:
            archive.writestr("OEBPS/toc.ncx", _ncx_document(identifier, title, chapters, nested_nav), compress_type=ZIP_DEFLATED)
        if include_nav:
            archive.writestr("OEBPS/nav.xhtml", _nav_document(chapters, nested_nav), compress_type=ZIP_DEFLATED)
        if include_cover:
            archive.writestr("OEBPS/cover.png", _PNG_1X1, compress_type=ZIP_DEFLATED)
            archive.writestr(
                "OEBPS/cover.xhtml",
                """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title></head>
<body><img src="cover.png" alt="Cover"/></body></html>""",
                compress_type=ZIP_DEFLATED,
            )
        for filename, chapter_title, sentence in chapters:
            body = sentence * 40
            archive.writestr(
                f"OEBPS/{filename}",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{chapter_title}</title></head>
<body><h1>{chapter_title}</h1><p>{body}</p></body></html>""",
                compress_type=ZIP_DEFLATED,
            )
    return output.getvalue()


def _ncx_document(
    identifier: str,
    title: str,
    chapters: list[tuple[str, str, str]],
    nested_nav: bool,
) -> str:
    if nested_nav:
        children = "\n".join(
            (
                f'<navPoint id="nav-{index}" playOrder="{index + 1}">'
                f"<navLabel><text>{chapter_title}</text></navLabel>"
                f'<content src="{filename}"/></navPoint>'
            )
            for index, (filename, chapter_title, _text) in enumerate(chapters, start=1)
        )
        nav_map = (
            '<navPoint id="nav-part" playOrder="1">'
            "<navLabel><text>Part One</text></navLabel>"
            f'<content src="{chapters[0][0]}"/>'
            f"{children}</navPoint>"
        )
    else:
        nav_map = "\n".join(
            (
                f'<navPoint id="nav-{index}" playOrder="{index}">'
                f"<navLabel><text>{chapter_title}</text></navLabel>"
                f'<content src="{filename}"/></navPoint>'
            )
            for index, (filename, chapter_title, _text) in enumerate(chapters, start=1)
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">
  <head><meta name="dtb:uid" content="{identifier}"/></head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>{nav_map}</navMap>
</ncx>"""


def _nav_document(chapters: list[tuple[str, str, str]], nested_nav: bool) -> str:
    if nested_nav:
        children = "".join(
            f'<li><a href="{filename}">{chapter_title}</a></li>'
            for filename, chapter_title, _text in chapters
        )
        inner = f'<li><a href="{chapters[0][0]}">Part One</a><ol>{children}</ol></li>'
    else:
        inner = "".join(
            f'<li><a href="{filename}">{chapter_title}</a></li>'
            for filename, chapter_title, _text in chapters
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Navigation</title></head>
<body>
<nav epub:type="toc"><ol>{inner}</ol></nav>
</body></html>"""
