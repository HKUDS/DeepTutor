from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.rag.index_versioning import (
    EmbeddingSignature,
    find_matching_version,
    list_kb_versions,
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_rebuild,
    resolve_storage_dir_for_write,
    write_version_meta,
)


def _signature(model: str = "embed-a", dim: int = 1024) -> EmbeddingSignature:
    return EmbeddingSignature(
        binding="openai",
        model=model,
        dimension=dim,
        base_url="https://example.test/v1",
        api_version="",
    )


def test_resolve_storage_dir_for_write_allocates_flat_version_dirs(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()

    storage_dir = resolve_storage_dir_for_write(kb_dir, sig)
    (storage_dir / "docstore.json").write_text("{}", encoding="utf-8")
    write_version_meta(kb_dir, sig, storage_dir=storage_dir)

    assert storage_dir == kb_dir / "version-1"
    assert (storage_dir / "meta.json").exists()
    assert not (kb_dir / "index_versions").exists()
    assert not (kb_dir / "llamaindex_storage").exists()


def test_resolve_storage_dir_for_write_reuses_matching_flat_version(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    version_dir = kb_dir / "version-3"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": sig.hash(), "version": "version-3"}),
        encoding="utf-8",
    )

    assert resolve_storage_dir_for_write(kb_dir, sig) == version_dir


def test_resolve_storage_dir_for_rebuild_allocates_fresh_version(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": sig.hash(), "version": "version-1"}),
        encoding="utf-8",
    )

    assert resolve_storage_dir_for_rebuild(kb_dir, sig) == kb_dir / "version-2"


def test_resolve_storage_dir_for_write_without_signature_still_uses_flat_layout(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"

    storage_dir = resolve_storage_dir_for_write(kb_dir, None)

    assert storage_dir == kb_dir / "version-1"
    assert not (kb_dir / "llamaindex_storage").exists()
    assert not (kb_dir / "index_versions").exists()


def test_resolve_storage_dir_for_read_without_signature_prefers_latest_flat_version(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    for version in ("version-1", "version-2"):
        version_dir = kb_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "docstore.json").write_text("{}", encoding="utf-8")

    assert resolve_storage_dir_for_read(kb_dir, None) == kb_dir / "version-2"


def test_read_prefers_flat_version_over_legacy_nested_with_same_signature(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    flat = kb_dir / "version-1"
    flat.mkdir(parents=True)
    (flat / "docstore.json").write_text("{}", encoding="utf-8")
    (flat / "meta.json").write_text(
        json.dumps({"signature": sig.hash(), "version": "version-1"}),
        encoding="utf-8",
    )
    legacy = kb_dir / "index_versions" / sig.hash()
    legacy_storage = legacy / "llamaindex_storage"
    legacy_storage.mkdir(parents=True)
    (legacy_storage / "docstore.json").write_text("{}", encoding="utf-8")
    (legacy / "meta.json").write_text(
        json.dumps({"signature": sig.hash()}),
        encoding="utf-8",
    )

    assert resolve_storage_dir_for_read(kb_dir, sig) == flat
    assert find_matching_version(kb_dir, sig)["layout"] == "flat"


def test_list_kb_versions_includes_legacy_nested_and_root_layouts(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    nested = kb_dir / "index_versions" / sig.hash()
    nested_storage = nested / "llamaindex_storage"
    nested_storage.mkdir(parents=True)
    (nested_storage / "docstore.json").write_text("{}", encoding="utf-8")
    (nested / "meta.json").write_text(json.dumps({"signature": sig.hash()}), encoding="utf-8")
    root_storage = kb_dir / "llamaindex_storage"
    root_storage.mkdir(parents=True)
    (root_storage / "docstore.json").write_text("{}", encoding="utf-8")

    layouts = {entry["layout"] for entry in list_kb_versions(kb_dir)}

    assert {"nested_legacy", "root_legacy"} <= layouts


def test_optional_ingestion_schema_changes_signature_without_changing_legacy_default() -> None:
    import hashlib

    legacy = _signature()
    expected_payload = {
        "api_version": "",
        "base_url": "https://example.test/v1",
        "binding": "openai",
        "dimension": 1024,
        "model": "embed-a",
    }
    expected = hashlib.sha256(
        json.dumps(expected_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    schema_v2 = EmbeddingSignature(
        binding=legacy.binding,
        model=legacy.model,
        dimension=legacy.dimension,
        base_url=legacy.base_url,
        api_version=legacy.api_version,
        ingestion_schema_version="2",
        visual_mapping_version="1",
        description_prompt_version="2",
    )

    assert legacy.hash() == expected
    assert schema_v2.hash() != legacy.hash()


def test_schema_version_prevents_old_index_reuse_and_meta_is_readable(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    old_signature = _signature()
    new_signature = EmbeddingSignature(
        binding=old_signature.binding,
        model=old_signature.model,
        dimension=old_signature.dimension,
        base_url=old_signature.base_url,
        api_version=old_signature.api_version,
        ingestion_schema_version="2",
        visual_mapping_version="1",
        description_prompt_version="2",
    )
    old_version = kb_dir / "version-1"
    old_version.mkdir(parents=True)
    (old_version / "docstore.json").write_text("{}", encoding="utf-8")
    write_version_meta(kb_dir, old_signature, storage_dir=old_version)

    assert resolve_storage_dir_for_read(kb_dir, new_signature) is None
    assert resolve_storage_dir_for_write(kb_dir, new_signature) == kb_dir / "version-2"

    new_version = kb_dir / "version-2"
    (new_version / "docstore.json").write_text("{}", encoding="utf-8")
    write_version_meta(kb_dir, new_signature, storage_dir=new_version)
    meta = json.loads((new_version / "meta.json").read_text(encoding="utf-8"))

    assert meta["ingestion_schema_version"] == "2"
    assert meta["visual_mapping_version"] == "1"
    assert meta["description_prompt_version"] == "2"
    assert resolve_storage_dir_for_read(kb_dir, new_signature) == new_version


def test_schema_signature_never_falls_back_to_root_legacy_store(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    legacy = kb_dir / "llamaindex_storage"
    legacy.mkdir(parents=True)
    (legacy / "docstore.json").write_text("{}", encoding="utf-8")
    signature = EmbeddingSignature(
        binding="openai",
        model="embed-a",
        dimension=1024,
        base_url="https://example.test/v1",
        api_version="",
        ingestion_schema_version="2",
    )

    assert resolve_storage_dir_for_read(kb_dir, signature) is None
