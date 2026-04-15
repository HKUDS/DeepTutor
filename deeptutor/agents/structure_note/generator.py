from __future__ import annotations

from collections.abc import Iterable
import re

from deeptutor.services.llm import complete as llm_complete

from .difficulty import DifficultyPreset
from .markdown_postprocessor import normalize_structure_note_markdown
from .models import (
    DifficultyLevel,
    DocumentPlan,
    ExplanationStyleLevel,
    GenerationChunk,
    NoteLanguage,
    PageIndexPage,
    SectionEvidence,
    SectionPlan,
    SectionTreeNode,
)


def _pages_by_number(pages: Iterable[PageIndexPage]) -> dict[int, PageIndexPage]:
    return {page.page_number: page for page in pages}


def build_generation_chunks(
    pages: list[PageIndexPage],
    sections: list[SectionTreeNode],
    preset: DifficultyPreset,
    document_plan: DocumentPlan | None = None,
) -> list[GenerationChunk]:
    chunks: list[GenerationChunk] = []
    chunk_index = 1

    if document_plan and document_plan.outline:
        section_lookup = {section.section_id: section for section in document_plan.outline}
        tree_lookup = {section.section_id: section for section in sections}
        ordered_plans = [
            section_lookup[section_id]
            for section_id in document_plan.section_order
            if section_id in section_lookup
        ]
        for plan in ordered_plans:
            page_numbers = plan.page_numbers
            evidence = plan.evidence
            tree_node = tree_lookup.get(plan.section_id)
            if tree_node and tree_node.child_ids:
                child_starts = [
                    tree_lookup[child_id].page_start
                    for child_id in tree_node.child_ids
                    if child_id in tree_lookup
                ]
                if child_starts:
                    overview_end = min(plan.page_end, min(child_starts) - 1)
                    page_numbers = list(range(plan.page_start, overview_end + 1))
                    if not page_numbers:
                        page_numbers = [plan.page_start]
                    evidence = [
                        item for item in plan.evidence if item.page_number in set(page_numbers)
                    ]
            if not page_numbers:
                continue
            chunks.append(
                _chunk_from_plan(plan, chunk_index, page_numbers=page_numbers, evidence=evidence)
            )
            chunk_index += 1
    elif sections:
        ordered_sections = sorted(
            sections, key=lambda item: (item.page_start, item.level, item.section_id)
        )
        for section in ordered_sections:
            page_numbers = list(range(section.page_start, section.page_end + 1))
            if not page_numbers:
                continue
            chunks.append(
                GenerationChunk(
                    chunk_id=f"chunk-{chunk_index:03d}",
                    section_id=section.section_id,
                    section_title=section.title,
                    section_path=section.path or [section.title],
                    section_summary=section.summary,
                    heading_level=max(2, min(section.level, 5)),
                    page_start=page_numbers[0],
                    page_end=page_numbers[-1],
                    page_numbers=page_numbers,
                )
            )
            chunk_index += 1
    else:
        for start in range(1, len(pages) + 1, preset.page_window):
            window = list(range(start, min(start + preset.page_window, len(pages) + 1)))
            title = f"Pages {window[0]}-{window[-1]}" if len(window) > 1 else f"Page {window[0]}"
            chunks.append(
                GenerationChunk(
                    chunk_id=f"chunk-{chunk_index:03d}",
                    section_title=title,
                    section_path=[title],
                    page_start=window[0],
                    page_end=window[-1],
                    page_numbers=window,
                )
            )
            chunk_index += 1

    return chunks


def _chunk_from_plan(
    plan: SectionPlan,
    chunk_index: int,
    *,
    page_numbers: list[int] | None = None,
    evidence: list[SectionEvidence] | None = None,
) -> GenerationChunk:
    resolved_pages = page_numbers or plan.page_numbers
    return GenerationChunk(
        chunk_id=f"chunk-{chunk_index:03d}",
        section_id=plan.section_id,
        section_title=plan.title,
        section_path=plan.section_path or [plan.title],
        section_summary=plan.summary,
        heading_level=max(2, min(plan.level, 5)),
        page_start=resolved_pages[0],
        page_end=resolved_pages[-1],
        page_numbers=resolved_pages,
        evidence=evidence if evidence is not None else plan.evidence,
        dependencies=plan.dependencies,
    )


