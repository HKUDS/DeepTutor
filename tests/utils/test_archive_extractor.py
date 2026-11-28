"""Tests for the safe ZIP extractor (``deeptutor.utils.archive_extractor``).

These lock in the security guards that a naive ``extractall`` lacks: Zip Slip
defusal, extension whitelisting, nested-archive rejection, duplicate handling,
and the zip-bomb size/count/ratio limits.
"""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from deeptutor.utils.archive_extractor import (
    ArchiveTooLargeError,
    ZipExtractionLimits,
    safe_extract_zip,
)

DOC_EXTS = {".txt", ".md", ".pdf", ".zip"}  # .zip is intentionally never extracted


def _make_zip(path: Path, entries: list[tuple[str, bytes]], *, deflate: bool = False) -> Path:
    mode = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w", compression=mode) as zf:
        for name, data in entries:
            # A ZipInfo carries its own compress_type, so set it explicitly —
            # otherwise writestr(ZipInfo, ...) ignores the archive's mode.
            info = zipfile.ZipInfo(name)
            info.compress_type = mode
            zf.writestr(info, data)
    return path


def test_extracts_allowed_files_flat(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("notes.txt", b"hello"), ("paper.md", b"# title")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    names = sorted(p.name for p in result.extracted)
    assert names == ["notes.txt", "paper.md"]
    assert (out / "notes.txt").read_bytes() == b"hello"
    assert result.skipped == []


def test_zip_slip_is_defused(tmp_path: Path) -> None:
    # Member names that try to escape via traversal or absolute paths.
    src = _make_zip(
        tmp_path / "evil.zip",
        [("../../escape.txt", b"x"), ("/abs/secret.txt", b"y"), ("a/b/deep.txt", b"z")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    # Everything is flattened into the target; nothing escapes it.
    for p in result.extracted:
        assert out.resolve() in p.resolve().parents
    assert not (tmp_path / "escape.txt").exists()
    assert not Path("/abs/secret.txt").exists()
    assert sorted(p.name for p in result.extracted) == ["deep.txt", "escape.txt", "secret.txt"]


def test_disallowed_extension_is_skipped(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("ok.txt", b"x"), ("malware.exe", b"x"), ("run.sh", b"x")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["ok.txt"]
    skipped_names = {member for member, _ in result.skipped}
    assert "malware.exe" in skipped_names
    assert "run.sh" in skipped_names


def test_nested_zip_is_never_extracted(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("inner.zip", b"PK\x03\x04"), ("ok.txt", b"x")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["ok.txt"]
    assert any(member == "inner.zip" for member, _ in result.skipped)


def test_unbounded_parser_policy_still_rejects_nested_zip(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "a.zip",
        [("vendor.custom", b"payload"), ("inner.zip", b"PK\x03\x04")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=set())

    assert [p.name for p in result.extracted] == ["vendor.custom"]
    assert any(
        member == "inner.zip" and reason == "nested archive" for member, reason in result.skipped
    )


def test_macosx_and_dotfiles_are_skipped(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "a.zip",
        [("__MACOSX/._notes.txt", b"junk"), (".hidden.txt", b"junk"), ("real.txt", b"ok")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["real.txt"]


def test_duplicate_basenames_after_flattening(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("chap1/notes.txt", b"one"), ("chap2/notes.txt", b"two")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["notes.txt"]
    assert (out / "notes.txt").read_bytes() == b"one"  # first wins
    assert any("duplicate" in reason for _, reason in result.skipped)


def _names_ignore_case(directory: Path) -> bool:
    probe = directory / "Case-Probe"
    probe.touch()
    try:
        return (directory / "case-probe").exists()
    finally:
        probe.unlink()


def test_case_only_duplicate_basenames_follow_the_filesystem(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "a.zip",
        [("week1/README.md", b"one"), ("week2/readme.md", b"two"), ("notes.txt", b"n")],
    )
    out = tmp_path / "out"
    out.mkdir()
    case_insensitive = _names_ignore_case(out)

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    if case_insensitive:
        # Windows/macOS: one file on disk, so the later member is a duplicate.
        assert [p.name for p in result.extracted] == ["README.md", "notes.txt"]
        assert (out / "README.md").read_bytes() == b"one"  # first wins
        assert ("week2/readme.md", "duplicate name after flattening") in result.skipped
    else:
        assert [p.name for p in result.extracted] == ["README.md", "readme.md", "notes.txt"]
        assert result.skipped == []


def test_case_only_match_with_existing_file_is_still_refused(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("new.txt", b"new"), ("readme.md", b"replacement")])
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "README.md"
    existing.write_bytes(b"original")

    if _names_ignore_case(out):
        with pytest.raises(FileExistsError):
            safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)
        assert not (out / "new.txt").exists()
    else:
        result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)
        assert [p.name for p in result.extracted] == ["new.txt", "readme.md"]
    assert existing.read_bytes() == b"original"


def test_per_entry_size_cap_raises(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("big.txt", b"x" * 100)])
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src, out, allowed_extensions=DOC_EXTS, limits=ZipExtractionLimits(max_entry_bytes=10)
        )


def test_too_many_entries_raises(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [(f"f{i}.txt", b"x") for i in range(5)])
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src, out, allowed_extensions=DOC_EXTS, limits=ZipExtractionLimits(max_entries=3)
        )


def test_total_size_cap_raises(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("a.txt", b"x" * 60), ("b.txt", b"x" * 60)])
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src,
            out,
            allowed_extensions=DOC_EXTS,
            limits=ZipExtractionLimits(max_total_bytes=100, max_entry_bytes=100),
        )


def test_compression_ratio_guard_raises(tmp_path: Path) -> None:
    # 50 KB of identical bytes compresses to a few hundred bytes -> very high ratio.
    src = _make_zip(tmp_path / "bomb.zip", [("a.txt", b"A" * 50_000)], deflate=True)
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src,
            out,
            allowed_extensions=DOC_EXTS,
            limits=ZipExtractionLimits(max_compression_ratio=10.0),
        )


