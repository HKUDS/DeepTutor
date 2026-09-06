"""
Prompt Service
==============

Unified prompt management for all DeepTutor modules.

Usage:
    from deeptutor.services.prompt import get_prompt_manager, PromptManager

    # Get singleton manager
    pm = get_prompt_manager()

    # Load prompts for an agent
    prompts = pm.load_prompts("solve", "solve_agent", language="en")

    # Get specific prompt
    system_prompt = pm.get_prompt(prompts, "system", "base")
"""

from .language import (
    RESPONSE_LANGUAGE_CHOICES,
    append_language_directive,
    is_chinese,
    is_response_language_code,
    language_directive,
    language_label,
    normalize_language,
    prompt_locale,
)
from .lookup import prompt_text
from .manager import PromptManager, get_prompt_manager

__all__ = [
    "PromptManager",
    "RESPONSE_LANGUAGE_CHOICES",
    "append_language_directive",
    "get_prompt_manager",
    "is_chinese",
    "is_response_language_code",
    "language_directive",
    "language_label",
    "normalize_language",
    "prompt_locale",
    "prompt_text",
]
