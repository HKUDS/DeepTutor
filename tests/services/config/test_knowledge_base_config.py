"""Tests for KnowledgeBaseConfigService provider config + legacy migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.config.knowledge_base_config import (
    KnowledgeBaseConfigService,
)


def _write_kb_config(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def fresh_service(tmp_path: Path) -> KnowledgeBaseConfigService:
    """A KBConfigService bound to a tmp config path, bypassing the singleton."""
    return KnowledgeBaseConfigService(config_path=tmp_path / "kb_config.json")


class TestProviderApi:
    def test_get_rag_provider_defaults_to_llamaindex(self, fresh_service) -> None:
        assert fresh_service.get_rag_provider("any-kb") == "llamaindex"

    def test_set_rag_provider_preserves_known_engine(self, fresh_service) -> None:
        fresh_service.set_rag_provider("kb-1", "lightrag")
        cfg = fresh_service.get_kb_config("kb-1")
        assert cfg["rag_provider"] == "lightrag"

    def test_set_rag_provider_coerces_unknown_to_llamaindex(self, fresh_service) -> None:
        fresh_service.set_rag_provider("kb-2", "totally-unknown")
        cfg = fresh_service.get_kb_config("kb-2")
        assert cfg["rag_provider"] == "llamaindex"

    def test_get_kb_config_preserves_known_provider_field(self, fresh_service) -> None:
        _write_kb_config(
            fresh_service.config_path,
            {
                "knowledge_bases": {
                    "kb-3": {"path": "kb-3", "rag_provider": "pageindex"},
                }
            },
        )
        cfg = fresh_service.get_kb_config("kb-3")
        assert cfg["rag_provider"] == "pageindex"

    def test_get_kb_config_coerces_removed_provider_field(self, fresh_service) -> None:
        _write_kb_config(
            fresh_service.config_path,
            {
                "knowledge_bases": {
                    "kb-4": {"path": "kb-4", "rag_provider": "raganything"},
                }
            },
        )
        cfg = fresh_service.get_kb_config("kb-4")
        assert cfg["rag_provider"] == "llamaindex"

    def test_provider_mode_roundtrip(self, fresh_service) -> None:
        assert fresh_service.get_provider_mode("lightrag") == ""
        fresh_service.set_provider_mode("lightrag", "mix")
        assert fresh_service.get_provider_mode("lightrag") == "mix"
        # Per-engine: setting one doesn't touch another.
        fresh_service.set_provider_mode("graphrag", "drift")
        assert fresh_service.get_provider_mode("lightrag") == "mix"
        assert fresh_service.get_provider_mode("graphrag") == "drift"


class TestPayloadNormalizationOnLoad:
    def test_legacy_provider_in_file_is_rewritten_and_marks_reindex(self, tmp_path: Path) -> None:
        config_path = tmp_path / "kb_config.json"
        _write_kb_config(
            config_path,
            {
                "defaults": {"rag_provider": "raganything", "search_mode": "hybrid"},
                "knowledge_bases": {
                    "old-kb": {"path": "old-kb", "rag_provider": "raganything"},
                },
            },
        )

        service = KnowledgeBaseConfigService(config_path=config_path)
        kb = service._config["knowledge_bases"]["old-kb"]
        assert kb["rag_provider"] == "llamaindex"
        assert kb["needs_reindex"] is True

        defaults = service._config["defaults"]
        assert defaults["rag_provider"] == "llamaindex"

    def test_existing_llamaindex_kb_is_left_alone(self, tmp_path: Path) -> None:
        config_path = tmp_path / "kb_config.json"
        _write_kb_config(
            config_path,
            {
                "defaults": {"rag_provider": "llamaindex"},
                "knowledge_bases": {
                    "fresh-kb": {"path": "fresh-kb", "rag_provider": "llamaindex"},
                },
            },
        )

        service = KnowledgeBaseConfigService(config_path=config_path)
        kb = service._config["knowledge_bases"]["fresh-kb"]
        assert kb["rag_provider"] == "llamaindex"
        assert kb.get("needs_reindex", False) is False

    def test_existing_known_nondefault_kb_is_left_alone(self, tmp_path: Path) -> None:
        config_path = tmp_path / "kb_config.json"
        _write_kb_config(
            config_path,
            {
                "defaults": {"rag_provider": "llamaindex"},
                "knowledge_bases": {
                    "graph-kb": {"path": "graph-kb", "rag_provider": "graphrag"},
                },
            },
        )

        service = KnowledgeBaseConfigService(config_path=config_path)
        kb = service._config["knowledge_bases"]["graph-kb"]
        assert kb["rag_provider"] == "graphrag"
        assert kb.get("needs_reindex", False) is False

    def test_legacy_storage_dir_marks_reindex(self, tmp_path: Path) -> None:
        """If the on-disk storage uses the old layout, force a reindex flag."""
        config_path = tmp_path / "kb_config.json"
        kb_dir = tmp_path / "stale-kb"
        (kb_dir / "rag_storage").mkdir(parents=True)

        _write_kb_config(
            config_path,
            {
                "defaults": {"rag_provider": "llamaindex"},
                "knowledge_bases": {
                    "stale-kb": {"path": "stale-kb", "rag_provider": "llamaindex"},
                },
            },
        )

        service = KnowledgeBaseConfigService(config_path=config_path)
        kb = service._config["knowledge_bases"]["stale-kb"]
        assert kb["needs_reindex"] is True

    def test_modern_storage_dir_does_not_trigger_reindex(self, tmp_path: Path) -> None:
        config_path = tmp_path / "kb_config.json"
        kb_dir = tmp_path / "modern-kb"
        (kb_dir / "version-1").mkdir(parents=True)
        (kb_dir / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
        (kb_dir / "version-1" / "index_store.json").write_text("{}", encoding="utf-8")
        (kb_dir / "rag_storage").mkdir(parents=True)  # legacy dir co-existing

        _write_kb_config(
            config_path,
            {
                "knowledge_bases": {
                    "modern-kb": {"path": "modern-kb", "rag_provider": "llamaindex"},
                },
            },
        )

        service = KnowledgeBaseConfigService(config_path=config_path)
        kb = service._config["knowledge_bases"]["modern-kb"]
        # legacy dir present + modern dir present => no forced reindex
        assert kb.get("needs_reindex", False) is False


class TestPersistence:
    def test_set_kb_config_normalizes_on_save(self, tmp_path: Path) -> None:
        config_path = tmp_path / "kb_config.json"
        service = KnowledgeBaseConfigService(config_path=config_path)
        service.set_kb_config("new-kb", {"rag_provider": "raganything", "description": "x"})

        on_disk = json.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk["knowledge_bases"]["new-kb"]["rag_provider"] == "llamaindex"
        assert on_disk["knowledge_bases"]["new-kb"]["description"] == "x"

    def test_set_kb_config_preserves_known_provider_on_save(self, tmp_path: Path) -> None:
        config_path = tmp_path / "kb_config.json"
        service = KnowledgeBaseConfigService(config_path=config_path)
        service.set_kb_config("new-kb", {"rag_provider": "pageindex"})

        on_disk = json.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk["knowledge_bases"]["new-kb"]["rag_provider"] == "pageindex"

    def test_set_kb_config_does_not_resurrect_externally_removed_kbs(self, tmp_path: Path) -> None:
        """Regression: the service used to cache ``self._config`` at construction
        and ``_save()`` wrote that snapshot back wholesale. If
        ``KnowledgeBaseManager`` pruned an orphan KB from disk in between, the
        next ``set_kb_config`` call would resurrect it. Fix: refresh from disk
        before any write so the two writers share a consistent view.
        """
        config_path = tmp_path / "kb_config.json"
        _write_kb_config(
            config_path,
            {
                "defaults": {"rag_provider": "llamaindex"},
                "knowledge_bases": {
                    "orphan": {"path": "orphan", "rag_provider": "llamaindex"},
                    "kept": {"path": "kept", "rag_provider": "llamaindex"},
                },
            },
        )
        service = KnowledgeBaseConfigService(config_path=config_path)

        # External writer (e.g. KnowledgeBaseManager) prunes the orphan entry.
        external = json.loads(config_path.read_text(encoding="utf-8"))
        del external["knowledge_bases"]["orphan"]
        config_path.write_text(json.dumps(external), encoding="utf-8")

        # Service writes an unrelated update. The orphan must NOT come back.
        service.set_kb_config("kept", {"description": "still here"})

        on_disk = json.loads(config_path.read_text(encoding="utf-8"))
        assert "orphan" not in on_disk["knowledge_bases"]
        assert on_disk["knowledge_bases"]["kept"]["description"] == "still here"

    def test_search_mode_is_preserved(self, fresh_service) -> None:
        fresh_service.set_search_mode("kb", "naive")
        assert fresh_service.get_search_mode("kb") == "naive"

    def test_set_default_kb(self, fresh_service) -> None:
        fresh_service.set_default_kb("primary")
        assert fresh_service.get_default_kb() == "primary"
        fresh_service.set_default_kb(None)
        assert fresh_service.get_default_kb() is None