def _build_page_context(
    page_lookup: dict[int, PageIndexPage],
    page_numbers: list[int],
    evidence: list[SectionEvidence],
) -> str:
    parts: list[str] = []
    evidence_lookup = {item.page_number: item for item in evidence}
    for page_number in page_numbers:
        page = page_lookup.get(page_number)
        if not page:
            continue
        evidence_item = evidence_lookup.get(page_number)
        excerpt = evidence_item.excerpt if evidence_item else page.text.strip()
        if len(excerpt) > 1800:
            excerpt = f"{excerpt[:1800]}\n..."
        title_candidates = (
            evidence_item.title_candidates
            if evidence_item
            else [candidate.text for candidate in page.title_candidates[:5]]
        )
        image_candidate_ids = (
            evidence_item.image_candidate_ids
            if evidence_item
            else [candidate.candidate_id for candidate in page.image_candidates[:8]]
        )
        metadata = []
        if title_candidates:
            metadata.append(f"title candidates: {title_candidates}")
        if image_candidate_ids:
            metadata.append(f"image candidates: {image_candidate_ids}")
        suffix = f"\n({'; '.join(metadata)})" if metadata else ""
        parts.append(f"[Page {page_number}]{suffix}\n{excerpt}")
    return "\n\n".join(parts)


def _fallback_markdown(
    chunk: GenerationChunk, page_lookup: dict[int, PageIndexPage], language: str
) -> str:
    heading = "#" * max(2, min(chunk.heading_level, 5))
    title = " / ".join(chunk.section_path)
    source_range = (
        f"Pages {chunk.page_start}-{chunk.page_end}"
        if chunk.page_start != chunk.page_end
        else f"Page {chunk.page_start}"
    )
    if language == "zh":
        intro = f"本节根据第 {chunk.page_start}-{chunk.page_end} 页内容整理。"
        summary_label = "本节小结"
        source_label = "来源线索"
        empty = "该页范围未提取到可用文本。"
    else:
        intro = f"This section synthesizes the material from {source_range.lower()}."
        summary_label = "Section Summary"
        source_label = "Source Notes"
        empty = "No extractable text was found for this section range."
    source_notes: list[str] = []
    for page_number in chunk.page_numbers:
        page = page_lookup.get(page_number)
        if not page or not page.text.strip():
            continue
        excerpt = page.text.strip().replace("\n", " ")
        if len(excerpt) > 360:
            excerpt = f"{excerpt[:360]}..."
        source_notes.append(f"- Page {page_number}: {excerpt}")
    if not source_notes:
        source_notes.append(f"- {empty}")
    summary = chunk.section_summary or empty
    return (
        f"{heading} {title}\n\n"
        f"{intro}\n\n"
        f"### {source_label}\n\n"
        + "\n".join(source_notes)
        + f"\n\n> **{summary_label}:** {summary}\n"
    )


def _strip_markdown_fence(content: str) -> str:
    match = re.fullmatch(
        r"\s*```(?:markdown)?\s*(.*?)\s*```\s*", content, flags=re.DOTALL | re.IGNORECASE
    )
    return match.group(1).strip() if match else content.strip()


def _document_outline(document_plan: DocumentPlan | None) -> str:
    if not document_plan:
        return ""
    lines: list[str] = []
    for section in document_plan.outline:
        indent = "  " * max(0, section.level - 2)
        page_range = (
            f"pages {section.page_start}-{section.page_end}"
            if section.page_start != section.page_end
            else f"page {section.page_start}"
        )
        lines.append(f"{indent}- {section.title} ({page_range}): {section.summary}")
    return "\n".join(lines)


def _language_name(language: str) -> str:
    if language == NoteLanguage.ZH.value:
        return "Chinese"
    if language == NoteLanguage.EN.value:
        return "English"
    return language


