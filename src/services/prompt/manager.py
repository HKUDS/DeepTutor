#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unified Prompt Manager - Single source of truth for all prompt loading.
Supports multi-language, caching, and language fallbacks.
"""

from pathlib import Path
from typing import Any

import yaml

from src.services.config import PROJECT_ROOT, parse_language


class PromptManager:
    """Unified prompt manager with singleton pattern and global caching."""

    _instance: "PromptManager | None" = None
    _cache: dict[str, dict[str, Any]] = {}

    # Language fallback chain: if primary language not found, try alternatives
    LANGUAGE_FALLBACKS = {
        "zh": ["zh", "en"],
        "en": ["en", "zh"],
    }

    # Supported modules
    MODULES = ["research", "solve", "guide", "question", "ideagen", "co_writer"]

    def __new__(cls) -> "PromptManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_prompts(
        self,
        module_name: str,
        agent_name: str,
        language: str = "zh",
        subdirectory: str | None = None,
    ) -> dict[str, Any]:
        """
        Load prompts for an agent.

        Args:
            module_name: Module name (research, solve, guide, question, ideagen, co_writer)
            agent_name: Agent name (filename without .yaml)
            language: Language code ('zh' or 'en')
            subdirectory: Optional subdirectory (e.g., 'solve_loop' for solve module)

        Returns:
            Loaded prompt configuration dictionary
        """
        lang_code = parse_language(language)
        cache_key = self._build_cache_key(module_name, agent_name, lang_code, subdirectory)

        if cache_key in self._cache:
            return self._cache[cache_key]

        prompts = self._load_with_fallback(module_name, agent_name, lang_code, subdirectory)
        self._cache[cache_key] = prompts
        return prompts

    def _build_cache_key(
        self,
        module_name: str,
        agent_name: str,
        lang_code: str,
        subdirectory: str | None,
    ) -> str:
        """Build unique cache key."""
        subdir_part = f"_{subdirectory}" if subdirectory else ""
        return f"{module_name}_{agent_name}_{lang_code}{subdir_part}"

    def _load_with_fallback(
        self,
        module_name: str,
        agent_name: str,
        lang_code: str,
        subdirectory: str | None,
    ) -> dict[str, Any]:
        """Load prompt file with language fallback."""
        prompts_dir = PROJECT_ROOT / "src" / "agents" / module_name / "prompts"
        fallback_chain = self.LANGUAGE_FALLBACKS.get(lang_code, ["en"])

        for lang in fallback_chain:
            prompt_file = self._resolve_prompt_path(prompts_dir, lang, agent_name, subdirectory)
            if prompt_file and prompt_file.exists():
                try:
                    with open(prompt_file, encoding="utf-8") as f:
                        return yaml.safe_load(f) or {}
                except Exception as e:
                    print(f"Warning: Failed to load {prompt_file}: {e}")
                    continue

        print(f"Warning: No prompt file found for {module_name}/{agent_name}")
        return {}

    def _resolve_prompt_path(
        self,
        prompts_dir: Path,
        lang: str,
        agent_name: str,
        subdirectory: str | None,
    ) -> Path | None:
        """Resolve prompt file path, supporting subdirectory and recursive search."""
        lang_dir = prompts_dir / lang

        if not lang_dir.exists():
            return None

        # If subdirectory specified, look there first
        if subdirectory:
            direct_path = lang_dir / subdirectory / f"{agent_name}.yaml"
            if direct_path.exists():
                return direct_path

        # Try direct path
        direct_path = lang_dir / f"{agent_name}.yaml"
        if direct_path.exists():
            return direct_path

        # Recursive search in subdirectories
        found = list(lang_dir.rglob(f"{agent_name}.yaml"))
        if found:
            return found[0]

        return None

    def get_prompt(
        self,
        prompts: dict[str, Any],
        section: str,
        field: str | None = None,
        fallback: str = "",
    ) -> str:
        """
        Safely get prompt from loaded configuration.

        Args:
            prompts: Loaded prompt dictionary
            section: Top-level section name
            field: Optional nested field name
            fallback: Default value if not found

        Returns:
            Prompt string or fallback
        """
        if section not in prompts:
            return fallback

        value = prompts[section]

        if field is None:
            return value if isinstance(value, str) else fallback

        if isinstance(value, dict) and field in value:
            result = value[field]
            return result if isinstance(result, str) else fallback

        return fallback

    def clear_cache(self, module_name: str | None = None) -> None:
        """
        Clear cached prompts.

        Args:
            module_name: If provided, only clear cache for this module
        """
        if module_name:
            keys_to_remove = [k for k in self._cache if k.startswith(f"{module_name}_")]
            for key in keys_to_remove:
                del self._cache[key]
        else:
            self._cache.clear()

    def reload_prompts(
        self,
        module_name: str,
        agent_name: str,
        language: str = "zh",
        subdirectory: str | None = None,
    ) -> dict[str, Any]:
        """Force reload prompts, bypassing cache."""
        lang_code = parse_language(language)
        cache_key = self._build_cache_key(module_name, agent_name, lang_code, subdirectory)

        if cache_key in self._cache:
            del self._cache[cache_key]

        return self.load_prompts(module_name, agent_name, language, subdirectory)


# Global singleton instance
_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """Get the global PromptManager instance."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


__all__ = ["PromptManager", "get_prompt_manager"]
