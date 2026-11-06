"""ZIP member names written without the UTF-8 flag.

Windows' built-in "Compressed (zipped) folder" stores names in the system ANSI
code page (GBK on Chinese Windows) and leaves the UTF-8 flag clear, so
``zipfile`` reads them as CP437 mojibake. A knowledge-base upload of such an
archive used to save ``第一章 导数.md`` as ``╡┌╥╗╒┬ ╡╝╩².md``.
"""

from __future__ import annotations

from pathlib import Path
import zipfile

from deeptutor.utils.archive_extractor import safe_extract_zip

DOC_EXTS = {".md", ".txt", ".pdf"}


class _UnflaggedName(zipfile.ZipInfo):
    """Stores ``raw_name`` verbatim and never sets the UTF-8 flag."""

    raw_name = b""

    def _encodeFilenameFlags(self):
        return self.raw_name, self.flag_bits & ~0x800


def _unflagged_zip(path: Path, entries: list[tuple[bytes, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for raw_name, data in entries:
            info = _UnflaggedName(raw_name.decode("cp437"))
            info.raw_name = raw_name
            archive.writestr(info, data)
    return path


def test_gbk_names_from_windows_compressed_folder_are_extracted_readably(tmp_path) -> None:
    src = _unflagged_zip(
        tmp_path / "course.zip",
        [
            ("课程/第一章 导数.md".encode("gbk"), b"# derivative"),
            ("课程/讲义.txt".encode("gbk"), b"notes"),
        ],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert sorted(p.name for p in result.extracted) == ["第一章 导数.md", "讲义.txt"]
    assert (out / "第一章 导数.md").read_bytes() == b"# derivative"


def test_member_names_are_decoded_utf8_first_then_gbk(tmp_path) -> None:
    from deeptutor.utils.zip_names import zip_member_name

    src = _unflagged_zip(
        tmp_path / "mixed.zip",
        [
            ("讲义.md".encode("utf-8"), b"utf-8 bytes, no flag"),
            ("讲义.md".encode("gbk"), b"gbk bytes, no flag"),
            (b"plain.md", b"ascii"),
        ],
    )
    with zipfile.ZipFile(src) as archive:
        names = [zip_member_name(info) for info in archive.infolist()]

    assert names == ["讲义.md", "讲义.md", "plain.md"]


def test_flagged_utf8_names_are_left_alone(tmp_path) -> None:
    from deeptutor.utils.zip_names import zip_member_name

    src = tmp_path / "modern.zip"
    with zipfile.ZipFile(src, "w") as archive:
        archive.writestr("第一章.md", b"x")
    with zipfile.ZipFile(src) as archive:
        (info,) = archive.infolist()

    assert info.flag_bits & 0x800
    assert zip_member_name(info) == "第一章.md"