def _style_instruction(style_level: ExplanationStyleLevel, language: str) -> str:
    if language == NoteLanguage.ZH.value:
        if style_level == ExplanationStyleLevel.LOW:
            return (
                "Low 只控制怎么讲：科普式讲解，强调直观、易懂、低门槛，减少术语和公式负担。"
                "不要减少本节按 depth 要覆盖的核心内容。"
            )
        if style_level == ExplanationStyleLevel.HIGH:
            return (
                "High 只控制怎么讲：学术讲义风格，定义更精确，边界更清楚，逻辑链更严格，"
                "强调机制、论证链和术语精度。理工/数学/计算机可保留关键公式、推导、矩阵、定理或算法机制；"
                "生物/医学保留机制链路、因果过程和术语定义；社科/人文保留概念辨析、理论框架和论证结构。"
                "High 的本质是 rigor，不是强行造公式。"
            )
        return (
            "Medium 只控制怎么讲：标准课堂讲义风格，兼顾清晰度、完整性和一定理论性，"
            "不要改变 depth 决定的覆盖范围。"
        )

    if style_level == ExplanationStyleLevel.LOW:
        return (
            "Low controls how to explain: popular-science style, intuitive, approachable, and low-friction, "
            "with less terminology and formula burden. Do not reduce the content coverage selected by depth."
        )
    if style_level == ExplanationStyleLevel.HIGH:
        return (
            "High controls how to explain: academic lecture-note style with precise definitions, clear concept "
            "boundaries, strict logic, mechanisms, argument chains, and terminology precision. For STEM, math, "
            "CS, or engineering, preserve key formulas, derivations, matrices, theorems, or algorithm mechanisms "
            "when supported. For biology or medicine, preserve mechanism chains, causal processes, and definitions. "
            "For social sciences or humanities, preserve conceptual distinctions, theoretical frameworks, and "
            "argument structure. High means rigor; do not invent formulas."
        )
    return (
        "Medium controls how to explain: standard classroom handout style, balancing clarity, completeness, "
        "and moderate theoretical density without changing the depth coverage."
    )


def _depth_label(level: DifficultyLevel) -> str:
    return {
        DifficultyLevel.SIMPLE: "Simple",
        DifficultyLevel.MEDIUM: "Medium",
        DifficultyLevel.DETAILED: "Detailed",
    }[level]


def _style_label(style_level: ExplanationStyleLevel) -> str:
    return {
        ExplanationStyleLevel.LOW: "Low",
        ExplanationStyleLevel.MEDIUM: "Medium",
        ExplanationStyleLevel.HIGH: "High",
    }[style_level]


def _transition_excerpt(markdown: str, limit: int = 800) -> str:
    excerpt = markdown.strip()
    if len(excerpt) <= limit:
        return excerpt
    return f"{excerpt[:limit].rstrip()}..."


def _clean_transition_markdown(content: str) -> str:
    cleaned = normalize_structure_note_markdown(_strip_markdown_fence(content))
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    normalized_lines: list[str] = []
    for line in lines:
        line = re.sub(r"^(?:>\s*)+", "", line).strip()
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line).strip()
        if line:
            normalized_lines.append(line)
    return " ".join(normalized_lines).strip()


def _transition_style_instruction(style_level: ExplanationStyleLevel) -> str:
    if style_level == ExplanationStyleLevel.LOW:
        return "LOW: intuitive, simple explanation"
    if style_level == ExplanationStyleLevel.HIGH:
        return "HIGH: emphasize logical necessity, limitation, or theoretical gap"
    return "MEDIUM: standard lecture explanation (default)"


def _minimal_transition_fallback(previous: GenerationChunk, current: GenerationChunk) -> str:
    return f"{previous.section_title} leads naturally to {current.section_title}."