def test_rejected_archive_removes_members_already_extracted(tmp_path: Path) -> None:
    # The ratio guard trips on the second member, after the first was written.
    src = _make_zip(
        tmp_path / "a.zip", [("notes.txt", b"hello"), ("bomb.txt", b"A" * 50_000)], deflate=True
    )
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src,
            out,
            allowed_extensions=DOC_EXTS,
            limits=ZipExtractionLimits(max_compression_ratio=10.0),
        )

    assert list(out.iterdir()) == []


def test_corrupt_member_leaves_nothing_behind(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("one.txt", b"first"), ("two.txt", b"second")])
    data = bytearray(src.read_bytes())
    # Members are stored, so this flips a payload byte and two.txt fails its CRC
    # check, which zipfile only reports after the bytes were written out.
    data[data.rindex(b"second")] ^= 0xFF
    src.write_bytes(bytes(data))
    out = tmp_path / "out"

    with pytest.raises(zipfile.BadZipFile):
        safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert list(out.iterdir()) == []


def test_bad_zip_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "not.zip"
    bogus.write_bytes(b"this is not a zip")
    with pytest.raises(zipfile.BadZipFile):
        safe_extract_zip(bogus, tmp_path / "out", allowed_extensions=DOC_EXTS)


@pytest.mark.parametrize("readonly", [False, True])
def test_existing_file_is_never_overwritten_or_cleaned_up(tmp_path, readonly):
    src = _make_zip(tmp_path / "a.zip", [("new.txt", b"new"), ("existing.txt", b"replacement")])
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "existing.txt"
    existing.write_bytes(b"original")
    if readonly:
        existing.chmod(0o444)
    try:
        with pytest.raises((FileExistsError, PermissionError)):
            safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)
        assert existing.read_bytes() == b"original"
        assert not (out / "new.txt").exists()
    finally:
        existing.chmod(0o644)


