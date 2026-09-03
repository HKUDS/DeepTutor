"""Settings are wired directly to the pinned native LightRAG constructor."""

from __future__ import annotations

import importlib.util
from pathlib import Path

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
    monkeypatch.setattr(engine, "_require_exact_version", lambda: None)
    monkeypatch.setattr(engine, "_register_parser", lambda: None)
    monkeypatch.setattr(engine, "_controlled_class", lambda: _NativeLightRag)
    monkeypatch.setattr(engine, "build_llm_model_func", lambda **_kwargs: "llm")
    monkeypatch.setattr(engine, "build_embedding_func", lambda **_kwargs: "embedding")
    monkeypatch.setattr(engine, "lightrag_llm_selection_from_settings", lambda: None)


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
    assert "role_llm_configs" not in rag.kwargs


def test_dedicated_selection_reaches_llm_but_not_embedding_adapter(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_build(monkeypatch)
    selection = {"profile_id": "profile-1", "model_id": "model-1"}
    monkeypatch.setattr(engine, "lightrag_llm_selection_from_settings", lambda: selection)
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
    monkeypatch.setattr(engine, "indexing_kwargs_from_settings", dict)
    monkeypatch.setattr(engine, "constructor_kwargs_from_settings", dict)

    engine.build_rag(tmp_path)

    assert llm_calls == [{"llm_selection": selection}]
    assert embedding_calls == [{}]


def test_vlm_role_is_only_configured_when_enabled(monkeypatch, tmp_path: Path) -> None:
    _stub_build(monkeypatch)
    monkeypatch.setattr(engine, "build_vision_model_func", lambda **_kwargs: "vision")
    monkeypatch.setattr(engine, "indexing_kwargs_from_settings", dict)
    monkeypatch.setattr(engine, "constructor_kwargs_from_settings", dict)

    rag = engine.build_rag(tmp_path, enable_vlm=True)

    role = rag.kwargs["role_llm_configs"]["vlm"]
    assert role.func == "vision"
    assert rag.kwargs["vlm_process_enable"] is True
