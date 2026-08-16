from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.rag.index_probe import (
    _llamaindex_doc_count,
    has_ready_provider_index,
    inspect_kb_versions,
    inspect_provider_index,
    inspect_provider_version,
    provider_failure_summary,
)
from deeptutor.services.rag.pipelines.graphrag import storage as graphrag_storage
from deeptutor.services.rag.pipelines.pageindex import storage as pageindex_storage


def _write_meta(version_dir: Path, *, provider: str, signature: str | None = None) -> None:
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "version": version_dir.name,
                "provider": provider,
                "signature": signature or provider,
                "layout": "flat",
            }
        ),
        encoding="utf-8",
    )


def test_llamaindex_requires_real_storage_files(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )

    probe = inspect_provider_index("llamaindex", version_dir)

    assert probe.ready is False
    assert "index_store.json" in probe.failure_summary
    assert probe.doc_count == 1

    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    probe = inspect_provider_index("llamaindex", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_kb_versions_overrule_fake_llamaindex_ready_marker(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    _write_meta(version_dir, provider="llamaindex", signature="sig")

    versions = inspect_kb_versions(tmp_path, "llamaindex")

    assert versions[0]["ready"] is False
    assert "index_store.json" in versions[0]["failure_summary"]
    assert has_ready_provider_index(tmp_path, "llamaindex") is False
    assert "index_store.json" in provider_failure_summary(tmp_path, "llamaindex")


def test_pageindex_ready_requires_doc_ids(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="pageindex")

    probe = inspect_provider_index("pageindex", version_dir)
    assert probe.ready is False

    manifest = pageindex_storage.read_manifest(version_dir)
    pageindex_storage.upsert_doc(manifest, "lesson.pdf", "doc-123")
    pageindex_storage.write_manifest(version_dir, manifest)

    probe = inspect_provider_index("pageindex", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_graphrag_ready_requires_core_output_table(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="graphrag")

    probe = inspect_provider_index("graphrag", version_dir)
    assert probe.ready is False
    assert "parquet" in probe.failure_summary

    out = graphrag_storage.output_dir(version_dir)
    out.mkdir()
    (out / "entities.parquet").write_bytes(b"placeholder")

    probe = inspect_provider_index("graphrag", version_dir)
    assert probe.ready is True
    assert probe.diagnostics["output_tables"] == ["entities"]


def test_lightrag_uses_doc_status_as_truth(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="lightrag")
    (version_dir / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {
                    "status": "failed",
                    "file_path": "bad.docx",
                    "error_msg": "parse failed",
                    "chunks_list": [],
                }
            }
        ),
        encoding="utf-8",
    )

    probe = inspect_provider_index("lightrag", version_dir)
    assert probe.ready is False
    assert "bad.docx" in probe.failure_summary

    (version_dir / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {
                    "status": "processed",
                    "file_path": "ok.docx",
                    "chunks_list": ["chunk-1"],
                }
            }
        ),
        encoding="utf-8",
    )
    probe = inspect_provider_index("lightrag", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_provider_mismatch_is_not_ready(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="lightrag")
    entry = {
        "provider": "lightrag",
        "signature": "lightrag",
        "ready": True,
        "storage_path": str(version_dir),
    }

    probe = inspect_provider_version(entry, "llamaindex")

    assert probe.ready is False
    assert probe.diagnostics["provider_mismatch"] is True


def test_llamaindex_doc_count_cached_until_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated probes must not re-parse docstore.json (issue #859)."""
    from deeptutor.services.rag.index_probe import _read_json

    docstore = tmp_path / "docstore.json"
    docstore.write_text(
        json.dumps({"docstore/data": {"doc-1": {}, "doc-2": {}}}),
        encoding="utf-8",
    )

    real_read = _read_json
    reads: list[str] = []

    def counting_read(path: Path) -> dict[str, Any] | None:
        reads.append(str(path))
        return real_read(path)

    monkeypatch.setattr("deeptutor.services.rag.index_probe._read_json", counting_read)

    assert _llamaindex_doc_count(docstore) == 2
    # Second probe on an unchanged file must be served from the cache.
    assert _llamaindex_doc_count(docstore) == 2
    assert reads == [str(docstore)]

    # A real file change must invalidate the cache entry.
    docstore.write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )
    assert _llamaindex_doc_count(docstore) == 1
    assert reads == [str(docstore), str(docstore)]


def test_llamaindex_doc_count_missing_file_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing docstore must not poison the cache for a later-created file."""
    from deeptutor.services.rag.index_probe import _read_json

    docstore = tmp_path / "docstore.json"

    real_read = _read_json
    reads: list[str] = []

    def counting_read(path: Path) -> dict[str, Any] | None:
        reads.append(str(path))
        return real_read(path)

    monkeypatch.setattr("deeptutor.services.rag.index_probe._read_json", counting_read)

    assert _llamaindex_doc_count(docstore) is None
    # A missing docstore short-circuits on stat() — no parse is attempted, and
    # no cache entry is created that could shadow a later-created file.
    assert reads == []
    docstore.write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )
    assert _llamaindex_doc_count(docstore) == 1
    assert reads == [str(docstore)]


def test_provider_failure_summary_reuses_precomputed_versions(tmp_path: Path) -> None:
    """Pre-annotated versions must not trigger another on-disk scan (#859)."""
    versions = [
        {"storage_path": str(tmp_path / "version-1"), "ready": True},
        {
            "storage_path": str(tmp_path / "version-2"),
            "ready": False,
            "failure_summary": "Missing LlamaIndex docstore.json.",
        },
    ]
    # Nothing exists on disk under tmp_path; the precomputed list is the only
    # source of failure text and must be honored without a rescan.
    assert provider_failure_summary(tmp_path, "llamaindex", versions=versions) == (
        "Missing LlamaIndex docstore.json."
    )
