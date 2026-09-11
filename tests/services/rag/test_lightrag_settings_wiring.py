"""Settings are wired directly to the pinned native LightRAG constructor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import types

import pytest

from deeptutor.services.rag.pipelines.lightrag import engine

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("lightrag") is None,
    reason="requires the optional rag-lightrag extra",
)


class _NativeLightRag:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


def _stub_build(monkeypatch) -> None:
    query_config = types.SimpleNamespace(binding="openai")
    monkeypatch.setattr(engine, "_require_exact_version", lambda: None)
    monkeypatch.setattr(engine, "_register_parser", lambda: None)
    monkeypatch.setattr(engine, "_controlled_class", lambda: _NativeLightRag)
    monkeypatch.setattr(engine, "build_llm_model_func", lambda **_kwargs: "llm")
    monkeypatch.setattr(engine, "build_embedding_func", lambda **_kwargs: "embedding")
    monkeypatch.setattr(engine, "resolve_lightrag_query_llm_config", lambda: query_config)
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.indexing_policy.cache_identity_for_config",
        lambda _config: "query-fingerprint",
    )


def test_native_constructor_receives_every_supported_knob(monkeypatch, tmp_path: Path) -> None:
    _stub_build(monkeypatch)
    monkeypatch.setattr(
        engine, "indexing_kwargs_from_settings", lambda: {"max_parallel_parse_native": 4}
    )
    monkeypatch.setattr(
        engine,
        "constructor_kwargs_from_settings",
        lambda: {"llm_model_max_async": 8, "entity_extract_max_gleaning": 2},
    )

    rag = engine.build_rag(tmp_path)

    assert rag.kwargs["working_dir"] == str(tmp_path)
    assert rag.kwargs["workspace"] == engine.workspace_for(tmp_path)
    assert rag.kwargs["llm_model_func"] == "llm"
    assert rag.kwargs["embedding_func"] == "embedding"
    assert rag.kwargs["auto_manage_storages_states"] is False
    assert rag.kwargs["max_parallel_parse_native"] == 4
    assert rag.kwargs["llm_model_max_async"] == 8
    assert rag.kwargs["entity_extract_max_gleaning"] == 2
    assert rag.kwargs["vlm_process_enable"] is False
    assert rag.kwargs["llm_model_name"] == "query-fingerprint"
    assert set(rag.kwargs["role_llm_configs"]) == {"keyword", "query"}


def test_global_dedicated_selection_drives_query_roles_not_embedding(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_build(monkeypatch)
    query_config = types.SimpleNamespace(binding="dedicated")
    llm_calls: list[dict[str, object]] = []
    embedding_calls: list[dict[str, object]] = []

    def build_llm(**kwargs):
        llm_calls.append(kwargs)
        return "llm"

    def build_embedding(**kwargs):
        embedding_calls.append(kwargs)
        return "embedding"

    monkeypatch.setattr(engine, "build_llm_model_func", build_llm)
    monkeypatch.setattr(engine, "build_embedding_func", build_embedding)
    monkeypatch.setattr(engine, "resolve_lightrag_query_llm_config", lambda: query_config)
    monkeypatch.setattr(engine, "indexing_kwargs_from_settings", dict)
    monkeypatch.setattr(engine, "constructor_kwargs_from_settings", dict)

    engine.build_rag(tmp_path)

    assert llm_calls == [{"llm_config": query_config}]
    assert embedding_calls == [{}]


def test_vlm_role_is_only_configured_when_enabled(monkeypatch, tmp_path: Path) -> None:
    _stub_build(monkeypatch)
    monkeypatch.setattr(engine, "build_vision_model_func", lambda **_kwargs: "vision")
    monkeypatch.setattr(engine, "indexing_kwargs_from_settings", dict)
    monkeypatch.setattr(engine, "constructor_kwargs_from_settings", dict)

    snapshot = types.SimpleNamespace(
        config=types.SimpleNamespace(binding="openai"),
        owner=object(),
        descriptor={"endpoint": "https://example.test/v1"},
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.indexing_policy.cache_identity",
        lambda _snapshot: "snapshot-fingerprint",
    )

    rag = engine.build_rag(tmp_path, enable_vlm=True, indexing_snapshot=snapshot)

    role = rag.kwargs["role_llm_configs"]["vlm"]
    assert role.func == "vision"
    assert rag.kwargs["vlm_process_enable"] is True


def test_snapshot_routes_only_extract_and_vlm_while_query_base_stays_global(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_build(monkeypatch)
    monkeypatch.setattr(engine, "indexing_kwargs_from_settings", dict)
    monkeypatch.setattr(engine, "constructor_kwargs_from_settings", dict)
    llm_calls: list[dict[str, object]] = []
    vision_calls: list[dict[str, object]] = []

    def build_llm(**kwargs):
        llm_calls.append(kwargs)
        return f"llm-{len(llm_calls)}"

    def build_vision(**kwargs):
        vision_calls.append(kwargs)
        return "vision"

    monkeypatch.setattr(engine, "build_llm_model_func", build_llm)
    monkeypatch.setattr(engine, "build_vision_model_func", build_vision)
    snapshot = types.SimpleNamespace(
        config=types.SimpleNamespace(binding="openai"),
        owner=object(),
        descriptor={"endpoint": "https://example.test/v1"},
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.indexing_policy.cache_identity",
        lambda _snapshot: "snapshot-fingerprint",
    )

    rag = engine.build_rag(tmp_path, enable_vlm=True, indexing_snapshot=snapshot)

    assert "llm_config" in llm_calls[0]
    assert llm_calls[1] == {"llm_config": snapshot.config, "owner": snapshot.owner}
    assert vision_calls == [{"llm_config": snapshot.config, "owner": snapshot.owner}]
    assert rag.kwargs["llm_model_func"] == "llm-1"
    assert rag.kwargs["role_llm_configs"]["extract"].func == "llm-2"
    assert rag.kwargs["role_llm_configs"]["vlm"].func == "vision"
    assert rag.kwargs["role_llm_configs"]["keyword"].func == "llm-1"
    assert rag.kwargs["role_llm_configs"]["query"].func == "llm-1"
