from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source import bilingual_store
from deeptutor.services.web_source.crawler import CrawlDiff
from deeptutor.services.web_source.orchestrator import sync_kb_sources_safe


@pytest.mark.asyncio
async def test_manual_pair_refreshes_stale_unilingual_sidecars(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    (kb_dir / "raw").mkdir(parents=True)
    manager.register_knowledge_base("kb")
    manager.add_web_source(
        "kb",
        "https://example.com/en.html",
        language="en",
        paired_url="https://example.cn/zh.html",
    )
    manager.add_web_source(
        "kb",
        "https://example.cn/zh.html",
        language="zh",
        paired_url="https://example.com/en.html",
    )
    sources = manager.get_web_sources("kb")
    pair_key = sources[0]["pairing_key"]
    (kb_dir / "raw" / "en.html.md").write_text(
        "# Reading\n\nThe harbour slept.\n", encoding="utf-8"
    )
    (kb_dir / "raw" / "zh.html.md").write_text("# 阅读\n\n海港沉睡着。\n", encoding="utf-8")
    bilingual_store.save_alignment(
        kb_dir, pair_key, "en.html.md", {"page_class": "en_only", "groups": []}
    )
    bilingual_store.save_alignment(
        kb_dir, pair_key, "zh.html.md", {"page_class": "zh_only", "groups": []}
    )

    async def fake_crawl(source: dict, raw_dir: Path, **_kwargs) -> CrawlDiff:
        filename = "en.html.md" if source["language"] == "en" else "zh.html.md"
        return CrawlDiff(
            ok=True,
            url=source["url"],
            page_hashes={filename: "hash"},
            page_files=[filename],
            page_urls={filename: source["url"]},
            pages_unchanged=[filename],
            navigation={"kind": "inferred", "nodes": []},
        )

    with (
        patch(
            "deeptutor.services.web_source.orchestrator.crawl_and_diff",
            new=AsyncMock(side_effect=fake_crawl),
        ),
        patch(
            "deeptutor.services.web_source.index_rebuild.rebuild_index_async",
            new=AsyncMock(),
        ),
    ):
        result = await sync_kb_sources_safe(
            "kb",
            manager.get_web_sources("kb"),
            base_dir=str(manager.base_dir),
        )

    assert result.ok is True
    pair_result = result.pair_results[0]
    assert pair_result.paired_pages == 1
    assert pair_result.en_only_pages == 0
    assert pair_result.zh_only_pages == 0
    alignment = bilingual_store.load_alignment(kb_dir, pair_key, "en.html.md")
    assert alignment is not None
    assert alignment["page_class"] == "bilingual"
    assert not (kb_dir / "bilingual" / pair_key / "zh.html.json").exists()
