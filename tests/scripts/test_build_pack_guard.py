"""A pack must not claim a version its payload does not contain.

The 2026-09-24 Phase 2 run built a "1.6.11" pack whose wheel was still 1.6.10:
`--app-version` only renames the archive, while the wheel comes from
`deeptutor/__version__.py`. Every checksum and the whole delta pipeline stayed
internally consistent, so nothing complained — the mistake would only surface
as "the update installed and nothing changed".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "desktop" / "pack" / "build_pack.py"
SPEC = importlib.util.spec_from_file_location("build_pack", SCRIPT)
assert SPEC and SPEC.loader
build_pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_pack)


def test_wheel_version_is_read_from_the_filename() -> None:
    assert build_pack.wheel_version(Path("deeptutor-1.6.11-py3-none-any.whl")) == "1.6.11"
    with pytest.raises(SystemExit):
        build_pack.wheel_version(Path("something-else.whl"))


def test_a_mislabelled_pack_is_refused() -> None:
    with pytest.raises(SystemExit) as error:
        build_pack.assert_wheel_matches_label(Path("deeptutor-1.6.10-py3-none-any.whl"), "1.6.11")
    assert "bump deeptutor/__version__.py" in str(error.value)


def test_a_correct_label_passes() -> None:
    build_pack.assert_wheel_matches_label(Path("deeptutor-1.6.11-py3-none-any.whl"), "1.6.11")


# --- Supply chain: what arrives from upstream and what an archive may contain --


def _tar_with(tmp_path: Path, name: str, members: list[tuple[str, bytes]]) -> Path:
    import io
    import tarfile

    archive = tmp_path / name
    with tarfile.open(archive, "w:gz") as handle:
        for member_name, payload in members:
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            info.mode = 0o644
            handle.addfile(info, io.BytesIO(payload))
    return archive


def _zip_with(tmp_path: Path, name: str, entries: list[tuple[str, bytes]]) -> Path:
    import zipfile

    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w") as handle:
        for entry_name, payload in entries:
            handle.writestr(entry_name, payload)
    return archive


def test_checksums_are_parsed_from_the_published_format() -> None:
    digest = "a" * 64
    text = (
        f"{digest}  cpython-3.12.14.tar.gz\n"
        f"{'B' * 64} *node-v20.18.0-darwin-arm64.tar.gz\n"
        "\n"
        "# a comment line\n"
        "not-a-checksum  other.tar.gz\n"
    )
    parsed = build_pack.parse_checksums(text)
    assert parsed["cpython-3.12.14.tar.gz"] == digest
    assert parsed["node-v20.18.0-darwin-arm64.tar.gz"] == "b" * 64
    assert "other.tar.gz" not in parsed


def test_a_download_is_checked_against_the_published_digest(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    archive.write_bytes(b"payload")
    digest = build_pack.sha256_file(archive)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{digest}  runtime.tar.gz\n", encoding="utf-8")

    destination = tmp_path / "cache" / "runtime.tar.gz"
    build_pack.download_verified(
        archive.as_uri(),
        destination,
        checksums_url=sums.as_uri(),
        source="test",
    )
    assert destination.read_bytes() == b"payload"

    # A cached file that no longer matches is re-fetched, not trusted.
    destination.write_bytes(b"tampered")
    build_pack.download_verified(
        archive.as_uri(),
        destination,
        checksums_url=sums.as_uri(),
        source="test",
    )
    assert destination.read_bytes() == b"payload"


def test_a_download_without_a_published_digest_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    archive.write_bytes(b"payload")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'0' * 64}  something-else.tar.gz\n", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        build_pack.download_verified(
            archive.as_uri(),
            tmp_path / "cache" / "runtime.tar.gz",
            checksums_url=sums.as_uri(),
            source="test",
        )
    assert "publishes no checksum" in str(error.value)


def test_a_swapped_archive_fails_its_checksum(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    archive.write_bytes(b"payload")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'0' * 64}  runtime.tar.gz\n", encoding="utf-8")

    destination = tmp_path / "cache" / "runtime.tar.gz"
    with pytest.raises(SystemExit) as error:
        build_pack.download_verified(
            archive.as_uri(),
            destination,
            checksums_url=sums.as_uri(),
            source="test",
        )
    assert "failed its test checksum" in str(error.value)
    assert not destination.exists(), "a rejected download must not be left on disk"


def test_archive_entries_cannot_escape_the_destination(tmp_path: Path) -> None:
    outside = tmp_path / "escaped.txt"
    for archive in (
        _tar_with(tmp_path, "traversal.tar.gz", [("../escaped.txt", b"pwned")]),
        _tar_with(tmp_path, "absolute.tar.gz", [(str(outside), b"pwned")]),
        _zip_with(tmp_path, "traversal.zip", [("../escaped.txt", b"pwned")]),
    ):
        with pytest.raises(SystemExit) as error:
            build_pack.extract_archive(archive, tmp_path / f"out-{archive.name}")
        assert "escapes the destination" in str(error.value)
        assert not outside.exists()


def test_an_escaping_link_is_refused_but_a_relative_one_is_not(tmp_path: Path) -> None:
    import io
    import tarfile

    escaping = tmp_path / "escaping-link.tar.gz"
    with tarfile.open(escaping, "w:gz") as handle:
        info = tarfile.TarInfo("python/bin/python3")
        info.size = 2
        info.mode = 0o755
        handle.addfile(info, io.BytesIO(b"#!"))
        link = tarfile.TarInfo("venv/bin/python")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../../etc/passwd"
        handle.addfile(link)
    with pytest.raises(SystemExit) as error:
        build_pack.extract_archive(escaping, tmp_path / "out-escaping")
    assert "link escapes the destination" in str(error.value)

    # A real pack's relative interpreter link must still extract.
    legitimate = tmp_path / "legitimate.tar.gz"
    with tarfile.open(legitimate, "w:gz") as handle:
        info = tarfile.TarInfo("python/bin/python3")
        info.size = 2
        info.mode = 0o755
        handle.addfile(info, io.BytesIO(b"#!"))
        link = tarfile.TarInfo("venv/bin/python")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../python/bin/python3"
        handle.addfile(link)
    destination = tmp_path / "out-legitimate"
    build_pack.extract_archive(legitimate, destination)
    assert (destination / "venv/bin/python").is_symlink()


def test_a_zip_symlink_entry_is_refused(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("payload", b"x")
    # Rewrite one entry with the symlink mode bits set.
    with zipfile.ZipFile(archive, "a") as handle:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16) | 0o644
        handle.writestr(info, "/etc/passwd")

    with pytest.raises(SystemExit) as error:
        build_pack.extract_archive(archive, tmp_path / "out-zip")
    assert "symlink" in str(error.value)


def test_build_delta_refuses_an_archive_that_escapes(tmp_path: Path) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "desktop" / "pack" / "build_delta.py"
    spec = importlib.util.spec_from_file_location("build_delta_guard", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    archive = _tar_with(tmp_path, "stage.tar.gz", [("../escaped.txt", b"pwned")])
    with pytest.raises(SystemExit) as error:
        module.materialise(archive, tmp_path / "work")
    assert "unsafe path" in str(error.value)
    assert not (tmp_path / "escaped.txt").exists()