@pytest.mark.parametrize("failure", ["read", "close"])
def test_failed_member_closes_before_cleanup(tmp_path, monkeypatch, failure):
    """Simulate Windows deny-delete sharing and buffered flush/close failure."""
    import io

    import deeptutor.utils.archive_extractor as extractor

    destination = tmp_path / "partial.txt"
    real_open = open
    real_unlink = Path.unlink
    sinks = []

    class Sink:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def write(self, data):
            return self.handle.write(data)

        def __exit__(self, *args):
            self.handle.close()
            if failure == "close":
                raise OSError("flush failed")

    class Source(io.BytesIO):
        def read(self, size=-1):
            if failure == "read" and self.tell():
                raise zipfile.BadZipFile("CRC mismatch")
            return super().read(size)

    class Archive:
        def open(self, _info):
            return Source(b"partial contents")

    def tracked_open(*args, **kwargs):
        sink = Sink(real_open(*args, **kwargs))
        sinks.append(sink)
        return sink

    def windows_unlink(path, *args, **kwargs):
        if path == destination and any(not sink.handle.closed for sink in sinks):
            raise PermissionError("cannot delete an open file")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(extractor, "open", tracked_open, raising=False)
    monkeypatch.setattr(Path, "unlink", windows_unlink)
    with pytest.raises((zipfile.BadZipFile, OSError)):
        extractor._extract_member(Archive(), object(), destination, 100)
    assert sinks and all(sink.handle.closed for sink in sinks)
    assert not destination.exists()


# ── keep_subdirs: course-download layout (one ``Slides.pdf`` per section) ──


def _extracted_rel(result, out: Path) -> list[str]:
    return sorted(p.relative_to(out.resolve()).as_posix() for p in result.extracted)


