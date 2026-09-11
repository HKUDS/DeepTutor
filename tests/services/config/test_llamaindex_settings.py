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
    assert loaded["vector_index_type"] == "flat"
    assert loaded["hnsw_m"] == 32
    assert loaded["hnsw_ef_construction"] == 200
    assert loaded["hnsw_ef_search"] == 64
    assert loaded["reranker_model"] == ""
    assert loaded["rerank_top_k"] == 50
    assert loaded["chunk_size"] == 512
    assert loaded["chunk_overlap"] == 50
    assert loaded["image_description_concurrency"] == 4
    assert loaded["image_description_timeout_seconds"] == 60


def test_llamaindex_roundtrip(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_llamaindex(
        {
            "retrieval_profile": "vector",
            "top_k": 8,
            "reranker_model": "  BAAI/bge-reranker-base  ",
            "rerank_top_k": 25,
            "chunk_size": 1024,
            "chunk_overlap": 0,
            "image_description_concurrency": 8,
            "image_description_timeout_seconds": 120,
        }
    )

    loaded = svc.load_llamaindex(include_process_overrides=False)
    assert loaded["retrieval_profile"] == "vector"
    assert loaded["top_k"] == 8
    assert loaded["reranker_model"] == "BAAI/bge-reranker-base"
    assert loaded["rerank_top_k"] == 25
    assert loaded["chunk_size"] == 1024
    assert loaded["chunk_overlap"] == 0
    assert loaded["image_description_concurrency"] == 8
    assert loaded["image_description_timeout_seconds"] == 120
    # Its own file beside the other per-feature settings.
    assert (tmp_path / "llamaindex.json").exists()


def test_llamaindex_clamps_out_of_range(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_llamaindex(
        {
            "retrieval_profile": "nonsense",
            "top_k": 999,
            "bm25_top_k_multiplier": 0,
            "vector_index_type": "hnsw",
            "hnsw_m": 999,
            "hnsw_ef_construction": 1,
            "hnsw_ef_search": 0,
            "reranker_model": "x" * 250,
            "rerank_top_k": 999,
            "chunk_size": 8,
            "chunk_overlap": 99999,
            "image_description_concurrency": 999,
            "image_description_timeout_seconds": 0,
        }
    )
    loaded = svc.load_llamaindex(include_process_overrides=False)
    # Unknown profile falls back to the safe default.
    assert loaded["retrieval_profile"] == "hybrid"
    assert loaded["top_k"] == 50
    assert loaded["bm25_top_k_multiplier"] == 1
    assert loaded["vector_index_type"] == "hnsw"
    assert loaded["hnsw_m"] == 64
    assert loaded["hnsw_ef_construction"] == 16
    assert loaded["hnsw_ef_search"] == 1
    assert len(loaded["reranker_model"]) == 200
    assert loaded["rerank_top_k"] == 100
    assert loaded["chunk_size"] == 64
    # Overlap is clamped below the chunk size so chunking never degenerates.
    assert loaded["chunk_overlap"] == 63
    assert loaded["image_description_concurrency"] == 16
    assert loaded["image_description_timeout_seconds"] == 5


def test_llamaindex_profile_env_override(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    svc.save_llamaindex({"retrieval_profile": "vector"})

    overridden = RuntimeSettingsService(tmp_path, process_env={"RAG_RETRIEVAL_PROFILE": "hybrid"})
    loaded = overridden.load_llamaindex(include_process_overrides=True)
    assert loaded["retrieval_profile"] == "hybrid"


def test_llamaindex_unknown_vector_index_falls_back_to_flat(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    saved = svc.save_llamaindex({"vector_index_type": "ivf"})

    assert saved["vector_index_type"] == "flat"


def test_chunk_geometry_preserves_zero_overlap(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import config

    monkeypatch.setattr(
        config,
        "_load_runtime_settings",
        lambda: {"chunk_size": 512, "chunk_overlap": 0},
    )

    assert config.chunk_geometry() == (512, 0)


def test_vector_index_config_uses_runtime_settings(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import config

    monkeypatch.setattr(
        config,
        "_load_runtime_settings",
        lambda: {
            "vector_index_type": "HNSW",
            "hnsw_m": 24,
            "hnsw_ef_construction": 128,
            "hnsw_ef_search": 48,
        },
    )

    selected = config.vector_index_config_from_settings()
    assert selected.type == "hnsw"
    assert selected.hnsw_m == 24
    assert selected.hnsw_ef_construction == 128
    assert selected.hnsw_ef_search == 48


def test_image_description_limits_use_runtime_settings(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import config

    monkeypatch.setattr(
        config,
        "_load_runtime_settings",
        lambda: {
            "image_description_concurrency": 7,
            "image_description_timeout_seconds": 90,
        },
    )

    assert config.image_description_limits() == (7, 90.0)


def test_retrieval_config_uses_reranker_settings(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import config

    monkeypatch.setattr(
        config,
        "_load_runtime_settings",
        lambda: {
            "reranker_model": " BAAI/bge-reranker-base ",
            "rerank_top_k": 25,
        },
    )

    selected = config.retrieval_config_from_settings()

    assert selected.reranker_model == "BAAI/bge-reranker-base"
    assert selected.rerank_candidate_top_k(5) == 25
    assert selected.rerank_candidate_top_k(40) == 40
