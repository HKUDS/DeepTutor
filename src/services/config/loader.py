#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Configuration Loader
====================

Unified configuration loading for all DeepTutor modules.
Provides YAML configuration loading, path resolution, and language parsing.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Optional

import yaml

# PROJECT_ROOT points to the actual project root directory (DeepTutor/)
# Path(__file__) = src/services/config/loader.py
# .parent = src/services/config/
# .parent.parent = src/services/
# .parent.parent.parent = src/
# .parent.parent.parent.parent = DeepTutor/ (project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Deep merge two dictionaries, values in override will override values in base

    Args:
        base: Base configuration
        override: Override configuration

    Returns:
        Merged configuration
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge dictionaries
            result[key] = _deep_merge(result[key], value)
        else:
            # Direct override
            result[key] = value

    return result


def load_config_with_main(config_file: str, project_root: Optional[Path] = None) -> dict[str, Any]:
    """
    Load configuration file, automatically merge with main.yaml common configuration

    Args:
        config_file: Sub-module configuration file name (e.g., "solve_config.yaml")
        project_root: Project root directory (if None, will try to auto-detect)

    Returns:
        Merged configuration dictionary
    """
    if project_root is None:
        project_root = PROJECT_ROOT

    config_dir = project_root / "config"

    # 1. Load main.yaml (common configuration)
    main_config = {}
    main_config_path = config_dir / "main.yaml"
    if main_config_path.exists():
        try:
            with open(main_config_path, encoding="utf-8") as f:
                main_config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"⚠️ Failed to load main.yaml: {e}")

    # 2. Load sub-module configuration file
    module_config = {}
    module_config_path = config_dir / config_file
    if module_config_path.exists():
        try:
            with open(module_config_path, encoding="utf-8") as f:
                module_config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"⚠️ Failed to load {config_file}: {e}")

    # 3. Merge configurations: main.yaml as base, sub-module config overrides
    merged_config = _deep_merge(main_config, module_config)

    return merged_config


def get_path_from_config(config: dict[str, Any], path_key: str, default: str = None) -> str:
    """
    Get path from configuration, supports searching in paths and system

    Args:
        config: Configuration dictionary
        path_key: Path key name (e.g., "log_dir", "workspace")
        default: Default value

    Returns:
        Path string
    """
    # Priority: search in paths
    if "paths" in config and path_key in config["paths"]:
        return config["paths"][path_key]

    # Search in system (backward compatibility)
    if "system" in config and path_key in config["system"]:
        return config["system"][path_key]

    # Search in tools (e.g., run_code.workspace)
    if "tools" in config:
        if path_key == "workspace" and "run_code" in config["tools"]:
            return config["tools"]["run_code"].get("workspace", default)

    return default


def parse_language(language: Any) -> str:
    """
    Unified language configuration parser, supports multiple input formats

    Supported language representations:
    - English: "en", "english", "English"
    - Chinese: "zh", "chinese", "Chinese"

    Args:
        language: Language configuration value (can be "zh"/"en"/"Chinese"/"English" etc.)

    Returns:
        Standardized language code: 'zh' or 'en', defaults to 'zh'
    """
    if not language:
        return "zh"

    if isinstance(language, str):
        lang_lower = language.lower()
        if lang_lower in ["en", "english"]:
            return "en"
        if lang_lower in ["zh", "chinese"]:
            return "zh"

    return "zh"  # Default Chinese


