"""Corrupt ``kb_config.json`` must surface through the RAG readers.

These resolvers used to swallow every parse/I/O error and fall back to their
defaults, so a damaged config silently rebound a KB to the default provider,
dropped its configured retrieval mode, or resolved a linked KB to a
non-existent local folder. Only a *missing* file may fall back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.config_store import KBConfigCorruptionError
from deeptutor.services.rag.kb_paths import resolve_kb_dir
from deeptutor.services.rag.pipelines.modes import resolve_kb_mode
from deeptutor.services.rag.provider_binding import (
    load_kb_config_entry,
    resolve_bound_provider,
)


@pytest.fixture
def corrupt_base(tmp_path: Path) -> Path:
    (tmp_path / "kb_config.json").write_text('{"knowledge_bases": {"kb": ', encoding="utf-8")
    return tmp_path


class TestCorruptConfigRaises:
    def test_load_kb_config_entry(self, corrupt_base: Path) -> None:
        with pytest.raises(KBConfigCorruptionError):
            load_kb_config_entry(corrupt_base, "kb")

    def test_resolve_bound_provider(self, corrupt_base: Path) -> None:
        with pytest.raises(KBConfigCorruptionError):
            resolve_bound_provider(corrupt_base, "kb")

    def test_resolve_kb_dir(self, corrupt_base: Path) -> None:
        with pytest.raises(KBConfigCorruptionError):
            resolve_kb_dir(corrupt_base, "kb")

    def test_resolve_kb_mode(self, corrupt_base: Path) -> None:
        with pytest.raises(KBConfigCorruptionError):
            resolve_kb_mode(
                corrupt_base, "kb", "lightrag", supported=["hybrid", "mix"], default="hybrid"
            )

    def test_zero_byte_config_raises_too(self, tmp_path: Path) -> None:
        (tmp_path / "kb_config.json").write_text("", encoding="utf-8")
        with pytest.raises(KBConfigCorruptionError):
            resolve_bound_provider(tmp_path, "kb")


class TestMissingConfigStillFallsBack:
    def test_provider_defaults(self, tmp_path: Path) -> None:
        assert resolve_bound_provider(tmp_path, "kb") == "llamaindex"
        assert load_kb_config_entry(tmp_path, "kb") == {}

    def test_kb_dir_uses_conventional_layout(self, tmp_path: Path) -> None:
        assert resolve_kb_dir(tmp_path, "kb") == tmp_path / "kb"

    def test_mode_uses_engine_default(self, tmp_path: Path) -> None:
        mode = resolve_kb_mode(
            tmp_path, "kb", "lightrag", supported=["hybrid", "mix"], default="hybrid"
        )
        assert mode == "hybrid"


class TestValidConfigStillResolves:
    def test_provider_mode_and_linked_path(self, tmp_path: Path) -> None:
        external = tmp_path / "external"
        external.mkdir()
        (tmp_path / "kb_config.json").write_text(
            json.dumps(
                {
                    "defaults": {"provider_modes": {"lightrag": "mix"}},
                    "knowledge_bases": {
                        "kb": {"path": "kb", "rag_provider": "graphrag"},
                        "linked": {"type": "linked", "external_path": str(external)},
                    },
                }
            ),
            encoding="utf-8",
        )

        assert resolve_bound_provider(tmp_path, "kb") == "graphrag"
        assert resolve_kb_dir(tmp_path, "linked") == external
        mode = resolve_kb_mode(
            tmp_path, "kb", "lightrag", supported=["hybrid", "mix"], default="hybrid"
        )
        assert mode == "mix"