async def generate_transition_markdown(
    previous: GenerationChunk,
    current: GenerationChunk,
    *,
    language: str,
    style_level: ExplanationStyleLevel,
    document_plan: DocumentPlan | None = None,
) -> str:
    outline = _document_outline(document_plan)
    prompt = (
        "Write a short transition paragraph for a lecture-style note.\n\n"
        "Goal:\n"
        "Connect the previous section to the current section in a natural, knowledge-driven way.\n\n"
        "Requirements:\n"
        "- 1-3 sentences ONLY\n"
        "- Do NOT use template phrases like:\n"
        '  "上一部分...", "接下来...", "本节将..."\n'
        "- Do NOT mention slides or pages\n"
        "- Explain the logical bridge:\n"
        "  1. what the previous section established\n"
        "  2. what is still missing or limited\n"
        "  3. why the current section naturally follows\n"
        "- Write like a human lecture note, not a system connector\n"
        "- No bullet points\n"
        "- Output plain Markdown paragraph only\n\n"
        "Style:\n"
        "- LOW: intuitive, simple explanation\n"
        "- MEDIUM: standard lecture explanation (default)\n"
        "- HIGH: emphasize logical necessity, limitation, or theoretical gap\n"
        f"Selected style: {_transition_style_instruction(style_level)}\n\n"
        f"Language:\n{_language_name(language)}\n\n"
        f"Document Outline:\n{outline or '(not provided)'}\n\n"
        "Previous Section:\n"
        f"Title: {previous.section_title}\n"
        f"Summary: {previous.section_summary}\n"
        f"Excerpt: {_transition_excerpt(previous.markdown)}\n\n"
        "Current Section:\n"
        f"Title: {current.section_title}\n"
        f"Summary: {current.section_summary}\n"
        f"Excerpt: {_transition_excerpt(current.markdown)}\n"
    )
    try:
        response = await llm_complete(
            prompt=prompt,
            system_prompt=(
                "You write concise connective paragraphs for online lecture notes. "
                "Use the given section excerpts to explain the knowledge flow without using a fixed template."
            ),
            temperature=0.45,
        )
        cleaned = _clean_transition_markdown(response)
        return cleaned or _minimal_transition_fallback(previous, current)
    except Exception:
        return _minimal_transition_fallback(previous, current)


def _combination_instruction(
    depth_level: DifficultyLevel,
    style_level: ExplanationStyleLevel,
    language: str,
) -> str:
    if language == NoteLanguage.ZH.value:
        matrix = {
            (DifficultyLevel.SIMPLE, ExplanationStyleLevel.LOW): (
                "Simple + Low：短篇幅、低门槛、科普化。只讲最核心内容，用直觉化表达帮助快速入门。"
            ),
            (DifficultyLevel.SIMPLE, ExplanationStyleLevel.MEDIUM): (
                "Simple + Medium：短篇幅、标准课堂风格。只保留核心知识骨架，但表述清晰、正常、不泛化。"
            ),
            (DifficultyLevel.SIMPLE, ExplanationStyleLevel.HIGH): (
                "Simple + High：短篇幅、高密度、学术型核心讲义。只讲最重要内容，但保留严谨定义、关键机制、"
                "关键公式或关键论证的作用说明。这是 short but dense，不是 short and shallow。"
            ),
            (DifficultyLevel.MEDIUM, ExplanationStyleLevel.LOW): (
                "Medium + Low：中等篇幅、科普风格。覆盖主要知识点，但仍以直观解释为主，减少抽象负担。"
            ),
            (DifficultyLevel.MEDIUM, ExplanationStyleLevel.MEDIUM): (
                "Medium + Medium：中等篇幅、标准课堂讲义。作为默认模式，兼顾覆盖面、逻辑和可读性。"
            ),
            (DifficultyLevel.MEDIUM, ExplanationStyleLevel.HIGH): (
                "Medium + High：中等篇幅、学术课堂风格。覆盖主要知识点，同时保留较强理论解释和关键数学、机制或论证说明。"
            ),
            (DifficultyLevel.DETAILED, ExplanationStyleLevel.LOW): (
                "Detailed + Low：长篇幅、低门槛。讲得更全、更慢、更细，但仍以易懂为优先，不强行学术化。"
            ),
            (DifficultyLevel.DETAILED, ExplanationStyleLevel.MEDIUM): (
                "Detailed + Medium：长篇幅、完整课堂讲义。比较全面，适合复习和系统整理。"
            ),
            (DifficultyLevel.DETAILED, ExplanationStyleLevel.HIGH): (
                "Detailed + High：长篇幅、学术讲义/课程笔记风格。完整覆盖，强理论解释，并保留材料支持的必要推导、公式或严谨论证。"
            ),
        }
        return matrix[(depth_level, style_level)]

    matrix = {
        (DifficultyLevel.SIMPLE, ExplanationStyleLevel.LOW): (
            "Simple + Low: short, low-barrier, popular-science explanation. Cover only the core ideas "
            "and use intuitive language for fast entry-level understanding."
        ),
        (DifficultyLevel.SIMPLE, ExplanationStyleLevel.MEDIUM): (
            "Simple + Medium: short standard classroom note. Keep the core knowledge skeleton, but explain it clearly "
            "without flattening it into a vague summary."
        ),
        (DifficultyLevel.SIMPLE, ExplanationStyleLevel.HIGH): (
            "Simple + High: short, dense, academic core note. Cover only the most important material while preserving "
            "precise definitions, key mechanisms, and the role of any essential formula or argument. This is short "
            "but dense, not short and shallow."
        ),
        (DifficultyLevel.MEDIUM, ExplanationStyleLevel.LOW): (
            "Medium + Low: medium length, popular-science style. Cover the main knowledge points with intuitive "
            "explanations and a lighter abstraction burden."
        ),
        (DifficultyLevel.MEDIUM, ExplanationStyleLevel.MEDIUM): (
            "Medium + Medium: medium length standard classroom note. This is the default balance of coverage, "
            "logic, and readability."
        ),
        (DifficultyLevel.MEDIUM, ExplanationStyleLevel.HIGH): (
            "Medium + High: medium length academic classroom note. Cover the main knowledge points while preserving "
            "stronger theoretical explanation and key mathematical, mechanistic, or argumentative structure."
        ),
        (DifficultyLevel.DETAILED, ExplanationStyleLevel.LOW): (
            "Detailed + Low: long, low-barrier explanation. Cover more material slowly and carefully while keeping "
            "accessibility ahead of academic density."
        ),
        (DifficultyLevel.DETAILED, ExplanationStyleLevel.MEDIUM): (
            "Detailed + Medium: long, complete classroom note for review and systematic organization."
        ),
        (DifficultyLevel.DETAILED, ExplanationStyleLevel.HIGH): (
            "Detailed + High: long academic lecture note. Complete coverage with strong theoretical explanation and "
            "source-supported derivations, formulas, or rigorous arguments when appropriate."
        ),
    }
    return matrix[(depth_level, style_level)]


