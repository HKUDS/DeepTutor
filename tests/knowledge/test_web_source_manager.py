from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source.pairing import group_sources_by_origin


@pytest.fixture
def manager(tmp_path: Path) -> KnowledgeBaseManager:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir(parents=True, exist_ok=True)
    manager.register_knowledge_base("kb")
    (manager.base_dir / "kb" / "metadata.json").write_text("{}", encoding="utf-8")
    return manager


def test_web_source_language_is_persisted(manager: KnowledgeBaseManager) -> None:
    source = manager.add_web_source("kb", "https://example.com/guide/", language="zh")

    assert source["language"] == "zh"
    assert manager.get_web_sources("kb")[0]["language"] == "zh"


def test_invalid_web_source_language_is_rejected(manager: KnowledgeBaseManager) -> None:
    with pytest.raises(ValueError, match="language"):
        manager.add_web_source("kb", "https://example.com/", language="fr")


def test_manual_pairing_links_separate_domains(manager: KnowledgeBaseManager) -> None:
    english = manager.add_web_source(
        "kb",
        "https://docs.example.com/",
        language="en",
        paired_url="https://example.cn/docs/",
    )
    chinese = manager.add_web_source(
        "kb",
        "https://example.cn/docs/",
        language="zh",
        paired_url="https://docs.example.com/",
    )

    sources = manager.get_web_sources("kb")
    pairs = group_sources_by_origin(sources)
    assert len(pairs) == 1
    assert pairs[0].en_source["id"] == english["id"]
    assert pairs[0].zh_source["id"] == chinese["id"]
    by_id = {source["id"]: source for source in sources}
    assert by_id[english["id"]]["paired_source_id"] == chinese["id"]
    assert by_id[chinese["id"]]["paired_source_id"] == english["id"]


def test_web_source_coverage_is_derived(manager: KnowledgeBaseManager) -> None:
    source = manager.add_web_source("kb", "https://example.com/", language="en")
    manager.update_web_source_state(
        "kb",
        source["id"],
        page_count=10,
        paired_pages=8,
    )

    assert manager.get_web_sources("kb")[0]["coverage"] == 0.8
