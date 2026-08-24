"""The LightRAG settings knobs must not break older RAG-Anything installs.

``max_concurrent_files`` rides on ``RAGAnythingConfig`` and
``llm_model_max_async`` / ``entity_extract_max_gleaning`` ride on RAG-Anything's
``lightrag_kwargs`` passthrough — a parameter that only exists from ~1.2.5,
while the supported range starts at 1.0.1. Passing it blind raised TypeError
and took the whole engine down, so the wiring asks the installed class first.

raganything is an optional extra and is absent from CI, so these tests exercise
``build_rag`` against stand-in classes with each constructor shape.
"""

from __future__ import annotations

from pathlib import Path
import sys
import types
from typing import Any

import pytest

from deeptutor.services.rag.pipelines.lightrag import engine as engine_module


class _ModernConfig:
    """RAG-Anything >= 1.2.5: config takes the batch knob."""

    def __init__(self, working_dir: str, max_concurrent_files: int = 1) -> None:
        self.working_dir = working_dir
        self.max_concurrent_files = max_concurrent_files


class _LegacyConfig:
    """RAG-Anything 1.0.x: no batch knob at all."""

    def __init__(self, working_dir: str) -> None:
        self.working_dir = working_dir


class _ModernRag:
    """RAG-Anything >= 1.2.5: exposes the lightrag_kwargs passthrough."""

    def __init__(
        self,
        config: Any,
        llm_model_func: Any,
        vision_model_func: Any,
        embedding_func: Any,
        lightrag_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.lightrag_kwargs = lightrag_kwargs
        self.set_content_source_func = None


class _LegacyRag:
    """RAG-Anything 1.0.x: no passthrough."""

    def __init__(
        self,
        config: Any,
        llm_model_func: Any,
        vision_model_func: Any,
        embedding_func: Any,
    ) -> None:
        self.config = config
        self.lightrag_kwargs = None
        self.set_content_source_func = None


@pytest.fixture
def fake_raganything(monkeypatch: pytest.MonkeyPatch):
    """Install a stand-in ``raganything`` module with the given class shapes."""

    def install(rag_cls: type, config_cls: type) -> None:
        module = types.ModuleType("raganything")
        module.RAGAnything = rag_cls  # type: ignore[attr-defined]
        module.RAGAnythingConfig = config_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "raganything", module)

    return install


@pytest.fixture(autouse=True)
def _stub_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("build_llm_model_func", "build_vision_model_func", "build_embedding_func"):
        monkeypatch.setattr(engine_module, name, lambda **_kwargs: lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        engine_module, "indexing_kwargs_from_settings", lambda: {"max_concurrent_files": 4}
    )
    monkeypatch.setattr(
        engine_module,
        "lightrag_kwargs_from_settings",
        lambda: {"llm_model_max_async": 8, "entity_extract_max_gleaning": 2},
    )


def test_modern_raganything_receives_every_knob(fake_raganything, tmp_path: Path) -> None:
    fake_raganything(_ModernRag, _ModernConfig)

    rag = engine_module.build_rag(tmp_path)

    assert rag.config.max_concurrent_files == 4
    assert rag.lightrag_kwargs == {"llm_model_max_async": 8, "entity_extract_max_gleaning": 2}


def test_legacy_raganything_still_builds(
    fake_raganything, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The knobs are dropped with a warning rather than raising TypeError."""
    fake_raganything(_LegacyRag, _LegacyConfig)

    with caplog.at_level("WARNING"):
        rag = engine_module.build_rag(tmp_path)

    assert rag.lightrag_kwargs is None
    assert not hasattr(rag.config, "max_concurrent_files")
    assert "max_concurrent_files" in caplog.text
    assert "lightrag_kwargs" in caplog.text


def test_mixed_versions_drop_only_the_unsupported_knob(fake_raganything, tmp_path: Path) -> None:
    fake_raganything(_LegacyRag, _ModernConfig)

    rag = engine_module.build_rag(tmp_path)

    assert rag.config.max_concurrent_files == 4
    assert rag.lightrag_kwargs is None


def test_no_configured_knobs_passes_nothing_extra(
    fake_raganything, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "indexing_kwargs_from_settings", dict)
    monkeypatch.setattr(engine_module, "lightrag_kwargs_from_settings", dict)
    fake_raganything(_ModernRag, _ModernConfig)

    rag = engine_module.build_rag(tmp_path)

    assert rag.config.max_concurrent_files == 1  # the library default
    assert rag.lightrag_kwargs is None
