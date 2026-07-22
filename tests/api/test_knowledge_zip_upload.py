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

from deeptutor.api.routers.knowledge import _save_uploaded_files

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
        zf.writestr("safe.txt", b"y")
    buf.seek(0)
    upload = UploadFile(filename="evil.zip", file=buf)
    raw = tmp_path / "raw"
    raw.mkdir()

    names, _ = _save_uploaded_files([upload], raw, allowed_extensions=ALLOWED)

    assert sorted(names) == ["escape.txt", "safe.txt"]
    assert (raw / "escape.txt").exists()
    assert not (tmp_path / "escape.txt").exists()  # did not escape


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
