"""Incremental runtime-pack deltas: the diff, the archive, and the fingerprint.

The fingerprint decides whether an update is safe: the Rust applier recomputes
it on the *installed* pack and refuses to patch anything that does not match
what the builder hashed. These tests pin that contract from the Python side,
including the rehydration normalisation that makes an installed pack comparable
to the tree it was built from.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tarfile

DELTA_SCRIPT = Path(__file__).resolve().parents[2] / "desktop" / "pack" / "build_delta.py"
SPEC = importlib.util.spec_from_file_location("build_delta", DELTA_SCRIPT)
assert SPEC and SPEC.loader
build_delta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_delta)


def write_pack(root: Path, *, version: str, marker: str) -> Path:
    """A miniature pack tree with the parts that matter for a diff."""

    (root / "venv" / "bin").mkdir(parents=True)
    (root / "python" / "bin").mkdir(parents=True)
    (root / "node" / "bin").mkdir(parents=True)
    (root / "venv" / "pyvenv.cfg").write_text(
        f"home = {root}/python/bin\n", encoding="utf-8"
    )
    (root / "venv" / "bin" / "deeptutor").write_text(
        f"#!/usr/bin/env python3\n# {marker}\n", encoding="utf-8"
    )
    (root / "python" / "bin" / "python3").write_bytes(b"\x7fELF still the same bytes")
    (root / "node" / "bin" / "node").write_bytes(b"node runtime, unchanged")
    (root / "manifest.json").write_text(
        json.dumps(
            {"schema_version": 1, "pack_id": f"{version}-macos-aarch64",
             "app_version": version, "platform": "macos-aarch64"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.symlink(f"{root}/python/bin/python3", root / "venv" / "bin" / "python")
    return root


def rehydrated_copy(source: Path, destination: Path) -> Path:
    """What the installer turns a staged tree into: links become relative and the
    pack's own path is rewritten, which is exactly what `rehydrate` does."""

    import shutil

    shutil.copytree(source, destination, symlinks=True)
    (destination / "venv" / "bin" / "python").unlink()
    os.symlink("../../python/bin/python3", destination / "venv" / "bin" / "python")
    for relative in ("venv/pyvenv.cfg", "venv/bin/deeptutor"):
        path = destination / relative
        path.write_text(
            path.read_text(encoding="utf-8").replace(str(source), str(destination)),
            encoding="utf-8",
        )
    return destination


def test_the_fingerprint_survives_installation(tmp_path: Path) -> None:
    staged = write_pack(tmp_path / "stage-1.6.10", version="1.6.10", marker="a")
    installed = rehydrated_copy(staged, tmp_path / "runtimes-1.6.10")

    assert build_delta.tree_digest(build_delta.iter_tree(staged)) == build_delta.tree_digest(
        build_delta.iter_tree(installed)
    ), "an installed pack must fingerprint the same as the tree it was built from"


def test_runtime_by_products_are_ignored(tmp_path: Path) -> None:
    pack = write_pack(tmp_path / "stage", version="1.6.10", marker="a")
    before = build_delta.tree_digest(build_delta.iter_tree(pack))
    (pack / "__pycache__").mkdir()
    (pack / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"cache")
    (pack / "venv" / "bin" / "deeptutor.pyc").write_bytes(b"cache")
    (pack / ".DS_Store").write_bytes(b"junk")
    assert build_delta.tree_digest(build_delta.iter_tree(pack)) == before


