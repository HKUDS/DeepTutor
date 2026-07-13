"""LlamaIndex engine knobs stored in RuntimeSettingsService."""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.runtime_settings import RuntimeSettingsService


def test_llamaindex_defaults_when_absent(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    loaded = svc.load_llamaindex(include_process_overrides=False)
    assert loaded["retrieval_profile"] == "hybrid"
    assert loaded["top_k"] == 5
    assert loaded["vector_top_k_multiplier"] == 2
    assert loaded["bm25_top_k_multiplier"] == 2
    assert loaded["chunk_size"] == 512
    assert loaded["chunk_overlap"] == 50


def test_llamaindex_roundtrip(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_llamaindex(
        {"retrieval_profile": "vector", "top_k": 8, "chunk_size": 1024, "chunk_overlap": 0}
    )

    loaded = svc.load_llamaindex(include_process_overrides=False)
    assert loaded["retrieval_profile"] == "vector"
    assert loaded["top_k"] == 8
    assert loaded["chunk_size"] == 1024
    assert loaded["chunk_overlap"] == 0
    # Its own file beside the other per-feature settings.
    assert (tmp_path / "llamaindex.json").exists()


def test_llamaindex_clamps_out_of_range(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_llamaindex(
        {
            "retrieval_profile": "nonsense",
            "top_k": 999,
            "bm25_top_k_multiplier": 0,
            "chunk_size": 8,
            "chunk_overlap": 99999,
        }
    )
    loaded = svc.load_llamaindex(include_process_overrides=False)
    # Unknown profile falls back to the safe default.
    assert loaded["retrieval_profile"] == "hybrid"
    assert loaded["top_k"] == 50
    assert loaded["bm25_top_k_multiplier"] == 1
    assert loaded["chunk_size"] == 64
    # Overlap is clamped below the chunk size so chunking never degenerates.
    assert loaded["chunk_overlap"] == 63


def test_llamaindex_profile_env_override(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_llamaindex({"retrieval_profile": "vector"})

    overridden = RuntimeSettingsService(tmp_path, process_env={"RAG_RETRIEVAL_PROFILE": "hybrid"})
    loaded = overridden.load_llamaindex(include_process_overrides=True)
    assert loaded["retrieval_profile"] == "hybrid"


def test_chunk_geometry_preserves_zero_overlap(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import config

    monkeypatch.setattr(
        config,
        "_load_runtime_settings",
        lambda: {"chunk_size": 512, "chunk_overlap": 0},
    )

    assert config.chunk_geometry() == (512, 0)
