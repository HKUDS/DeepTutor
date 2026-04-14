from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.structure_note import generator as generator_module
from deeptutor.services.structure_note.difficulty import get_difficulty_preset
from deeptutor.services.structure_note.generator import (
    _combination_instruction,
    build_generation_chunks,
    generate_transition_markdown,
)
from deeptutor.services.structure_note.image_pipeline import process_images
from deeptutor.services.structure_note.manager import StructureNoteManager
from deeptutor.services.structure_note.markdown_postprocessor import (
    normalize_structure_note_markdown,
    validate_renderer_compatible_markdown,
)
from deeptutor.services.structure_note.models import (
    DifficultyLevel,
    ExplanationStyleLevel,
    GenerationChunk,
    JobStatus,
    NoteLanguage,
    PageIndexPage,
    SectionTreeNode,
    StructureNoteArtifact,
)
from deeptutor.services.structure_note.normalizer import NormalizationError, normalize_to_pdf
from deeptutor.services.structure_note.page_index import sections_from_pageindex_structure
from deeptutor.services.structure_note.planner import build_document_plan
from deeptutor.services.structure_note.tree_builder import build_section_tree


def _page(page_number: int, *, text: str = "", image_candidates=None) -> PageIndexPage:
    return PageIndexPage(
        page_number=page_number,
        width=800,
        height=1200,
        text=text,
        text_blocks=[],
        title_candidates=[],
        image_candidates=image_candidates or [],
    )


def test_vectify_pageindex_structure_maps_to_section_tree() -> None:
    structure = [
        {
            "title": "Chapter 1",
            "start_index": 1,
            "end_index": 4,
            "summary": "Core ideas.",
            "nodes": [
                {
                    "title": "Topic 1.1",
                    "start_index": 2,
                    "end_index": 4,
                    "summary": "Details.",
                }
            ],
        },
        {"title": "Chapter 2", "start_index": 5, "end_index": 9},
    ]

    tree = sections_from_pageindex_structure(structure, total_pages=6)

    assert [node.title for node in tree] == ["Chapter 1", "Topic 1.1", "Chapter 2"]
    assert tree[0].child_ids == ["section-002"]
    assert tree[1].parent_id == "section-001"
    assert tree[2].page_end == 6