def test_a_delta_carries_only_what_changed(tmp_path: Path) -> None:
    base = write_pack(tmp_path / "stage-1.6.10", version="1.6.10", marker="a")
    target = write_pack(tmp_path / "stage-1.6.11", version="1.6.11", marker="b")
    # One file only the new pack has, one the old pack loses.
    (target / "venv" / "bin" / "new-entry-point").write_text("new\n", encoding="utf-8")
    (base / "venv" / "bin" / "gone-entry-point").write_text("old\n", encoding="utf-8")
    # Noise must not travel.
    (target / "__pycache__").mkdir()
    (target / "__pycache__" / "x.pyc").write_bytes(b"cache")

    out = tmp_path / "dist"
    delta = build_delta.build_delta(base, target, out)

    changed = {entry["path"] for entry in delta["changed"]}
    added = {entry["path"] for entry in delta["added"]}
    assert "manifest.json" in changed, delta
    assert "venv/bin/deeptutor" in changed, delta
    assert "venv/bin/new-entry-point" in added, delta
    assert delta["removed"] == ["venv/bin/gone-entry-point"], delta
    # Untouched payload stays out of the archive.
    shipped = changed | added
    assert "node/bin/node" not in shipped
    assert "python/bin/python3" not in shipped
    assert "venv/pyvenv.cfg" not in shipped

    archive = out / f"{delta['target_pack_id']}.delta.tar.gz"
    assert archive.is_file()
    with tarfile.open(archive, "r:gz") as handle:
        names = set(handle.getnames())
        assert "delta.json" in names
        assert "links.json" in names
        assert "files/manifest.json" in names
        assert not any("__pycache__" in name for name in names)
        payload = json.loads(handle.extractfile("delta.json").read())
    assert payload["base_tree_sha256"] == delta["base_tree_sha256"]
    assert payload["target_tree_sha256"] == delta["target_tree_sha256"]
    assert payload["base_pack_id"] == "1.6.10-macos-aarch64"
    assert payload["target_pack_id"] == "1.6.11-macos-aarch64"
    # Entry hashes describe the bytes that travel. Using the *fingerprint*
    # digest here (which tokenises the pack's own path) made the installer
    # reject its own archive.
    for entry in payload["changed"] + payload["added"]:
        raw = (target / entry["path"]).read_bytes()
        import hashlib

        assert entry["sha256"] == hashlib.sha256(raw).hexdigest(), entry
        assert entry["size"] == len(raw), entry

    fragment = json.loads(
        (out / f"{delta['target_pack_id']}.delta.catalog.json").read_text(encoding="utf-8")
    )
    entry = fragment["deltas"][0]
    assert entry["base_pack_id"] == payload["base_pack_id"]
    assert entry["archive"] == archive.name
    assert len(entry["sha256"]) == 64


def test_the_delta_is_a_small_fraction_of_the_pack(tmp_path: Path) -> None:
    """The point of Spike B: only the changed bytes travel."""

    base = write_pack(tmp_path / "stage-1.6.10", version="1.6.10", marker="a")
    # 4 MB of "runtime" that neither release touches.
    (base / "python" / "bin" / "python3").write_bytes(b"\x00" * (4 * 1024 * 1024))
    target = write_pack(tmp_path / "stage-1.6.11", version="1.6.11", marker="b")
    (target / "python" / "bin" / "python3").write_bytes(b"\x00" * (4 * 1024 * 1024))

    out = tmp_path / "dist"
    build_delta.build_delta(base, target, out)
    archive = out / "1.6.11-macos-aarch64.delta.tar.gz"
    assert archive.stat().st_size < 16 * 1024, archive.stat().st_size


