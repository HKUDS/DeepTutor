"""Focus-check prompt utilities."""

from __future__ import annotations

from typing import Literal

from deeptutor.immersive_reading.models import ReadingSection

FOCUS_CHECK_MAX_TOKENS = 4000
FOCUS_CHECK_PROMPT_VERSION = "focus-check-v4-structured"
FOCUS_CHECK_PASS_THRESHOLD = 65


def requires_focus_check(section: ReadingSection) -> bool:
    return section.checkpoint_kind != "none"


def detect_content_type(text: str) -> Literal["code_heavy", "conceptual"]:
    """Heuristic: code blocks or tables indicate API/tutorial, prose indicates conceptual."""
    if not text:
        return "conceptual"
    code_fences = text.count("```")
    tables = text.count("|---")
    lines = text.splitlines()
    non_blank = max(1, sum(1 for line in lines if line.strip()))
    code_ratio = (code_fences / 2) / non_blank
    table_ratio = tables / non_blank
    return "code_heavy" if code_ratio > 0.03 or table_ratio > 0.02 else "conceptual"


def build_focus_prompts(content_type: str, *, language: str) -> list[str]:
    zh = language.startswith("zh")
    if content_type == "code_heavy":
        return [
            "这节解决什么问题或实现什么功能？" if zh else "What problem does this section solve or what feature does it implement?",
            "列出 1-2 个关键 API、命令或配置项" if zh else "List 1-2 key APIs, commands, or config options",
            "你会怎么在实际中使用？" if zh else "How would you use this in practice?",
        ]
    return [
        "用自己的话概括核心概念" if zh else "Summarize the core concept in your own words",
        "这个概念和什么相关或依赖什么？" if zh else "What does this concept relate to or depend on?",
        "它解决了什么问题？" if zh else "What problem does it solve?",
    ]


def build_focus_system_prompt(language: str) -> str:
    zh = language.startswith("zh")
    return (
        "你是严谨但公平的精读检查员。判断读者是否真正读懂刚才的内容，而不是要求逐字复述。"
        "叙事作品看主要情节、关键因果和有原文依据的感受；技术或参考资料看核心概念、用途、结构或实际收获。"
        "技术资料不要求情绪反应，也不要求覆盖目录中的每个条目。允许措辞不同、选择性阅读和合理的个人解读。"
        "读者回答了若干结构化问题；逐条评估，并在 missing_points 中标注哪个问题答得不足。"
        f"只输出 JSON：{{\"passed\":bool,\"score\":0-100,\"feedback\":str,\"strengths\":[str],\"missing_points\":[str]}}。分数达到{FOCUS_CHECK_PASS_THRESHOLD}通常应通过。"
        if zh
        else "You are a rigorous but fair close-reading checker. Decide whether the reader genuinely understood "
        "the material without requiring verbatim recall. For narrative works, assess the main events, causality, "
        "and a text-grounded response. For technical or reference material, assess core concepts, purpose, structure, "
        "or practical takeaways; do not require an emotional reaction or exhaustive coverage of every TOC item. "
        "The reader answered structured questions; evaluate each one and note in missing_points which question was "
        "insufficiently addressed. Allow selective reading, different wording, and "
        f'reasonable interpretation. Return JSON only: {{"passed":bool,"score":0-100,"feedback":str,'
        f'"strengths":[str],"missing_points":[str]}}. A score of {FOCUS_CHECK_PASS_THRESHOLD} normally passes.'
    )


def build_focus_prompt(
    document_title: str, section_title: str, material: str, *, summary: str, reflection: str
) -> str:
    return (
        f"Book: {document_title}\nSection: {section_title}\n\nSource material:\n{material}\n\n"
        f"Reader's account of the main content:\n{summary}\n\n"
        f"Reader's additional notes (optional, may be empty):\n{reflection}"
    )