def _prompt_contract(
    preset: DifficultyPreset,
    style_level: ExplanationStyleLevel,
    language: str,
) -> str:
    if language == NoteLanguage.ZH.value:
        return (
            "Parameter contract:\n"
            f"- Explanation Depth = {_depth_label(preset.level)}，只控制“讲多少”：{preset.depth_instruction}\n"
            f"- Lecture Style Level = {_style_label(style_level)}，只控制“怎么讲”：{_style_instruction(style_level, language)}\n"
            f"- 组合语义：{_combination_instruction(preset.level, style_level, language)}\n"
            "Compression policy:\n"
            f"- {preset.compression_instruction}\n"
            "- 优先删除：模板过渡、重复背景、空泛总结、“这一部分讲什么”的元描述、低信息量套话。\n"
            "- 优先保留：核心概念、关键机制、关键公式或关键论证、关键推导桥梁句、方法之间为什么衔接的逻辑。\n"
        )

    return (
        "Parameter contract:\n"
        f"- Explanation Depth = {_depth_label(preset.level)} controls only how much to cover: {preset.depth_instruction}\n"
        f"- Lecture Style Level = {_style_label(style_level)} controls only how to explain: {_style_instruction(style_level, language)}\n"
        f"- Combination meaning: {_combination_instruction(preset.level, style_level, language)}\n"
        "Compression policy:\n"
        f"- {preset.compression_instruction}\n"
        "- Delete first: template transitions, repeated background, vague summaries, meta descriptions of what the section covers, and low-information filler.\n"
        "- Preserve first: core concepts, key mechanisms, essential formulas or arguments, derivation bridge sentences, and the logic explaining why methods or ideas connect.\n"
    )


