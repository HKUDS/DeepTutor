"""Tests for Markdown-level bilingual alignment."""
import pytest

from deeptutor.services.web_source.md_align import (
    split_blocks,
    align_markdown,
    align_markdown_en_only,
    HEADING,
    PARAGRAPH,
    CODE,
    IMAGE,
    LIST,
    TABLE,
    HR,
)


class TestSplitBlocks:
    def test_simple_paragraphs(self):
        md = "First paragraph.\n\nSecond paragraph."
        blocks = split_blocks(md)
        assert len(blocks) == 2
        assert all(b.block_type == PARAGRAPH for b in blocks)

    def test_heading_starts_new_block(self):
        md = "# Title\n\nContent.\n\n## Section\n\nMore content."
        blocks = split_blocks(md)
        types = [b.block_type for b in blocks]
        assert HEADING in types

    def test_code_fence_preserved(self):
        md = "Before code.\n\n```python\nx = 1\n# not a heading\ny = 2\n```\n\nAfter code."
        blocks = split_blocks(md)
        code_blocks = [b for b in blocks if b.block_type == CODE]
        assert len(code_blocks) == 1
        assert "x = 1" in code_blocks[0].content
        assert "# not a heading" in code_blocks[0].content

    def test_heading_inside_code_fence_not_split(self):
        md = "```python\n# This is a comment, not a heading\n```\n\nReal paragraph."
        blocks = split_blocks(md)
        # The heading inside the fence should be part of the code block
        heading_blocks = [b for b in blocks if b.block_type == HEADING]
        assert len(heading_blocks) == 0

    def test_list_grouped(self):
        md = "- Item 1\n- Item 2\n- Item 3"
        blocks = split_blocks(md)
        list_blocks = [b for b in blocks if b.block_type == LIST]
        assert len(list_blocks) == 1

    def test_table_grouped(self):
        md = "| Col A | Col B |\n| --- | --- |\n| 1 | 2 |"
        blocks = split_blocks(md)
        table_blocks = [b for b in blocks if b.block_type == TABLE]
        assert len(table_blocks) == 1

    def test_image_block(self):
        md = "![Alt text](image.png)"
        blocks = split_blocks(md)
        image_blocks = [b for b in blocks if b.block_type == IMAGE]
        assert len(image_blocks) == 1


class TestAlignMarkdown:
    def test_identical_structure_pairs(self):
        en = "# Title\n\nEnglish content here.\n\n## Section\n\nMore detail."
        zh = "# 标题\n\n中文内容在这里。\n\n## 章节\n\n更多细节。"
        result = align_markdown(en, zh)
        assert result["page_class"] == "bilingual"
        assert len(result["groups"]) >= 4
        # First group should be the heading pair
        assert "Title" in result["groups"][0]["en_content"]
        assert "标题" in result["groups"][0]["zh_content"]

    def test_show_once_for_code(self):
        en = "Some text.\n\n```python\nx = 1\n```\n\nMore text."
        zh = "一些文本。\n\n```python\nx = 1\n```\n\n更多文本。"
        result = align_markdown(en, zh)
        # Find the code group
        code_groups = [g for g in result["groups"] if "code" in g["show_once"]]
        assert len(code_groups) >= 1

    def test_show_once_for_image(self):
        en = "![Screenshot](screenshot.png)"
        zh = "![截图](screenshot.png)"
        result = align_markdown(en, zh)
        image_groups = [g for g in result["groups"] if "image" in g["show_once"]]
        assert len(image_groups) >= 1

    def test_en_only_result(self):
        en = "# English only page\n\nContent."
        zh = ""
        result = align_markdown(en, zh)
        assert result["page_class"] == "en_only"

    def test_zh_only_result(self):
        en = ""
        zh = "# 仅中文页面\n\n内容。"
        result = align_markdown(en, zh)
        assert result["page_class"] == "zh_only"

    def test_stable_group_ids(self):
        en = "# Title\n\nContent paragraph.\n\n## Section\n\nMore detail."
        zh = "# 标题\n\n内容段落。\n\n## 章节\n\n更多细节。"
        result1 = align_markdown(en, zh)
        result2 = align_markdown(en, zh)
        ids1 = [g["group_id"] for g in result1["groups"]]
        ids2 = [g["group_id"] for g in result2["groups"]]
        assert ids1 == ids2

    def test_group_ids_change_with_content(self):
        en1 = "# Title A\n\nContent."
        en2 = "# Title B\n\nContent."
        zh = "# 标题\n\n内容。"
        r1 = align_markdown(en1, zh)
        r2 = align_markdown(en2, zh)
        ids1 = {g["group_id"] for g in r1["groups"]}
        ids2 = {g["group_id"] for g in r2["groups"]}
        assert ids1 != ids2

    def test_source_comment_stripped(self):
        en = "<!-- source: https://example.com/page/ -->\n\n# Title\n\nContent."
        zh = "<!-- source: https://example.com/zh/page/ -->\n\n# 标题\n\n内容。"
        result = align_markdown(en, zh)
        for g in result["groups"]:
            assert "source:" not in g["en_content"]
            assert "source:" not in g["zh_content"]

    def test_content_hashes_present(self):
        en = "# Title\n\nContent."
        zh = "# 标题\n\n内容。"
        result = align_markdown(en, zh)
        assert result["en_hash"]
        assert result["zh_hash"]
        assert result["en_hash"] != result["zh_hash"]

    def test_interactive_book_page(self):
        """Integration test using the actual DeepTutor book page structure."""
        en = """# Interactive Book

Interactive Book turns your materials into a **living book**.

## Where it is

Open **Book** in the left sidebar.

![Book overview](/screenshots/book.png)

## Creation flow

1. Open **Book -> New book**.
2. Choose a topic.
"""
        zh = """# 交互式书本

交互式书本把你的材料变成一本**「活书」**。

## 它在哪里

点击左侧栏的 **Book**。

![Book 书库](/screenshots/book.png)

## 创建流程

1. 打开 **Book -> New book**。
2. 选择一个主题。
"""
        result = align_markdown(en, zh)
        assert result["page_class"] == "bilingual"
        # Should have heading pairs for all 3 sections
        heading_groups = [
            g for g in result["groups"]
            if g["en_content"].strip().startswith("#")
        ]
        assert len(heading_groups) >= 3
        # Check the first heading pair
        assert "Interactive Book" in heading_groups[0]["en_content"]
        assert "交互式书本" in heading_groups[0]["zh_content"]


class TestAlignMarkdownEnOnly:
    def test_basic_en_only(self):
        en = "# Title\n\nEnglish content.\n\n```python\ncode\n```"
        result = align_markdown_en_only(en)
        assert result["page_class"] == "en_only"
        assert len(result["groups"]) >= 2
        code_groups = [g for g in result["groups"] if "code" in g["show_once"]]
        assert len(code_groups) >= 1

    def test_no_zh_content(self):
        en = "# Title\n\nContent."
        result = align_markdown_en_only(en)
        for g in result["groups"]:
            assert g["zh_content"] == ""
