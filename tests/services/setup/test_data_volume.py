"""Data-volume writability probe for Unraid / UID-mismatched bind mounts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deeptutor.services.setup.data_volume import (
    DataVolumePermissionError,
    check_container_data_volume,
    ensure_data_volume_writable,
    format_data_volume_permission_error,
    parse_id,
    resolve_runtime_ids,
)


def test_parse_id_rejects_root_and_non_integers() -> None:
    assert parse_id(None, default=1000, name="PUID") == 1000
    assert parse_id("99", default=1000, name="PUID") == 99
    with pytest.raises(ValueError, match="non-root"):
        parse_id("0", default=1000, name="PUID")
    with pytest.raises(ValueError, match="non-root"):
        parse_id("alan", default=1000, name="PUID")


def test_resolve_runtime_ids_keeps_rootless_identity() -> None:
    uid, gid = resolve_runtime_ids(puid="99", pgid="100", euid=501, egid=20)
    assert (uid, gid) == (501, 20)


def test_resolve_runtime_ids_uses_puid_when_root() -> None:
    uid, gid = resolve_runtime_ids(puid="99", pgid="100", euid=0, egid=0)
    assert (uid, gid) == (99, 100)


def test_permission_error_names_uid_mismatch_and_puid_hint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.setup.data_volume.describe_path_ownership",
        lambda _path: "uid=99 gid=100 mode=0755",
    )
    message = format_data_volume_permission_error(tmp_path / "knowledge_bases", uid=1000, gid=1000)

    assert "euid=1000" in message
    assert "uid=99 gid=100 mode=0755" in message
    assert "PUID" in message
    assert "PGID" in message
    assert "not writable" in message


def test_ensure_writable_succeeds_on_owned_directory(tmp_path: Path) -> None:
    target = tmp_path / "data" / "knowledge_bases"
    ensure_data_volume_writable(target)
    assert target.is_dir()
    assert not any(target.glob(".deeptutor-write-probe-*"))


def test_root_probe_defers_mkdir_until_after_identity_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "mounted" / "knowledge_bases"
    monkeypatch.setattr("deeptutor.services.setup.data_volume.os.geteuid", lambda: 0)

    def create_as_runtime_user(path: Path, uid: int, gid: int) -> None:
        assert (uid, gid) == (1234, 1234)
        assert not path.exists()
        path.mkdir(parents=True)

    monkeypatch.setattr(
        "deeptutor.services.setup.data_volume._ensure_writable_as", create_as_runtime_user
    )
    ensure_data_volume_writable(target, uid=1234, gid=1234)
    assert target.is_dir()


def test_ensure_unwritable_directory_fail_fasts(tmp_path: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root bypasses directory mode bits")
    target = tmp_path / "locked"
    target.mkdir()
    target.chmod(0o555)
    try:
        with pytest.raises(DataVolumePermissionError, match="not writable"):
            ensure_data_volume_writable(target)
    finally:
        target.chmod(0o755)


def test_check_container_data_volume_probes_knowledge_bases(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "app-data"
    monkeypatch.setenv("PUID", "1000")
    monkeypatch.setenv("PGID", "1000")
    check_container_data_volume(data_root)
    assert (data_root / "knowledge_bases").is_dir()


def test_check_container_data_volume_fail_fasts_when_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "app-data"
    data_root.mkdir()
    kb_root = data_root / "knowledge_bases"
    kb_root.mkdir()

    def _boom(path, **_kwargs):
        raise DataVolumePermissionError(
            format_data_volume_permission_error(Path(path), uid=1000, gid=1000)
        )

    monkeypatch.setattr(
        "deeptutor.services.setup.data_volume.ensure_data_volume_writable",
        _boom,
    )
    with pytest.raises(DataVolumePermissionError, match="not writable"):
        check_container_data_volume(data_root)
