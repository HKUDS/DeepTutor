"""write_secret_text must never leave a secret readable by other users."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from deeptutor.utils.secret_files import (
    SECRET_FILE_MODE,
    write_secret_text,
)

posix_only = pytest.mark.skipif(
    os.name != "posix", reason="POSIX permission bits are not modelled on Windows"
)


def test_writes_the_content(tmp_path):
    target = tmp_path / "secret.txt"
    write_secret_text(target, "token-value")
    assert target.read_text(encoding="utf-8") == "token-value"


def test_creates_missing_parent(tmp_path):
    target = tmp_path / "nested" / "deeper" / "secret.txt"
    write_secret_text(target, "token-value")
    assert target.exists()


@posix_only
def test_file_is_owner_only(tmp_path):
    target = tmp_path / "secret.txt"
    write_secret_text(target, "token-value")
    assert stat.S_IMODE(target.stat().st_mode) == SECRET_FILE_MODE


@posix_only
def test_replaces_a_wide_open_leftover(tmp_path):
    """O_CREAT does not narrow an existing file, so a leftover must be replaced."""
    target = tmp_path / "secret.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)

    write_secret_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert stat.S_IMODE(target.stat().st_mode) == SECRET_FILE_MODE


@posix_only
def test_never_widens_via_umask(tmp_path):
    previous = os.umask(0)
    try:
        target = tmp_path / "secret.txt"
        write_secret_text(target, "token-value")
        assert stat.S_IMODE(target.stat().st_mode) == SECRET_FILE_MODE
    finally:
        os.umask(previous)


def test_no_partial_file_when_writing_fails(tmp_path, monkeypatch):
    """A failed write must not leave a secret behind."""
    target = tmp_path / "secret.txt"

    real_fdopen = os.fdopen

    def exploding_fdopen(fd, *args, **kwargs):
        handle = real_fdopen(fd, *args, **kwargs)
        handle.close()
        raise OSError("disk full")

    monkeypatch.setattr(os, "fdopen", exploding_fdopen)

    with pytest.raises(OSError):
        write_secret_text(target, "token-value")
    assert not target.exists()
