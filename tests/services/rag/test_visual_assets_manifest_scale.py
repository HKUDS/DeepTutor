"""Sharded visual-asset manifest scaling (#1802).

The manifest used to be a single JSON file with a hard 16 MB cap: a
figure-heavy KB would cross the ceiling, every further ingest failed whole,
and the read path silently returned nothing for the assets already indexed.
The store now shards the manifest behind a small index, so scale no longer
produces failures — and legacy single-file manifests, including ones already
over the old cap, still resolve.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.rag.visual_assets import (
    MAX_MANIFEST_BYTES,
    SHARD_SOFT_TARGET_BYTES,
    VisualAssetStore,
)


def _record(asset_id: str, source: str = "doc.pdf") -> dict:
    # ~1 KB of padding per record, matching the issue's measured scale.
    return {
        "asset_id": asset_id,
        "source_path": f"{source}",
        "mime_type": "image/png",
        "image_sha256": asset_id.replace("-", "0") * 2,
        "size": 1234,
        "page": 1,
        "caption": "figure " + "x" * 900,
    }


def _seed_legacy_manifest(store: VisualAssetStore, count: int, *, pad: str = "x") -> None:
    """Write a version-1 single-file manifest the old way (inline assets)."""
    store.root.mkdir(parents=True, exist_ok=True)
    records = {
        f"{i:064x}": _record(f"{i:064x}") | {"caption": "figure " + pad * 900} for i in range(count)
    }
    store.manifest_path.write_text(
        json.dumps({"version": 1, "assets": records}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def test_legacy_manifest_still_reads(tmp_path: Path) -> None:
    store = VisualAssetStore(tmp_path)
    _seed_legacy_manifest(store, 5)

    records = store.records()

    assert len(records) == 5


def test_legacy_manifest_over_the_old_cap_still_reads(tmp_path: Path) -> None:
    """Assets already indexed must not vanish once the legacy file crossed
    the old cap — the silent-return read path was half of the bug."""
    store = VisualAssetStore(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    # ~10 KB per record: crosses the old 16 MB cap within a few hundred rows.
    records = {
        f"{i:064x}": _record(f"{i:064x}") | {"caption": "pad " + "y" * 9500}
        for i in range((MAX_MANIFEST_BYTES // 10240) + 100)
    }
    store.manifest_path.write_text(
        json.dumps({"version": 1, "assets": records}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    assert store.manifest_path.stat().st_size > MAX_MANIFEST_BYTES

    loaded = store.records()

    assert len(loaded) == len(records)


def test_publish_beyond_the_old_cap_shards_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VisualAssetStore(tmp_path)
    monkeypatch.setattr("deeptutor.services.rag.visual_assets.SHARD_SOFT_TARGET_BYTES", 64 * 1024)
    count = 3000
    # publish() validates image bytes against real files, which a unit test
    # does not have; the write path is exercised directly (unit under test).
    records = {
        f"{i:064x}": _record(f"{i:064x}") | {"caption": "pad " + "z" * 1000} for i in range(count)
    }
    store.root.mkdir(parents=True, exist_ok=True)
    store._write_sharded(records)  # noqa: SLF001 - unit under test

    assert store.manifest_path.stat().st_size < MAX_MANIFEST_BYTES
    loaded = store.records()
    assert len(loaded) == count


def test_shards_stay_below_the_per_file_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VisualAssetStore(tmp_path)
    monkeypatch.setattr("deeptutor.services.rag.visual_assets.SHARD_SOFT_TARGET_BYTES", 64 * 1024)
    count = 3000
    records = {
        f"{i:064x}": _record(f"{i:064x}") | {"caption": "pad " + "w" * 1000} for i in range(count)
    }
    store.root.mkdir(parents=True, exist_ok=True)
    store._write_sharded(records)  # noqa: SLF001 - unit under test

    shard_paths = sorted(store.root.glob("manifest.shard-*.json"))
    assert len(shard_paths) > 1
    for shard in shard_paths:
        assert shard.stat().st_size < MAX_MANIFEST_BYTES
    index = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert index["version"] == 2
    assert index["shards"] == [p.name for p in shard_paths]
    assert len(store.records()) == count


def test_stale_shards_are_removed_when_the_set_shrinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VisualAssetStore(tmp_path)
    monkeypatch.setattr("deeptutor.services.rag.visual_assets.SHARD_SOFT_TARGET_BYTES", 64 * 1024)
    big = {f"{i:064x}": _record(f"{i:064x}") | {"caption": "p" * 900} for i in range(400)}
    store.root.mkdir(parents=True, exist_ok=True)
    store._write_sharded(big)  # noqa: SLF001 - unit under test
    many_shards = sorted(store.root.glob("manifest.shard-*.json"))
    assert len(many_shards) > 1

    small = dict(list(big.items())[:10])
    store._write_sharded(small)  # noqa: SLF001 - unit under test

    remaining = sorted(store.root.glob("manifest.shard-*.json"))
    assert len(remaining) == 1
    index = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert index["shards"] == [p.name for p in remaining]
    assert len(store.records()) == 10


def test_remove_source_and_move_source_work_on_sharded_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VisualAssetStore(tmp_path)
    monkeypatch.setattr("deeptutor.services.rag.visual_assets.SHARD_SOFT_TARGET_BYTES", 64 * 1024)
    records = {
        f"{i:064x}": _record(f"{i:064x}", source=f"doc-{i % 3}.pdf") | {"caption": "c" * 900}
        for i in range(400)
    }
    store.root.mkdir(parents=True, exist_ok=True)
    store._write_sharded(records)  # noqa: SLF001 - unit under test

    store.remove_source("doc-0.pdf")
    assert all(r["source_path"] != "doc-0.pdf" for r in store.records().values())

    store.move_source("doc-1.pdf", "renamed/doc-1.pdf")
    moved = [r for r in store.records().values() if r["source_path"].startswith("renamed/")]
    assert moved


def test_unreadable_shard_is_skipped_fail_open(tmp_path: Path) -> None:
    store = VisualAssetStore(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    good = _record("a" * 64)
    store._atomic_write(
        store._shard_path("manifest.shard-000.json"),
        json.dumps({"version": 2, "assets": {"a" * 64: good}}, ensure_ascii=False).encode(),
    )
    broken = store._shard_path("manifest.shard-001.json")
    broken.write_text("{not json", encoding="utf-8")
    store._atomic_write(
        store.manifest_path,
        json.dumps(
            {"version": 2, "shards": ["manifest.shard-000.json", "manifest.shard-001.json"]},
            ensure_ascii=False,
        ).encode(),
    )

    records = store.records()

    assert set(records) == {"a" * 64}


def test_shard_name_that_is_not_a_shard_is_rejected(tmp_path: Path) -> None:
    store = VisualAssetStore(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    store._atomic_write(
        store.manifest_path,
        json.dumps({"version": 2, "shards": ["../../escape.json"]}, ensure_ascii=False).encode(),
    )

    assert store.records() == {}