async def generate_chunk_markdown(
    chunk: GenerationChunk,
    pages: list[PageIndexPage],
    preset: DifficultyPreset,
    language: str = "en",
    style_level: ExplanationStyleLevel = ExplanationStyleLevel.MEDIUM,
    document_plan: DocumentPlan | None = None,
) -> str:
    page_lookup = _pages_by_number(pages)
    context = _build_page_context(page_lookup, chunk.page_numbers, chunk.evidence)
    if not context.strip():
        return _fallback_markdown(chunk, page_lookup, language)

    heading = "#" * max(2, min(chunk.heading_level, 5))
    prompt = (
        f"Write one Markdown-first study-note section in {_language_name(language)}.\n"
        f"The final note content itself must be in {_language_name(language)}; this is independent of UI language.\n"
        "Return Markdown only. Write a real online lecture note section, not a page digest, slide script, "
        "summary expansion, or fixed template.\n"
        f"Section path: {' > '.join(chunk.section_path)}\n"
        f"Page range: {chunk.page_start}-{chunk.page_end}\n"
        f"Section summary: {chunk.section_summary}\n"
        f"Required heading: {heading} {' / '.join(chunk.section_path)}\n"
        f"{_prompt_contract(preset, style_level, language)}\n"
        f"Document outline:\n{_document_outline(document_plan)}\n\n"
        "Requirements:\n"
        f"- Start exactly with the required Markdown heading.\n"
        "- Organize by the knowledge thread of this section: what problem/concept is being explained, what mechanism or argument makes it work, and why the ideas connect.\n"
        "- Do not average-compress every page. Select evidence according to the depth/style contract above.\n"
        '- Do not write page-by-page explanations, presentation speech, or template phrases such as "this section introduces".\n'
        "- Use natural explanatory paragraphs as the main body. Lists, tables, and callouts are supporting material only.\n"
        "- Use ### subheadings only when they reflect real conceptual turns, not a fixed Definition/Example/Summary template.\n"
        "- When a formula, theorem, algorithm, mechanism, causal chain, or argument is essential, explain the problem it solves, why it is introduced, and what role it plays in the method.\n"
        "- For formulas or algorithmic updates, do not merely quote the expression. When the evidence supports it, derive it step by step from the preceding definition, objective, constraint, or mechanism; otherwise explain the missing derivation assumption clearly.\n"
        "- For algorithms, identify the input/state/objective/update, why each update is shaped that way, and how the update reduces the original problem.\n"
        "- For mechanisms, explain the chain from condition to process to consequence, including the point where the mechanism changes the outcome.\n"
        "- For High style, increase rigor through precise definitions, boundaries, mechanisms, and argument quality; do not force formulas for non-mathematical material.\n"
        "- Use numbered lists for algorithms, procedures, or causal sequences."
        "- End with a short section summary callout that states the knowledge takeaway, not a generic recap.\n"
        "- Markdown math contract: inline math must use `$...$`; display math and multi-step derivations must use `$$...$$` on their own lines.\n"
        "- Never use unsupported wrappers such as `\\(...\\)` or `\\[...\\]`, and never mix wrappers like `$$\\(...\\)$$`.\n"
        "- For function names, API names, code-like expressions, or pseudocode in prose, use backticks such as `f(x)` or `softmax(x)`, not math delimiters.\n"
        "- Keep grounding traceable by mentioning source page ranges only when it clarifies evidence.\n\n"
        "- Use bold sparingly for key concepts, mechanism names, theorem names, algorithm names, and likely confusion points. Do not overuse bold. Prefer 1–3 bold phrases per paragraph and never bold full sentences."
        "- When appropriate, briefly point out one common misunderstanding, confusion, or misuse of the concept, and clarify it directly."
        f"Section-grounded evidence:\n{context}"
    )

    try:
        response = await llm_complete(
            prompt=prompt,
            system_prompt=(
                "You turn a PageIndex-style section plan and page evidence into coherent online lecture notes. "
                "You never produce slide narration or page-by-page commentary."
            ),
            temperature=0.35,
        )
        cleaned = normalize_structure_note_markdown(_strip_markdown_fence(response))
        return cleaned if cleaned else _fallback_markdown(chunk, page_lookup, language)
    except Exception:
        return _fallback_markdown(chunk, page_lookup, language)


def inject_image_placeholders(
    chunks: list[GenerationChunk],
    pages: list[PageIndexPage],
    purpose: str,
) -> list[GenerationChunk]:
    page_lookup = _pages_by_number(pages)
    for chunk in chunks:
        image_pages = [
            page_number
            for page_number in chunk.page_numbers
            if page_lookup.get(page_number) and page_lookup[page_number].image_candidates
        ]
        if not image_pages:
            continue
        page_hint = image_pages[0]
        placeholder_id = f"{chunk.chunk_id}-image-1"
        token = f"[[IMAGE_PLACEHOLDER:{placeholder_id}:{page_hint}:{purpose}]]"
        if token not in chunk.markdown:
            chunk.markdown = f"{chunk.markdown.rstrip()}\n\n{token}\n"
        chunk.placeholder_ids.append(placeholder_id)
    return chunks