def test_keep_subdirs_preserves_same_named_members_in_different_folders(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "course.zip",
        [
            ("Week1/Slides.pdf", b"w1 slides"),
            ("Week1/Uebung.pdf", b"w1 exercise"),
            ("Week2/Slides.pdf", b"w2 slides"),
        ],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    assert _extracted_rel(result, out) == [
        "Week1/Slides.pdf",
        "Week1/Uebung.pdf",
        "Week2/Slides.pdf",
    ]
    assert (out / "Week2" / "Slides.pdf").read_bytes() == b"w2 slides"
    assert result.skipped == []


def test_keep_subdirs_reads_windows_backslash_member_names(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "win.zip",
        [("Kurs\\Woche 1\\Slides.pdf", b"one"), ("Kurs\\Woche 2\\Slides.pdf", b"two")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    assert _extracted_rel(result, out) == ["Kurs/Woche 1/Slides.pdf", "Kurs/Woche 2/Slides.pdf"]


def test_keep_subdirs_never_lets_a_member_escape(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "evil.zip",
        [
            ("../../escape.txt", b"x"),
            ("ok/../../escape2.txt", b"x"),
            ("..\\..\\escape3.txt", b"x"),
            ("/abs/secret.txt", b"y"),
            ("C:\\Users\\x\\notes.txt", b"z"),
        ],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    for p in result.extracted:
        assert out.resolve() in p.resolve().parents
    # Absolute and drive-qualified names are re-rooted under the target.
    assert _extracted_rel(result, out) == ["C/Users/x/notes.txt", "abs/secret.txt"]
    # Traversal members are refused one by one, not silently flattened.
    refused = {member for member, reason in result.skipped if reason == "unsafe path"}
    assert refused == {"../../escape.txt", "ok/../../escape2.txt", "..\\..\\escape3.txt"}
    assert not list(tmp_path.glob("escape*"))


def test_keep_subdirs_skips_os_junk_anywhere_in_the_tree(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "mac.zip",
        [
            ("Week1/Slides.pdf", b"real"),
            ("__MACOSX/Week1/._Slides.pdf", b"fork"),
            ("Week1/.DS_Store", b"ds"),
            ("Week1/.git/notes.md", b"vcs"),
            (".ipynb_checkpoints/notes-checkpoint.md", b"jupyter"),
            (".Trashes/501/old.pdf", b"trash"),
            ("Week1/Thumbs.db", b"thumbs"),
            ("Week1/desktop.ini", b"ini"),
        ],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    assert _extracted_rel(result, out) == ["Week1/Slides.pdf"]
    assert {reason for _, reason in result.skipped} == {"system file or dotfile"}
    assert not (out / "__MACOSX").exists()


def test_keep_subdirs_still_refuses_an_existing_file_by_default(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("Week1/new.txt", b"new"), ("Week1/old.txt", b"v2")])
    out = tmp_path / "out"
    (out / "Week1").mkdir(parents=True)
    existing = out / "Week1" / "old.txt"
    existing.write_bytes(b"v1")

    with pytest.raises(FileExistsError):
        safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    assert existing.read_bytes() == b"v1"
    assert not (out / "Week1" / "new.txt").exists()


def test_keep_subdirs_rejected_archive_removes_created_folders(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "a.zip",
        [("Week1/Sub/notes.txt", b"hello"), ("Week2/bomb.txt", b"A" * 50_000)],
        deflate=True,
    )
    out = tmp_path / "out"
    (out / "Week1").mkdir(parents=True)  # pre-existing folder must survive

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src,
            out,
            allowed_extensions=DOC_EXTS,
            limits=ZipExtractionLimits(max_compression_ratio=10.0),
            keep_subdirs=True,
        )

    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*")) == ["Week1"]


@pytest.mark.parametrize("keep_subdirs", [False, True])
def test_name_too_long_for_the_filesystem_skips_only_that_member(
    tmp_path: Path, keep_subdirs: bool
) -> None:
    too_long = "Ü" * 200  # 400 UTF-8 bytes: over every common filesystem limit
    src = _make_zip(
        tmp_path / "a.zip",
        [(f"{too_long}/notes.md", b"x"), (f"Week1/{too_long}.md", b"y"), ("ok.md", b"z")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=keep_subdirs)

    names = sorted(p.name for p in result.extracted)
    assert "ok.md" in names
    assert any(reason == "path too long" for _, reason in result.skipped)
    if keep_subdirs:
        # The folder made for the refused ``Week1/<too long>.md`` is not left behind.
        assert not (out / "Week1").exists()


def test_keep_subdirs_keeps_an_ordinary_dot_folder(tmp_path: Path) -> None:
    """Only known junk folders are dropped; ``.NET Basics/`` is course content."""
    src = _make_zip(
        tmp_path / "a.zip",
        [(".NET Basics/Slides1.pdf", b"s1"), ("Week1/.notes/summary.md", b"sum")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    # The folder-upload sanitizer strips leading dots from a folder name.
    assert _extracted_rel(result, out) == ["NET Basics/Slides1.pdf", "Week1/notes/summary.md"]
    assert result.skipped == []


@pytest.mark.parametrize(
    "order",
    [["a.pdf", "a.pdf/x.pdf"], ["a.pdf/x.pdf", "a.pdf"]],
    ids=["file-first", "folder-first"],
)
def test_keep_subdirs_file_and_folder_with_one_name_skip_only_the_member(
    tmp_path: Path, order: list[str]
) -> None:
    src = _make_zip(tmp_path / "a.zip", [*((name, b"x") for name in order), ("ok.md", b"ok")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    assert _extracted_rel(result, out) == sorted([order[0], "ok.md"])
    assert result.skipped == [(order[1], "path conflict")]


def test_keep_subdirs_merges_nfd_and_nfc_spellings_of_a_folder(tmp_path: Path) -> None:
    """A macOS-made zip spells \u00dc as U + combining diaeresis (NFD)."""
    src = _make_zip(
        tmp_path / "a.zip",
        [("U\u0308bung/a.pdf", b"a"), ("\u00dcbung/b.pdf", b"b")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS, keep_subdirs=True)

    assert _extracted_rel(result, out) == ["\u00dcbung/a.pdf", "\u00dcbung/b.pdf"]
