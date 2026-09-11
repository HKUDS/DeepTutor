"""Mastery Path LLM prompt templates.

The prompt text lives in ``deeptutor/learning/prompts/{en,zh}.yaml`` so the
capability and API can follow the active UI language. The module-level constants
remain as the Chinese defaults for older tests/imports.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from deeptutor.services.config import parse_language
from deeptutor.services.prompt.language import append_language_directive

_PROMPT_DIR = Path(__file__).with_name("prompts")


def _get_nested(data: dict[str, Any], path: str, default: str = "") -> str:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict):
            return default
        value = value.get(part)
    return value if isinstance(value, str) else default


@lru_cache(maxsize=8)
def get_learning_prompts(language: str = "zh") -> dict[str, Any]:
    """Load localized Mastery Path LLM prompts."""
    lang = parse_language(language)
    # Regional codes reuse their base locale's file ("zh-tw" -> zh.yaml); a
    # language with no file of its own lands on English, not Chinese (#712).
    candidates = dict.fromkeys([lang, lang.split("-", 1)[0], "en", "zh"])
    for candidate in candidates:
        path = _PROMPT_DIR / f"{candidate}.yaml"
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def prompt_text(language: str, path: str, default: str = "") -> str:
    return _get_nested(get_learning_prompts(language), path, default)


def notebook_generation_prompts(language: str, records_json: str) -> tuple[str, str]:
    prompts = get_learning_prompts(language)
    system_prompt = _get_nested(prompts, "notebook.system", NOTEBOOK_SYSTEM)
    user_template = _get_nested(prompts, "notebook.user", NOTEBOOK_USER)
    # Only en/zh ship prompt files, so a Japanese learner is handed English
    # scaffolding. The directive — the same one book, quiz and Deep Research
    # already append — is what makes the answer come back in the language that
    # was actually asked for (#712).
    system_prompt = append_language_directive(system_prompt, parse_language(language))
    return system_prompt, user_template.format(records_json=records_json)


#: What a regeneration says when the learner asked for specific documents to
#: be included. Kept beside the templates rather than inside them because an
#: ordinary first draft must not carry an empty header for it.
_MUST_COVER_HEADERS = {
    "zh": "上一版路线漏掉了下面这些文件，这一版必须为每一个都安排位置：",
    "en": (
        "The previous route left these documents out. This one must give every "
        "single one of them a place:"
    ),
}


def _must_cover_block(language: str, must_cover: list[str]) -> str:
    if not must_cover:
        return ""
    zh = parse_language(language).lower().startswith("zh")
    header = _MUST_COVER_HEADERS["zh" if zh else "en"]
    listed = "\n".join(f"- {name}" for name in must_cover[:40])
    return f"\n{header}\n{listed}\n"


def topic_generation_prompts(
    language: str,
    *,
    name: str,
    goal: str,
    sources_json: str,
    module_limit: int = 8,
    must_cover: list[str] | None = None,
) -> tuple[str, str]:
    prompts = get_learning_prompts(language)
    system_prompt = _get_nested(
        prompts,
        "topic.system",
        "You design coherent mastery-learning routes and return JSON only.",
    )
    user_template = _get_nested(
        prompts,
        "topic.user",
        "Design a route for {name}: {goal}. Sources: {sources_json}",
    )
    system_prompt = append_language_directive(system_prompt, parse_language(language))
    # The cap travels in the prompt as well as being enforced after the fact:
    # a model told "3-8 modules" will not offer fourteen, so raising the
    # server-side limit alone would change nothing.
    system_prompt = system_prompt.replace("{module_limit}", str(max(3, int(module_limit or 8))))
    return system_prompt, user_template.format(
        name=name,
        goal=goal,
        sources_json=sources_json,
        must_cover_block=_must_cover_block(language, must_cover or []),
    )


def default_module_name(language: str, index: int) -> str:
    template = prompt_text(language, "notebook.default_module_name", "模块 {index}")
    return template.format(index=index)


DIAGNOSTIC_SYSTEM = prompt_text("zh", "diagnostic.system")
DIAGNOSTIC_USER = prompt_text("zh", "diagnostic.user")
EXPLAIN_SYSTEM = prompt_text("zh", "explain.system")
EXPLAIN_USER = prompt_text("zh", "explain.user")
FEYNMAN_SYSTEM = prompt_text("zh", "feynman.system")
FEYNMAN_USER = prompt_text("zh", "feynman.user")
PRACTICE_SYSTEM = prompt_text("zh", "practice.system")
PRACTICE_USER = prompt_text("zh", "practice.user")
ERROR_DIAGNOSIS_SYSTEM = prompt_text("zh", "error_diagnosis.system")
ERROR_DIAGNOSIS_USER = prompt_text("zh", "error_diagnosis.user")
REVIEW_SYSTEM = prompt_text("zh", "review.system")
REVIEW_USER = prompt_text("zh", "review.user")
NOTEBOOK_SYSTEM = prompt_text("zh", "notebook.system")
NOTEBOOK_USER = prompt_text("zh", "notebook.user")


__all__ = [
    "DIAGNOSTIC_SYSTEM",
    "DIAGNOSTIC_USER",
    "ERROR_DIAGNOSIS_SYSTEM",
    "ERROR_DIAGNOSIS_USER",
    "EXPLAIN_SYSTEM",
    "EXPLAIN_USER",
    "FEYNMAN_SYSTEM",
    "FEYNMAN_USER",
    "NOTEBOOK_SYSTEM",
    "NOTEBOOK_USER",
    "PRACTICE_SYSTEM",
    "PRACTICE_USER",
    "REVIEW_SYSTEM",
    "REVIEW_USER",
    "default_module_name",
    "get_learning_prompts",
    "notebook_generation_prompts",
    "prompt_text",
    "topic_generation_prompts",
]