def get_agent_params(module_name: str) -> dict:
    """
    Get agent parameters (temperature, max_tokens) for a specific module.

    This function loads parameters from config/agents.yaml which serves as the
    SINGLE source of truth for all agent temperature and max_tokens settings.

    Args:
        module_name: Module name, one of:
            - "guide": Guide module agents
            - "solve": Solve module agents
            - "research": Research module agents
            - "question": Question module agents
            - "ideagen": IdeaGen module agents
            - "co_writer": CoWriter module agents
            - "narrator": Narrator agent (independent, for TTS)

    Returns:
        dict: Dictionary containing:
            - temperature: float, default 0.5
            - max_tokens: int, default 4096

    Example:
        >>> params = get_agent_params("guide")
        >>> params["temperature"]  # 0.5
        >>> params["max_tokens"]   # 8192
    """
    # Default values
    defaults = {
        "temperature": 0.5,
        "max_tokens": 4096,
    }

    # Try to load from agents.yaml
    try:
        config_path = PROJECT_ROOT / "config" / "agents.yaml"

        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                agents_config = yaml.safe_load(f) or {}

            if module_name in agents_config:
                module_config = agents_config[module_name]
                return {
                    "temperature": module_config.get("temperature", defaults["temperature"]),
                    "max_tokens": module_config.get("max_tokens", defaults["max_tokens"]),
                }
    except Exception as e:
        print(f"⚠️ Failed to load agents.yaml: {e}, using defaults")

    return defaults


@dataclass
class PPTConfig:
    """PPT generation configuration."""

    model: str
    api_key: str
    base_url: str
    binding: str = "openai"
    temperature: float = 0.4
    max_tokens: int = 2000
    max_slides: int = 15
    default_style_prompt: str = ""
    style_templates: list[dict[str, str]] = field(default_factory=list)


@dataclass
class BananaPptOutlineConfig:
    """BananaPPT outline generation settings."""

    temperature: float = 0.4
    max_tokens: int = 4000
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    binding: str = ""


@dataclass
class BananaPptImageConfig:
    """BananaPPT image generation settings."""

    model: str
    api_key: str
    base_url: str
    binding: str = "gemini"
    aspect_ratio: str = "16:9"


@dataclass
class BananaPptConfig:
    """BananaPPT configuration for frontend export flow."""

    enabled: bool = False
    max_slides: int = 15
    outline: BananaPptOutlineConfig = field(default_factory=BananaPptOutlineConfig)
    image: BananaPptImageConfig = field(
        default_factory=lambda: BananaPptImageConfig(
            model="", api_key="", base_url="", binding="gemini", aspect_ratio="16:9"
        )
    )
    style_templates: list[dict[str, str]] = field(default_factory=list)


def get_ppt_config(project_root: Optional[Path] = None) -> PPTConfig:
    """
    Get PPT-specific LLM configuration with fallback chain.

    Priority:
    1. main.yaml: export.ppt section
    2. Environment variables: PPT_MODEL, PPT_API_KEY, PPT_BASE_URL
    3. Default LLM config (from LLM_* env vars)

    Args:
        project_root: Project root directory (if None, will use PROJECT_ROOT)

    Returns:
        PPTConfig with resolved configuration
    """
    if project_root is None:
        project_root = PROJECT_ROOT

    # Load main.yaml config
    config = load_config_with_main("main.yaml", project_root)
    ppt_config = config.get("export", {}).get("ppt", {})

    # Helper to get value with priority: yaml -> env -> default
    def _get_value(yaml_key: str, env_key: str, default: Any = "") -> Any:
        yaml_val = ppt_config.get(yaml_key)
        if yaml_val:  # YAML value is not empty
            return yaml_val
        env_val = os.getenv(env_key)
        if env_val:  # Env value exists
            return env_val.strip().strip("\"'")
        return default

    # Get PPT-specific config, fallback to default LLM env vars
    model = _get_value("model", "PPT_MODEL", "") or os.getenv("LLM_MODEL", "")
    api_key = _get_value("api_key", "PPT_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    base_url = _get_value("base_url", "PPT_BASE_URL", "") or os.getenv("LLM_HOST", "")
    binding = _get_value("binding", "PPT_BINDING", "openai")

    # Get generation parameters
    temperature = float(ppt_config.get("temperature", 0.4))
    max_tokens = int(ppt_config.get("max_tokens", 2000))
    max_slides = int(ppt_config.get("max_slides", 15))
    default_style_prompt = ppt_config.get("default_style_prompt", "")
    style_templates = ppt_config.get("style_templates", []) or []

    return PPTConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        binding=binding,
        temperature=temperature,
        max_tokens=max_tokens,
        max_slides=max_slides,
        default_style_prompt=default_style_prompt,
        style_templates=style_templates,
    )


