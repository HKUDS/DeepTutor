"""Minimal EPUB fixtures for bilingual tests."""

from pathlib import Path
import zipfile


def _container_xml(opf_path: str = "content.opf") -> str:
    return f'''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf_path}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def _make_opf(title: str, items: list[tuple[str, str, str]], spine: list[str]) -> str:
    manifest = "\n".join(
        f'    <item id="{iid}" href="{href}" media-type="application/xhtml+xml"/>'
        for iid, href, _ in items
    )
    spine_xml = "\n".join(f'    <itemref idref="{sid}"/>' for sid in spine)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">test-{title}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
{manifest}
  </manifest>
  <spine>
{spine_xml}
  </spine>
</package>'''


def make_chapter_xhtml(title: str, paragraphs: list[str]) -> str:
    paras = "\n".join(f'<p id="p{i}">{p}</p>' for i, p in enumerate(paragraphs, 1))
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body>
<h2>{title}</h2>
{paras}
</body>
</html>'''


def make_minimal_epub(path: Path, title: str, chapters: list[tuple[str, list[str]]]) -> None:
    """Build a minimal valid EPUB.

    Args:
        path: output .epub path.
        title: book title.
        chapters: list of (chapter_title, [paragraph_texts]).
    """
    items = [(f"ch{i}", f"chapter{i}.xhtml", "application/xhtml+xml") for i in range(len(chapters))]
    spine = [f"ch{i}" for i in range(len(chapters))]
    opf = _make_opf(title, items, spine)

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _container_xml())
        zf.writestr("content.opf", opf)
        for i, (ch_title, paras) in enumerate(chapters):
            zf.writestr(f"chapter{i}.xhtml", make_chapter_xhtml(ch_title, paras))
