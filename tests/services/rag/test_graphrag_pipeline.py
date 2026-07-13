"""Unit tests for the GraphRAG local RAG pipeline + provider routing.

GraphRAG itself is an optional dependency that is NOT installed in CI, so these
tests exercise everything that does not require the package (factory routing,
config bridge, ingestion, storage, lifecycle gating) directly, and stub the thin
``engine`` adapter to cover the index/search orchestration without graphrag.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest

from deeptutor.services.rag.factory import (
    GRAPHRAG_PROVIDER,
    get_pipeline,
    list_pipelines,
    normalize_provider_name,
)
from deeptutor.services.rag.index_versioning import resolve_storage_dir_for_read
from deeptutor.services.rag.pipelines.graphrag import config as gr_config
from deeptutor.services.rag.pipelines.graphrag import engine, ingestion, storage
from deeptutor.services.rag.pipelines.graphrag.pipeline import GraphRagPipeline, _context_to_sources

# --------------------------------------------------------------------------- #
# factory routing
# --------------------------------------------------------------------------- #


def test_factory_dispatches_graphrag_lazily(tmp_path) -> None:
    pipe = get_pipeline("graphrag", kb_base_dir=str(tmp_path))
    assert type(pipe).__name__ == "GraphRagPipeline"
    # Building the pipeline must NOT import the heavy optional dependency.
    assert "graphrag" not in sys.modules


def test_list_pipelines_includes_graphrag() -> None:
    entry = next(p for p in list_pipelines() if p["id"] == GRAPHRAG_PROVIDER)
    assert entry["requires_api_key"] is False
    # Not installed in the test env.
    assert entry["configured"] is False


def test_normalize_provider_keeps_graphrag() -> None:
    assert normalize_provider_name("graphrag") == "graphrag"
    assert normalize_provider_name("GraphRAG") == "graphrag"


def test_ragservice_routes_graphrag_from_metadata(tmp_path) -> None:
    from deeptutor.services.rag.service import RAGService

    kb = tmp_path / "kbg"
    kb.mkdir()
    (kb / "metadata.json").write_text(json.dumps({"rag_provider": "graphrag"}), encoding="utf-8")

    svc = RAGService(kb_base_dir=str(tmp_path))
    assert svc._resolve_provider("kbg") == "graphrag"


# --------------------------------------------------------------------------- #
# config bridge
# --------------------------------------------------------------------------- #


class _Cfg:
    def __init__(self, model, url, key, dim=3072):
        self.model = model
        self.effective_url = url
        self.base_url = None
        self.api_key = key
        self.dim = dim


def test_build_settings_bridges_models() -> None:
    settings = gr_config.build_settings(
        llm_cfg=_Cfg("gpt-4o-mini", "https://api.example.com/v1", "sk-llm"),
        embedding_cfg=_Cfg(
            "Qwen/Qwen3-Embedding-8B",
            "https://emb.example.com/v1",
            "sk-emb",
            dim=4096,
        ),
    )
    chat = settings["completion_models"]["default_completion_model"]
    emb = settings["embedding_models"]["default_embedding_model"]
    assert chat == {
        "model_provider": "openai",
        "model": "gpt-4o-mini",
        "auth_method": "api_key",
        "api_base": "https://api.example.com/v1",
        "api_key": "sk-llm",
    }
    assert emb["model"] == "Qwen/Qwen3-Embedding-8B"
    assert settings["input"]["type"] == "text"
    assert settings["vector_store"]["type"] == "lancedb"
    assert settings["vector_store"]["vector_size"] == 4096


def test_build_settings_requires_models() -> None:
    with pytest.raises(gr_config.GraphRagNotConfiguredError):
        gr_config.build_settings(
            llm_cfg=_Cfg("", "u", "k"),
            embedding_cfg=_Cfg("e", "u", "k"),
        )


def test_build_settings_requires_embedding_dimension() -> None:
    with pytest.raises(gr_config.GraphRagNotConfiguredError, match="known dimension"):
        gr_config.build_settings(
            llm_cfg=_Cfg("m", "u", "k"),
            embedding_cfg=_Cfg("e", "u", "k", dim=0),
        )


def test_local_api_key_placeholder_when_missing() -> None:
    settings = gr_config.build_settings(
        llm_cfg=_Cfg("m", "u", ""),
        embedding_cfg=_Cfg("e", "u", ""),
    )
    assert settings["completion_models"]["default_completion_model"]["api_key"] == (
        "sk-no-key-required"
    )


def test_write_settings_roundtrips(tmp_path) -> None:
    import yaml

    path = gr_config.write_settings(
        tmp_path,
        llm_cfg=_Cfg("m", "u", "k"),
        embedding_cfg=_Cfg("e", "u", "k"),
    )
    assert path.exists()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "completion_models" in loaded and "embedding_models" in loaded


@pytest.mark.parametrize(
    "given,expected",
    [
        ("hybrid", "local"),
        ("", "local"),
        (None, "local"),
        ("global", "global"),
        ("DRIFT", "drift"),
        ("basic", "basic"),
        ("nonsense", "local"),
    ],
)
def test_normalize_mode(given, expected) -> None:
    assert gr_config.normalize_mode(given) == expected


def test_is_graphrag_available_false_in_ci() -> None:
    assert gr_config.is_graphrag_available() is False


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


def test_storage_meta_and_has_output(tmp_path) -> None:
    root = tmp_path / "version-1"
    assert storage.has_output(root) is False
    storage.write_meta(root)
    meta = json.loads((root / storage.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["provider"] == "graphrag" and meta["signature"] == "graphrag"
    # has_output keys off the parquet artefacts, not the meta marker.
    assert storage.has_output(root) is False
    storage.output_dir(root).mkdir(parents=True, exist_ok=True)
    (storage.output_dir(root) / "entities.parquet").write_bytes(b"")
    assert storage.has_output(root) is True


# --------------------------------------------------------------------------- #
# ingestion
# --------------------------------------------------------------------------- #


def test_ingestion_writes_text_and_skips_noise(tmp_path) -> None:
    root = tmp_path / "root"
    txt = tmp_path / "notes.txt"
    txt.write_text("hello graph world", encoding="utf-8")
    md = tmp_path / "guide.md"
    md.write_text("# Title\nbody", encoding="utf-8")
    empty = tmp_path / "empty.txt"
    empty.write_text("   ", encoding="utf-8")
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")

    count = asyncio.run(ingestion.prepare_input([str(txt), str(md), str(empty), str(img)], root))

    assert count == 2
    written = sorted(p.name for p in storage.input_dir(root).glob("*.txt"))
    assert written == ["guide.txt", "notes.txt"]


def test_ingestion_uses_active_parse_service_for_parser_files(tmp_path, monkeypatch) -> None:
    from deeptutor.services import parsing

    root = tmp_path / "root"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    calls: list[Path] = []

    class _Parsed:
        markdown = "parsed by configured engine"
        blocks: list[dict] = []

    class _ParseService:
        def parse(self, path: Path):
            calls.append(path)
            return _Parsed()

    monkeypatch.setattr(parsing, "get_parse_service", lambda: _ParseService())

    count = asyncio.run(ingestion.prepare_input([str(pdf)], root))

    assert count == 1
    assert calls == [pdf]
    assert (storage.input_dir(root) / "paper.txt").read_text(encoding="utf-8") == (
        "parsed by configured engine"
    )


def test_ingestion_avoids_name_collisions(tmp_path) -> None:
    root = tmp_path / "root"
    a = tmp_path / "a" / "doc.txt"
    b = tmp_path / "b" / "doc.txt"
    for p in (a, b):
        p.parent.mkdir(parents=True)
        p.write_text("content", encoding="utf-8")

    count = asyncio.run(ingestion.prepare_input([str(a), str(b)], root))
    assert count == 2
    names = sorted(p.name for p in storage.input_dir(root).glob("*.txt"))
    assert names == ["doc.txt", "doc_1.txt"]


# --------------------------------------------------------------------------- #
# pipeline lifecycle (engine stubbed)
# --------------------------------------------------------------------------- #


def _force_available(monkeypatch, available: bool = True) -> None:
    monkeypatch.setattr(gr_config, "is_graphrag_available", lambda: available)


def _stub_build(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def fake_build(root_dir, *, is_update=False):
        calls.append({"root": str(root_dir), "is_update": is_update})
        out = storage.output_dir(Path(root_dir))
        out.mkdir(parents=True, exist_ok=True)
        (out / "entities.parquet").write_bytes(b"")

    monkeypatch.setattr(engine, "build", fake_build)

    # initialize() -> write_settings() resolves the active chat + embedding
    # models from the catalog; CI has none configured, so pin fakes here so the
    # settings.yaml write succeeds. The build_settings <-> catalog bridge itself
    # is covered by the test_build_settings_* tests above.
    monkeypatch.setattr(
        "deeptutor.services.config.resolve_llm_runtime_config",
        lambda: _Cfg("gpt-4o-mini", "https://llm.test/v1", "sk-llm"),
    )
    monkeypatch.setattr(
        "deeptutor.services.embedding.get_embedding_config",
        lambda: _Cfg("emb-model", "https://emb.test/v1", "sk-emb"),
    )
    return calls


def test_initialize_requires_graphrag(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, False)
    txt = tmp_path / "a.txt"
    txt.write_text("x", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    with pytest.raises(gr_config.GraphRagNotAvailableError):
        asyncio.run(pipe.initialize("kb", [str(txt)]))


def test_initialize_orchestrates_index(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    calls = _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("graph content", encoding="utf-8")

    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    ok = asyncio.run(pipe.initialize("kb", [str(txt)]))

    assert ok is True
    assert calls == [{"root": calls[0]["root"], "is_update": False}]
    root = Path(calls[0]["root"])
    assert (root / gr_config.SETTINGS_FILENAME).exists()
    assert list(storage.input_dir(root).glob("*.txt"))
    assert (root / storage.META_FILENAME).exists()


def test_initialize_no_text_returns_false(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    calls = _stub_build(monkeypatch)
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")

    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    ok = asyncio.run(pipe.initialize("kb", [str(img)]))

    assert ok is False
    assert calls == []  # build never runs without extractable text


def test_add_documents_runs_update_when_indexed(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    calls = _stub_build(monkeypatch)
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))

    a = tmp_path / "a.txt"
    a.write_text("one", encoding="utf-8")
    asyncio.run(pipe.initialize("kb", [str(a)]))

    b = tmp_path / "b.txt"
    b.write_text("two", encoding="utf-8")
    ok = asyncio.run(pipe.add_documents("kb", [str(b)]))

    assert ok is True
    assert calls[-1]["is_update"] is True


def test_search_needs_reindex_without_output(tmp_path) -> None:
    res = asyncio.run(GraphRagPipeline(kb_base_dir=str(tmp_path)).search("q", "missing"))
    assert res["needs_reindex"] is True
    assert res["provider"] == "graphrag"
    assert res["sources"] == []


def test_search_not_configured_when_unavailable(tmp_path, monkeypatch) -> None:
    # Index exists on disk, but the package is gone (e.g. uninstalled).
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))

    _force_available(monkeypatch, False)
    res = asyncio.run(pipe.search("q", "kb"))
    assert res["error_type"] == "not_configured"
    assert res["provider"] == "graphrag"


def test_search_happy_path(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))

    seen = {}

    async def fake_search(root_dir, query, mode):
        seen["mode"] = mode
        return "THE ANSWER", {"sources": [{"id": "u1", "text": "grounded ctx"}]}

    monkeypatch.setattr(engine, "search", fake_search)

    res = asyncio.run(pipe.search("what?", "kb"))
    assert res["answer"] == "THE ANSWER"
    assert res["content"] == "THE ANSWER"
    assert res["mode"] == "local"  # default
    assert res["sources"][0]["content"] == "grounded ctx"
    assert res["sources"][0]["chunk_id"] == "u1"


def test_search_mode_from_kb_config(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))

    (tmp_path / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {"kb": {"search_mode": "global"}}}),
        encoding="utf-8",
    )

    async def fake_search(root_dir, query, mode):
        return f"mode={mode}", {}

    monkeypatch.setattr(engine, "search", fake_search)
    res = asyncio.run(pipe.search("q", "kb"))
    assert res["mode"] == "global"


def test_delete_removes_kb_dir(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))
    assert (tmp_path / "kb").exists()

    ok = asyncio.run(pipe.delete("kb"))
    assert ok is True
    assert not (tmp_path / "kb").exists()


def test_context_to_sources_prefers_concrete_records() -> None:
    sources = _context_to_sources(
        {
            "sources": [{"id": "u1", "text": "unit text"}],
            "reports": [{"title": "Community 0", "content": "summary"}],
        }
    )
    assert len(sources) == 1
    assert sources[0]["chunk_id"] == "u1"
    assert sources[0]["content"] == "unit text"


# --------------------------------------------------------------------------- #
# knowledge-router gating
# --------------------------------------------------------------------------- #


def test_router_blocks_graphrag_when_unavailable(monkeypatch) -> None:
    from fastapi import HTTPException

    from deeptutor.api.routers import knowledge

    monkeypatch.setattr(gr_config, "is_graphrag_available", lambda: False)
    with pytest.raises(HTTPException) as exc:
        knowledge._assert_provider_ready(GRAPHRAG_PROVIDER)
    assert exc.value.status_code == 400