def get_banana_ppt_config(project_root: Optional[Path] = None) -> BananaPptConfig:
    """
    Get BananaPPT configuration with fallback chain.

    Priority:
    1. main.yaml: export.banana_ppt section
    2. Environment variables for image config

    Args:
        project_root: Project root directory (if None, will use PROJECT_ROOT)

    Returns:
        BananaPptConfig with resolved configuration
    """
    if project_root is None:
        project_root = PROJECT_ROOT

    config = load_config_with_main("main.yaml", project_root)
    export_config = config.get("export", {})
    banana_config = export_config.get("banana_ppt", {}) or {}
    ppt_config = export_config.get("ppt", {}) or {}

    outline_cfg = banana_config.get("outline", {}) or {}
    image_cfg = banana_config.get("image", {}) or {}

    def _get_value(cfg: dict[str, Any], yaml_key: str, env_key: str, default: Any = "") -> Any:
        yaml_val = cfg.get(yaml_key)
        if yaml_val:
            return yaml_val
        env_val = os.getenv(env_key)
        if env_val:
            return env_val.strip().strip("\"'")
        return default

    def _get_value_env_first(
        cfg: dict[str, Any], yaml_key: str, env_key: str, default: Any = ""
    ) -> Any:
        env_val = os.getenv(env_key)
        if env_val:
            return env_val.strip().strip("\"'")
        yaml_val = cfg.get(yaml_key)
        if yaml_val:
            return yaml_val
        return default

    enabled = bool(banana_config.get("enabled", False))
    max_slides = int(banana_config.get("max_slides", ppt_config.get("max_slides", 15)))
    style_templates = banana_config.get("style_templates")
    if style_templates is None:
        style_templates = ppt_config.get("style_templates", []) or []

    outline = BananaPptOutlineConfig(
        temperature=float(outline_cfg.get("temperature", 0.4)),
        max_tokens=int(outline_cfg.get("max_tokens", 4000)),
        model=str(outline_cfg.get("model", "")).strip(),
        api_key=str(outline_cfg.get("api_key", "")).strip(),
        base_url=str(outline_cfg.get("base_url", "")).strip(),
        binding=str(outline_cfg.get("binding", "")).strip(),
    )

    image = BananaPptImageConfig(
        model=_get_value_env_first(image_cfg, "model", "BANANA_PPT_IMAGE_MODEL", ""),
        api_key=_get_value_env_first(image_cfg, "api_key", "BANANA_PPT_IMAGE_API_KEY", ""),
        base_url=_get_value_env_first(
            image_cfg, "base_url", "BANANA_PPT_IMAGE_BASE_URL", ""
        ),
        binding=_get_value_env_first(
            image_cfg, "binding", "BANANA_PPT_IMAGE_BINDING", "gemini"
        ),
        aspect_ratio=_get_value_env_first(
            image_cfg, "aspect_ratio", "BANANA_PPT_IMAGE_ASPECT_RATIO", "16:9"
        ),
    )

    return BananaPptConfig(
        enabled=enabled,
        max_slides=max_slides,
        outline=outline,
        image=image,
        style_templates=style_templates,
    )


__all__ = [
    "PROJECT_ROOT",
    "load_config_with_main",
    "get_path_from_config",
    "parse_language",
    "get_agent_params",
    "get_ppt_config",
    "get_banana_ppt_config",
    "PPTConfig",
    "BananaPptConfig",
    "BananaPptOutlineConfig",
    "BananaPptImageConfig",
    "_deep_merge",
]
