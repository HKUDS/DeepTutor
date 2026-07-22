"""Probing and resolving externally-linked knowledge bases.

A *linked* KB points at a self-contained engine index the user built elsewhere.
These tests cover the three load-bearing pieces: the storage-dir seam
(:func:`resolve_kb_dir`), the connect-time probe (ready index? right engine?
compatible embedding?), and the optional path-jail guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.rag import embedding_signature as emb_sig
from deeptutor.services.rag.index_versioning import EmbeddingSignature
from deeptutor.services.rag.kb_paths import resolve_kb_dir
from deeptutor.services.rag.linked_kb import (
    assert_path_allowed,
    probe_linked_folder,
    provider_is_linkable,
)

_SIG = EmbeddingSignature(
    binding="openai", model="text-embedding-3-small", dimension=1536, base_url="u", api_version=""
)


def _write_llamaindex_index(root: Path, *, signature: str, docs: int = 0) -> None:
    version = root / "version-1"
    version.mkdir(parents=True)
    (version / "docstore.json").write_text(
        json.dumps({"docstore/data": {f"doc{i}": {} for i in range(docs)}}),
        encoding="utf-8",
    )
    (version / "index_store.json").write_text("{}", encoding="utf-8")
    (version / "meta.json").write_text(
        json.dumps(
            {
                "version": "version-1",
                "signature": signature,
                "layout": "flat",
                "embedding_model": _SIG.model,
            }
        ),
        encoding="utf-8",
    )
    if docs:
        raw = root / "raw"
        raw.mkdir()
        for i in range(docs):
            (raw / f"doc{i}.md").write_text("x", encoding="utf-8")


def test_provider_is_linkable_excludes_pageindex() -> None:
    assert provider_is_linkable("llamaindex")
    assert provider_is_linkable("graphrag")
    assert provider_is_linkable("lightrag")
    assert not provider_is_linkable("pageindex")


def test_resolve_kb_dir_points_at_external_for_linked(tmp_path: Path) -> None:
    base = tmp_path / "kbs"
    base.mkdir()
    external = tmp_path / "external_kb"
    external.mkdir()
    (base / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "linked": {"type": "linked", "external_path": str(external)},
                    "plain": {"path": "plain"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert resolve_kb_dir(str(base), "linked") == external
    assert resolve_kb_dir(str(base), "plain") == base / "plain"
    # Unknown KB falls back to the conventional layout.
    assert resolve_kb_dir(str(base), "missing") == base / "missing"


def test_probe_rejects_pageindex(tmp_path: Path) -> None:
    result = probe_linked_folder(str(tmp_path), "pageindex")
    assert not result.ok
    assert result.error and "cloud" in result.error.lower()


def test_probe_errors_when_no_index(tmp_path: Path) -> None:
    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert not result.ok
    assert result.error


def test_probe_finds_ready_llamaindex_index(tmp_path: Path, monkeypatch) -> None:
    _write_llamaindex_index(tmp_path, signature=_SIG.hash(), docs=3)
    # Current embedding matches what the index was built with.
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert result.ok
    assert result.version == "version-1"
    assert result.doc_count == 3
    assert result.embedding.compatible is True
    assert result.warnings == []


def test_probe_warns_on_embedding_mismatch(tmp_path: Path, monkeypatch) -> None:
    _write_llamaindex_index(tmp_path, signature="0000different0000")
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: _SIG)

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    # A mismatch is a warning, not a hard block — the user may switch models.
    assert result.ok
    assert result.embedding.compatible is False
    assert result.warnings


def test_probe_unverifiable_embedding_is_a_warning(tmp_path: Path, monkeypatch) -> None:
    _write_llamaindex_index(tmp_path, signature=_SIG.hash())
    # No embedding configured → can't verify compatibility.
    monkeypatch.setattr(emb_sig, "signature_from_embedding_config", lambda: None)

    result = probe_linked_folder(str(tmp_path), "llamaindex")
    assert result.ok
    assert result.embedding.compatible is None
    assert result.warnings


def test_probe_rejects_wrong_engine(tmp_path: Path) -> None:
    # A llamaindex-style index (docstore.json) probed as lightrag should fail:
    # lightrag's ready-marker globs won't match, so no ready version is found.
    _write_llamaindex_index(tmp_path, signature=_SIG.hash())
    result = probe_linked_folder(str(tmp_path), "lightrag")
    assert not result.ok


def test_assert_path_allowed_default_permissive(tmp_path: Path) -> None:
    folder = tmp_path / "vault"
    folder.mkdir()
    assert assert_path_allowed(str(folder)) == folder.resolve()


def test_assert_path_allowed_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        assert_path_allowed(str(tmp_path / "nope"))


def test_assert_path_allowed_enforces_allowlist(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("DEEPTUTOR_LINKED_FOLDER_ROOTS", str(allowed))

    inside = allowed / "kb"
    inside.mkdir()
    assert assert_path_allowed(str(inside)) == inside.resolve()
    with pytest.raises(ValueError):
        assert_path_allowed(str(outside))
