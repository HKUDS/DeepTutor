# -*- coding: utf-8 -*-
"""
Prompt Service
==============

Unified prompt management for all DeepTutor modules.

Usage:
    from src.services.prompt import get_prompt_manager, PromptManager

    # Get singleton manager
    pm = get_prompt_manager()

    # Load prompts for an agent
    prompts = pm.load_prompts("guide", "tutor_agent", language="en")

    # Get specific prompt
    system_prompt = pm.get_prompt(prompts, "system", "base")
"""

from .manager import PromptManager, get_prompt_manager

__all__ = [
    "PromptManager",
    "get_prompt_manager",
]
