"""Wiring tests for safe ``.zip`` upload handling in the knowledge router.

The deep security guards live in ``tests/utils/test_archive_extractor.py``;
these check that ``_save_uploaded_files`` routes ``.zip`` uploads through the
safe extractor, registers only supported members, and never persists the
archive itself.
"""

from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException, UploadFile

from deeptutor.api.routers.knowledge import UploadImportReport, _save_uploaded_files
from deeptutor.utils.document_validator import DocumentValidator

ALLOWED = {".txt", ".md", ".pdf", ".zip"}


@pytest.fixture(autouse=True)
def _disable_pocketbase(monkeypatch):
    monkeypatch.setattr("deeptutor.services.pocketbase_client.is_pocketbase_enabled", lambda: False)


def _zip_upload(filename: str, entries: list[tuple[str, bytes]]) -> UploadFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    buf.seek(0)
    return UploadFile(filename=filename, file=buf)


def test_zip_upload_extracts_only_supported_members(tmp_path: Path) -> None:
    upload = _zip_upload(
        "bundle.zip",
        [
            ("notes.txt", b"hello"),
            ("paper.md", b"# title"),
            ("malware.exe", b"x"),  # disallowed -> skipped
            ("inner.zip", b"PK\x03\x04"),  # nested archive -> skipped
        ],
    )
    raw = tmp_path / "raw"
    raw.mkdir()

    names, paths = _save_uploaded_files([upload], raw, allowed_extensions=ALLOWED)

    assert sorted(names) == ["notes.txt", "paper.md"]
    assert (raw / "notes.txt").read_bytes() == b"hello"
    # The archive itself is never persisted or registered.
    assert not (raw / "bundle.zip").exists()
    assert all(not p.endswith(".zip") for p in paths)


def test_zip_upload_with_zip_slip_member_stays_in_target(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("../../escape.txt"), b"x")
        zf.writestr(zipfile.ZipInfo("/abs/rooted.txt"), b"z")
        zf.writestr("safe.txt", b"y")
    buf.seek(0)
    upload = UploadFile(filename="evil.zip", file=buf)
    raw = tmp_path / "raw"
    raw.mkdir()
    report = UploadImportReport()

    names, _ = _save_uploaded_files([upload], raw, allowed_extensions=ALLOWED, import_report=report)

    assert sorted(names) == ["abs/rooted.txt", "safe.txt"]
    assert not list(tmp_path.rglob("escape.txt"))  # refused, did not escape
    assert report.rejected == [{"file": "evil.zip/../../escape.txt", "reason": "unsafe path"}]


def test_invalid_zip_is_rejected(tmp_path: Path) -> None:
    upload = UploadFile(filename="broken.zip", file=io.BytesIO(b"not a zip"))
    raw = tmp_path / "raw"
    raw.mkdir()

    with pytest.raises(HTTPException) as exc_info:
        _save_uploaded_files([upload], raw, allowed_extensions=ALLOWED)
    assert exc_info.value.status_code == 400


def test_zip_with_no_supported_members_is_rejected(tmp_path: Path) -> None:
    upload = _zip_upload("only-junk.zip", [("a.exe", b"x"), ("b.sh", b"y")])
    raw = tmp_path / "raw"
    raw.mkdir()

    with pytest.raises(HTTPException) as exc_info:
        _save_uploaded_files([upload], raw, allowed_extensions=ALLOWED)
    assert exc_info.value.status_code == 400


def test_zip_keeps_member_folders_like_a_folder_upload(tmp_path: Path) -> None:
    upload = _zip_upload(
        "course.zip",
        [
            ("Week1/Slides.pdf", b"w1 slides"),
            ("Week1/Uebung.pdf", b"w1 exercise"),
            ("Week2/Slides.pdf", b"w2 slides"),
            ("Week2\\Loesung.pdf", b"w2 solution"),  # Windows-made archive
        ],
    )
    raw = tmp_path / "raw"
    raw.mkdir()

    names, paths = _save_uploaded_files([upload], raw, allowed_extensions=ALLOWED)

    assert sorted(names) == [
        "Week1/Slides.pdf",
        "Week1/Uebung.pdf",
        "Week2/Loesung.pdf",
        "Week2/Slides.pdf",
    ]
    assert (raw / "Week2" / "Slides.pdf").read_bytes() == b"w2 slides"
    assert sorted(paths) == sorted(str(raw / name) for name in names)


