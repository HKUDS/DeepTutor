from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.agents.goal.extractor import KnowledgeExtractor


@pytest.mark.asyncio
async def test_extractor_uses_fallback_when_kb_missing(tmp_path: Path) -> None:
    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")

    drafts = await extractor.extract(
        "missing_kb",
        scope={"chapters": ["极限", "导数"], "topics": [], "exclude_topics": []},
    )

    assert [draft.title for draft in drafts[:2]] == ["极限", "导数"]
    assert drafts[0].evidence[0].source == "fallback:missing_kb"
    assert drafts[1].prerequisites == ["极限"]


@pytest.mark.asyncio
async def test_extractor_reads_files_and_dedupes_titles(tmp_path: Path) -> None:
    kb_dir = tmp_path / "knowledge_bases" / "calc"
    (kb_dir / "content_list").mkdir(parents=True)
    (kb_dir / "raw").mkdir(parents=True)
    (kb_dir / "content_list" / "chapter1.md").write_text(
        "# 极限\n## 导数\n",
        encoding="utf-8",
    )
    (kb_dir / "raw" / "notes.txt").write_text(
        "1. 极限\n导数\n",
        encoding="utf-8",
    )

    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")
    drafts = await extractor.extract("calc")
    by_title = {draft.title: draft for draft in drafts}

    assert "极限" in by_title
    assert "导数" in by_title
    assert by_title["极限"].doc_freq >= 2.0
    assert len(by_title["极限"].evidence) >= 2


@pytest.mark.asyncio
async def test_extractor_fallback_uses_goal_statement_domain_priors(tmp_path: Path) -> None:
    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")
    drafts = await extractor.extract(
        "missing_kb",
        scope={
            "goal_statement": "7天复习微积分并结合历年真题提升解题速度",
            "chapters": [],
            "topics": [],
            "exclude_topics": [],
        },
    )
    titles = [draft.title for draft in drafts]

    assert "导数与求导规则" in titles
    assert "高频真题题型拆解" in titles