def test_a_platform_mismatch_is_refused(tmp_path: Path) -> None:
    base = write_pack(tmp_path / "stage", version="1.6.10", marker="a")
    target = write_pack(tmp_path / "stage2", version="1.6.11", marker="b")
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["platform"] = "windows-x86_64"
    (target / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    try:
        build_delta.build_delta(base, target, tmp_path / "dist")
    except SystemExit as error:
        assert "platform mismatch" in str(error)
    else:  # pragma: no cover - the assertion below is the failure path
        raise AssertionError("a cross-platform delta must not be buildable")


def test_a_delta_that_is_not_worth_shipping_is_skipped(tmp_path: Path) -> None:
    """A release that rebuilds the runtime must not ship a near-full "delta"."""

    base = write_pack(tmp_path / "stage-1.6.10", version="1.6.10", marker="a")
    target = write_pack(tmp_path / "stage-1.6.11", version="1.6.11", marker="b")
    # A runtime where most of the payload changed: incompressible content, two of
    # three files new, so the delta is most of the archive.
    for index in range(3):
        (base / "python" / "bin" / f"blob{index}").write_bytes(os.urandom(200_000))
        payload = (
            os.urandom(200_000) if index < 2 else (base / "python" / "bin" / f"blob{index}").read_bytes()
        )
        (target / "python" / "bin" / f"blob{index}").write_bytes(payload)
    out = tmp_path / "dist"
    out.mkdir()
    # `build_pack.py` writes the archive next to the staged tree; the guard reads
    # it to know what "worth shipping" means.
    with tarfile.open(out / "1.6.11-macos-aarch64.tar.gz", "w:gz") as handle:
        handle.add(target, arcname="stage")

    delta = build_delta.build_delta(base, target, out, max_ratio=0.5)
    assert delta.get("skipped") is True, delta
    assert not (out / "1.6.11-macos-aarch64.delta.tar.gz").exists()
    assert not (out / "1.6.11-macos-aarch64.delta.catalog.json").exists()

    # ...and an explicit --force still produces one for debugging.
    forced = build_delta.build_delta(base, target, out, max_ratio=0.5, force=True)
    assert "skipped" not in forced
    assert (out / "1.6.11-macos-aarch64.delta.tar.gz").is_file()


def _incompressible_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Two stages whose delta is most of the archive."""

    base = write_pack(tmp_path / "stage-1.6.10", version="1.6.10", marker="a")
    target = write_pack(tmp_path / "stage-1.6.11", version="1.6.11", marker="b")
    for index in range(3):
        (base / "python" / "bin" / f"blob{index}").write_bytes(os.urandom(200_000))
        payload = (
            os.urandom(200_000)
            if index < 2
            else (base / "python" / "bin" / f"blob{index}").read_bytes()
        )
        (target / "python" / "bin" / f"blob{index}").write_bytes(payload)
    return base, target


def test_the_ratio_guard_works_when_the_full_archive_is_elsewhere(
    tmp_path: Path,
) -> None:
    """CI downloads the full pack into `current/` and builds into `out/`.

    Without `--full-archive` the guard had nothing to compare against, so it
    silently did nothing and a "delta" bigger than the full archive shipped.
    """

    base, target = _incompressible_pair(tmp_path)
    current = tmp_path / "current"
    current.mkdir()
    full = current / "1.6.11-macos-aarch64.tar.gz"
    with tarfile.open(full, "w:gz") as handle:
        handle.add(target, arcname="stage")
    out = tmp_path / "out"
    out.mkdir()

    delta = build_delta.build_delta(base, target, out, max_ratio=0.5, full_archive=full)

    assert delta.get("skipped") is True, delta
    assert not (out / "1.6.11-macos-aarch64.delta.tar.gz").exists()
    assert not (out / "1.6.11-macos-aarch64.delta.catalog.json").exists()


def test_a_missing_full_archive_says_the_guard_is_off(tmp_path: Path, capsys) -> None:
    base, target = _incompressible_pair(tmp_path)
    out = tmp_path / "out"
    out.mkdir()

    delta = build_delta.build_delta(base, target, out, max_ratio=0.5)

    assert "skipped" not in delta
    assert "guard is inactive" in capsys.readouterr().out


def test_a_skipped_delta_does_not_leave_a_stale_catalog_fragment(
    tmp_path: Path,
) -> None:
    """A fragment pointing at an archive that was just deleted would make the
    merged catalog advertise a download that 404s."""

    base, target = _incompressible_pair(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    stale = out / "1.6.11-macos-aarch64.delta.catalog.json"
    stale.write_text('{"schema_version": 1, "deltas": []}\n', encoding="utf-8")
    with tarfile.open(out / "1.6.11-macos-aarch64.tar.gz", "w:gz") as handle:
        handle.add(target, arcname="stage")

    delta = build_delta.build_delta(base, target, out, max_ratio=0.5)

    assert delta.get("skipped") is True, delta
    assert not stale.exists()