def test_normalizer_requires_soffice_for_ppt(monkeypatch, tmp_path: Path) -> None:
    ppt_path = tmp_path / "deck.pptx"
    ppt_path.write_text("fake", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(NormalizationError) as exc:
        normalize_to_pdf(ppt_path, tmp_path / "normalized")

    assert "LibreOffice" in str(exc.value)


def test_generation_chunks_use_difficulty_window() -> None:
    pages = [_page(index, text=f"content {index}") for index in range(1, 15)]
    chunks = build_generation_chunks(pages, [], get_difficulty_preset(DifficultyLevel.DETAILED))

    assert chunks
    assert all(len(chunk.page_numbers) <= 6 for chunk in chunks)
    assert chunks[0].page_start == 1


def test_generation_chunks_use_section_plan_not_page_windows() -> None:
    pages = [_page(index, text=f"content {index}") for index in range(1, 15)]
    sections = [
        SectionTreeNode(
            section_id="section-001",
            title="Long Section",
            level=2,
            page_start=1,
            page_end=14,
            summary="A long section.",
            path=["Long Section"],
        )
    ]
    plan = build_document_plan(pages, sections, document_title="demo.pdf", language="en")
    chunks = build_generation_chunks(
        pages,
        sections,
        get_difficulty_preset(DifficultyLevel.DETAILED),
        document_plan=plan,
    )

    assert len(chunks) == 1
    assert chunks[0].section_id == "section-001"
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 14
    assert chunks[0].evidence


def test_generation_chunks_limit_parent_section_to_overview_pages() -> None:
    pages = [_page(index, text=f"content {index}") for index in range(1, 7)]
    sections = [
        SectionTreeNode(
            section_id="section-001",
            title="Chapter",
            level=2,
            page_start=1,
            page_end=6,
            summary="Chapter overview.",
            child_ids=["section-002"],
            path=["Chapter"],
        ),
        SectionTreeNode(
            section_id="section-002",
            title="Main Topic",
            level=3,
            page_start=2,
            page_end=6,
            parent_id="section-001",
            summary="Main details.",
            path=["Chapter", "Main Topic"],
        ),
    ]
    plan = build_document_plan(pages, sections, document_title="demo.pdf", language="en")
    chunks = build_generation_chunks(
        pages,
        sections,
        get_difficulty_preset(DifficultyLevel.MEDIUM),
        document_plan=plan,
    )

    assert [chunk.section_id for chunk in chunks] == ["section-001", "section-002"]
    assert chunks[0].page_numbers == [1]
    assert chunks[1].page_numbers == [2, 3, 4, 5, 6]


@pytest.mark.parametrize(
    ("depth", "style", "expected"),
    [
        (DifficultyLevel.SIMPLE, ExplanationStyleLevel.LOW, "短篇幅、低门槛"),
        (DifficultyLevel.SIMPLE, ExplanationStyleLevel.MEDIUM, "核心知识骨架"),
        (DifficultyLevel.SIMPLE, ExplanationStyleLevel.HIGH, "short but dense"),
        (DifficultyLevel.MEDIUM, ExplanationStyleLevel.LOW, "中等篇幅、科普风格"),
        (DifficultyLevel.MEDIUM, ExplanationStyleLevel.MEDIUM, "默认模式"),
        (DifficultyLevel.MEDIUM, ExplanationStyleLevel.HIGH, "学术课堂风格"),
        (DifficultyLevel.DETAILED, ExplanationStyleLevel.LOW, "长篇幅、低门槛"),
        (DifficultyLevel.DETAILED, ExplanationStyleLevel.MEDIUM, "完整课堂讲义"),
        (DifficultyLevel.DETAILED, ExplanationStyleLevel.HIGH, "学术讲义/课程笔记"),
    ],
)
def test_depth_style_combinations_have_stable_prompt_semantics(
    depth: DifficultyLevel,
    style: ExplanationStyleLevel,
    expected: str,
) -> None:
    assert expected in _combination_instruction(depth, style, NoteLanguage.ZH.value)


def test_markdown_postprocessor_normalizes_renderer_math_syntax() -> None:
    markdown = (
        "Use $x + y$ to express the sum, call \\(softmax(x)\\), and keep currency $100.\n\n"
        "$$a=b$$\n\n"
        "$$\\(c=d\\)$$\n\n"
        "\\[e=f\\]\n\n"
        "```python\nprint('$x$')\n```\n"
    )

    normalized = normalize_structure_note_markdown(markdown)

    assert "$x + y$" in normalized
    assert "`softmax(x)`" in normalized
    assert "$$\na=b\n$$" in normalized
    assert "$$\nc=d\n$$" in normalized
    assert "$$\ne=f\n$$" in normalized
    assert "\\(" not in normalized
    assert "\\[" not in normalized
    assert "print('$x$')" in normalized
    assert validate_renderer_compatible_markdown(normalized).ok is True


def test_markdown_validation_detects_damaged_formula() -> None:
    result = validate_renderer_compatible_markdown("The update is $x + \\frac{1}{2.\n")

    assert result.ok is False
    assert any("damaged inline math delimiter" in warning for warning in result.warnings)


def test_compose_markdown_inserts_generated_transition_between_major_sections() -> None:
    artifact = StructureNoteArtifact(
        job_id="job_1",
        file_name="demo.pdf",
        source_format="pdf",
        difficulty_level=DifficultyLevel.MEDIUM,
        note_language=NoteLanguage.ZH,
        style_level=ExplanationStyleLevel.HIGH,
        status=JobStatus.RENDERING,
        source_path="/tmp/demo.pdf",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    chunks = [
        GenerationChunk(
            chunk_id="chunk-001",
            section_id="section-001",
            section_title="基础概念",
            section_summary="基础概念",
            section_path=["基础概念"],
            heading_level=2,
            page_start=1,
            page_end=3,
            page_numbers=[1, 2, 3],
            markdown="## 基础概念\n\n内容。",
        ),
        GenerationChunk(
            chunk_id="chunk-002",
            section_id="section-002",
            section_title="理论展开",
            section_summary="理论展开",
            section_path=["理论展开"],
            heading_level=2,
            page_start=4,
            page_end=6,
            page_numbers=[4, 5, 6],
            markdown="## 理论展开\n\n内容。",
        ),
    ]

    markdown = StructureNoteManager()._compose_markdown(
        artifact,
        chunks,
        NoteLanguage.ZH.value,
        transition_map={
            "section-002": "基础概念已经确定了问题的核心变量，但要解释这些变量如何形成稳定关系，还需要进入理论层面的约束与推理。"
        },
    )

    assert "> **过渡：**" not in markdown
    assert "建立了必要的概念基础" not in markdown
    assert "核心变量" in markdown
    assert "基础概念" in markdown
    assert "理论展开" in markdown


@pytest.mark.asyncio
async def test_generate_transition_markdown_uses_llm_context(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def _fake_complete(prompt: str, **_kwargs):
        captured["prompt"] = prompt
        return (
            "> 前面的定义已经说明目标函数衡量什么，但优化过程还需要解释参数为什么沿梯度方向移动。"
        )

    monkeypatch.setattr(generator_module, "llm_complete", _fake_complete)
    previous = GenerationChunk(
        chunk_id="chunk-001",
        section_id="section-001",
        section_title="目标函数",
        section_summary="定义损失与优化目标。",
        section_path=["目标函数"],
        heading_level=2,
        page_start=1,
        page_end=2,
        page_numbers=[1, 2],
        markdown="## 目标函数\n\n损失函数刻画预测与真实结果之间的差异。" * 20,
    )
    current = GenerationChunk(
        chunk_id="chunk-002",
        section_id="section-002",
        section_title="梯度下降",
        section_summary="用梯度更新参数。",
        section_path=["梯度下降"],
        heading_level=2,
        page_start=3,
        page_end=4,
        page_numbers=[3, 4],
        markdown="## 梯度下降\n\n梯度方向给出局部变化最快的方向。",
    )

    transition = await generate_transition_markdown(
        previous,
        current,
        language=NoteLanguage.ZH.value,
        style_level=ExplanationStyleLevel.HIGH,
    )

    assert transition.startswith("前面的定义")
    assert not transition.startswith(">")
    assert "Title: 目标函数" in captured["prompt"]
    assert "Title: 梯度下降" in captured["prompt"]
    assert "损失函数刻画预测" in captured["prompt"]
    assert "梯度方向给出" in captured["prompt"]
    assert "Do NOT use template phrases" in captured["prompt"]


@pytest.mark.asyncio
async def test_generate_transition_markdown_falls_back_without_blocking(monkeypatch) -> None:
    async def _raise_complete(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(generator_module, "llm_complete", _raise_complete)
    previous = GenerationChunk(
        chunk_id="chunk-001",
        section_title="A",
        section_path=["A"],
        heading_level=2,
        page_start=1,
        page_end=1,
        page_numbers=[1],
        markdown="## A\n\nA content.",
    )
    current = GenerationChunk(
        chunk_id="chunk-002",
        section_title="B",
        section_path=["B"],
        heading_level=2,
        page_start=2,
        page_end=2,
        page_numbers=[2],
        markdown="## B\n\nB content.",
    )

    transition = await generate_transition_markdown(
        previous,
        current,
        language=NoteLanguage.EN.value,
        style_level=ExplanationStyleLevel.MEDIUM,
    )

    assert transition == "A leads naturally to B."


@pytest.mark.asyncio
async def test_tree_builder_falls_back_without_candidates() -> None:
    pages = [_page(index, text=f"content {index}") for index in range(1, 12)]
    tree = await build_section_tree(pages, page_window=5, language="en")

    assert tree
    assert tree[0].page_start == 1
    assert tree[0].page_end == 5


def test_image_pipeline_falls_back_to_full_page(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "demo.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=600)
    page.insert_text((72, 72), "Hello Structure Note")
    document.save(pdf_path)
    document.close()

    pages = [_page(1, text="Hello", image_candidates=[])]
    chunks = [
        GenerationChunk(
            chunk_id="chunk-001",
            section_title="Page 1",
            section_path=["Page 1"],
            page_start=1,
            page_end=1,
            page_numbers=[1],
            markdown="## Page 1\n\n[[IMAGE_PLACEHOLDER:chunk-001-image-1:1:key_figure]]\n",
            placeholder_ids=["chunk-001-image-1"],
        )
    ]

    next_chunks, placeholders, citations = process_images(
        chunks,
        pages,
        pdf_path,
        tmp_path / "images",
        "demo.pdf",
        language="en",
    )

    assert placeholders[0].status == "fallback_page"
    assert citations[0].source_kind == "image"
    assert "images/chunk-001-image-1.png" in next_chunks[0].markdown
    assert "It supports the explanation of Page 1" in next_chunks[0].markdown