def test_zip_inside_a_folder_lands_under_that_folder(tmp_path: Path) -> None:
    upload = _zip_upload("course.zip", [("Week1/Slides.pdf", b"s")])
    raw = tmp_path / "raw"
    raw.mkdir()

    names, _ = _save_uploaded_files(
        [upload],
        raw,
        allowed_extensions=ALLOWED,
        rel_paths=["Downloads/course.zip"],
        dest_subdir="Semester",
    )

    assert names == ["Semester/Downloads/Week1/Slides.pdf"]


def _course_zip() -> list[tuple[str, bytes]]:
    return [
        ("Week1/Slides.pdf", b"w1 slides"),
        ("Week2/Slides.pdf", b"w2 slides"),
        ("__MACOSX/Week1/._Slides.pdf", b"fork"),
        ("Week1/.DS_Store", b"ds"),
    ]


def test_reimporting_the_same_zip_skips_identical_files(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    _save_uploaded_files(
        [_zip_upload("course.zip", _course_zip())], raw, allowed_extensions=ALLOWED
    )
    before = {p: p.stat().st_mtime_ns for p in raw.rglob("*") if p.is_file()}
    report = UploadImportReport()

    names, paths = _save_uploaded_files(
        [_zip_upload("course.zip", _course_zip())],
        raw,
        allowed_extensions=ALLOWED,
        import_report=report,
    )

    assert names == []  # nothing new was stored
    assert report.duplicates == ["Week1/Slides.pdf", "Week2/Slides.pdf"]
    assert report.renamed == [] and report.rejected == []  # OS junk is not reported
    # Identical files are still handed to indexing, which skips what it holds
    # by content hash and retries a copy whose earlier indexing failed.
    assert sorted(paths) == sorted(str(raw / name) for name in report.duplicates)
    assert {p: p.stat().st_mtime_ns for p in raw.rglob("*") if p.is_file()} == before


def test_changed_file_at_an_existing_path_is_kept_beside_the_original(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "Week1").mkdir(parents=True)
    (raw / "Week1" / "Slides.pdf").write_bytes(b"v1")
    report = UploadImportReport()
    entries = [("Week1/Slides.pdf", b"v2"), ("Week1/Uebung.pdf", b"new")]

    names, _ = _save_uploaded_files(
        [_zip_upload("course.zip", entries)],
        raw,
        allowed_extensions=ALLOWED,
        import_report=report,
    )

    # Same rule as every other KB staging path: never replace a different
    # document; the newcomer takes a free sibling name and both are indexed.
    assert (raw / "Week1" / "Slides.pdf").read_bytes() == b"v1"
    assert (raw / "Week1" / "Slides (2).pdf").read_bytes() == b"v2"
    assert sorted(names) == ["Week1/Slides (2).pdf", "Week1/Uebung.pdf"]
    assert report.renamed == [
        {"path": "Week1/Slides (2).pdf", "conflicts_with": "Week1/Slides.pdf"}
    ]

    # Importing the same download again is a no-op, sibling included.
    again = UploadImportReport()
    names, _ = _save_uploaded_files(
        [_zip_upload("course.zip", entries)],
        raw,
        allowed_extensions=ALLOWED,
        import_report=again,
    )
    assert names == []
    assert again.duplicates == ["Week1/Slides (2).pdf", "Week1/Uebung.pdf"]
    assert again.renamed == []
    assert not (raw / "Week1" / "Slides (3).pdf").exists()


def test_unsupported_members_are_reported_not_silently_dropped(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    report = UploadImportReport()

    _save_uploaded_files(
        [_zip_upload("course.zip", [("Week1/Slides.pdf", b"s"), ("tools/setup.exe", b"x")])],
        raw,
        allowed_extensions=ALLOWED,
        import_report=report,
    )

    assert [item["file"] for item in report.rejected] == ["course.zip/tools/setup.exe"]
    assert "Unsupported file type" in report.rejected[0]["reason"]


def test_failed_batch_removes_zip_members_but_keeps_existing_files(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "Week1").mkdir(parents=True)
    (raw / "Week1" / "Slides.pdf").write_bytes(b"v1")
    archive = _zip_upload("course.zip", [("Week1/Slides.pdf", b"v1"), ("Week2/new.pdf", b"n")])
    bad = UploadFile(filename="notes.exe", file=io.BytesIO(b"x"))

    with pytest.raises(HTTPException):
        _save_uploaded_files([archive, bad], raw, allowed_extensions=ALLOWED)

    assert (raw / "Week1" / "Slides.pdf").read_bytes() == b"v1"
    assert not (raw / "Week2" / "new.pdf").exists()


def test_oversize_archive_suggests_uploading_the_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(DocumentValidator, "MAX_FILE_SIZE", 64)
    raw = tmp_path / "raw"
    raw.mkdir()
    upload = _zip_upload("course.zip", [("Week1/Slides.pdf", b"x" * 200)])

    with pytest.raises(HTTPException) as exc_info:
        _save_uploaded_files([upload], raw, allowed_extensions=ALLOWED)

    assert exc_info.value.status_code == 400
    assert "upload the folder instead" in exc_info.value.detail


def test_member_clashing_with_an_existing_file_is_reported_not_fatal(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "notes.md").write_bytes(b"a file, not a folder")
    report = UploadImportReport()

    names, _ = _save_uploaded_files(
        [_zip_upload("bundle.zip", [("notes.md/c.md", b"c"), ("Week1/ok.md", b"ok")])],
        raw,
        allowed_extensions=ALLOWED,
        import_report=report,
    )

    assert names == ["Week1/ok.md"]
    assert [item["file"] for item in report.rejected] == ["bundle.zip/notes.md/c.md"]
    assert str(tmp_path) not in report.rejected[0]["reason"]
    assert (raw / "notes.md").read_bytes() == b"a file, not a folder"


def test_failed_batch_removes_folders_the_archive_created(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "Week1").mkdir(parents=True)
    archive = _zip_upload("course.zip", [("Week1/a.pdf", b"a"), ("Week2/Sub/b.pdf", b"b")])
    bad = UploadFile(filename="notes.exe", file=io.BytesIO(b"x"))

    with pytest.raises(HTTPException):
        _save_uploaded_files([archive, bad], raw, allowed_extensions=ALLOWED)

    assert sorted(p.relative_to(raw).as_posix() for p in raw.rglob("*")) == ["Week1"]


def test_member_under_a_symlinked_folder_never_leaves_the_kb(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "Week1").symlink_to(outside, target_is_directory=True)
    report = UploadImportReport()

    names, _ = _save_uploaded_files(
        [_zip_upload("course.zip", [("Week1/Slides.pdf", b"s"), ("Week2/ok.pdf", b"o")])],
        raw,
        allowed_extensions=ALLOWED,
        import_report=report,
    )

    assert names == ["Week2/ok.pdf"]
    assert list(outside.iterdir()) == []
    assert report.rejected == [{"file": "course.zip/Week1/Slides.pdf", "reason": "unsafe path"}]


def test_same_member_in_two_archives_of_one_batch_is_stored_once(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    report = UploadImportReport()

    names, paths = _save_uploaded_files(
        [
            _zip_upload("part1.zip", [("Week1/Slides.pdf", b"s")]),
            _zip_upload("part2.zip", [("Week1/Slides.pdf", b"s")]),
        ],
        raw,
        allowed_extensions=ALLOWED,
        import_report=report,
    )

    assert names == ["Week1/Slides.pdf"]
    assert paths == [str(raw / "Week1" / "Slides.pdf")]
    assert report.duplicates == []  # not "already present": this upload wrote it


def test_rejected_reason_is_short(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    report = UploadImportReport()

    _save_uploaded_files(
        [_zip_upload("course.zip", [("ok.pdf", b"s"), ("setup.exe", b"x")])],
        raw,
        allowed_extensions=ALLOWED,
        import_report=report,
    )

    assert report.rejected == [
        {"file": "course.zip/setup.exe", "reason": "Unsupported file type: .exe"}
    ]
