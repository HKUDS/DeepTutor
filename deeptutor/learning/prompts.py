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
    candidates = [lang, "zh" if lang != "zh" else "en"]
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
    return system_prompt, user_template.format(records_json=records_json)


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
]
