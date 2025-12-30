#!/usr/bin/env python
"""
Unified Configuration Management
Combines environment variable configuration and YAML configuration loading.
"""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml

# PROJECT_ROOT points to the actual project root directory (DeepTutor/)
# Path(__file__) = src/core/core.py
# .parent = src/core/
# .parent.parent = src/
# .parent.parent.parent = DeepTutor/ (project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Load .env from project root directory
# DeepTutor.env takes precedence, then fallback to .env
load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)


# ============================================================================
# Environment Variable Configuration (from config.py)
# ============================================================================


def _to_int(value: str | None, default: int) -> int:
    """Convert environment variable to int, fallback to default value on failure."""
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _strip_value(value: str | None) -> str | None:
    """Remove leading/trailing whitespace and quotes from string."""
    if value is None:
        return None
    return value.strip().strip("\"'")


def get_llm_config() -> dict:
    """
    Return complete environment configuration for LLM.

    Returns:
        dict: Dictionary containing the following keys:
            - binding: LLM service provider
            - model: LLM model name
            - api_key: LLM API key
            - base_url: LLM API endpoint URL

    Raises:
        ValueError: If required configuration is missing
    """
    binding = _strip_value(os.getenv("LLM_BINDING", "openai"))
    model = _strip_value(os.getenv("LLM_MODEL"))
    api_key = _strip_value(os.getenv("LLM_BINDING_API_KEY"))
    base_url = _strip_value(os.getenv("LLM_BINDING_HOST"))

    # Validate required configuration
    if not model:
        raise ValueError("Error: LLM_MODEL not set, please configure it in .env file")
    if not api_key:
        raise ValueError("Error: LLM_BINDING_API_KEY not set, please configure it in .env file")
    if not base_url:
        raise ValueError("Error: LLM_BINDING_HOST not set, please configure it in .env file")

    return {
        "binding": binding,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }


def get_tts_config() -> dict:
    """
    Return complete environment configuration for TTS (Text-to-Speech).

    Returns:
        dict: Dictionary containing the following keys:
            - model: TTS model name
            - api_key: TTS API key
            - base_url: TTS API endpoint URL
            - voice: Default voice character

    Raises:
        ValueError: If required configuration is missing
    """
    model = _strip_value(os.getenv("TTS_MODEL"))
    api_key = _strip_value(os.getenv("TTS_API_KEY"))
    base_url = _strip_value(os.getenv("TTS_URL"))
    voice = _strip_value(os.getenv("TTS_VOICE", "alloy"))

    # Validate required configuration
    if not model:
        raise ValueError(
            "Error: TTS_MODEL not set, please configure it in .env file (e.g., tts-1 or tts-1-hd)"
        )
    if not api_key:
        raise ValueError("Error: TTS_API_KEY not set, please configure it in .env file")
    if not base_url:
        raise ValueError(
            "Error: TTS_URL not set, please configure it in .env file (e.g., https://api.openai.com/v1)"
        )

    return {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "voice": voice,
    }


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
        # PROJECT_ROOT is the project root directory, so config is at PROJECT_ROOT/config/
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


def get_embedding_config() -> dict:
    """
    Return complete environment configuration for embedding models.

    Returns:
        dict: Dictionary containing the following keys:
            - binding: Embedding service provider
            - model: Embedding model name
            - api_key: Embedding API key
            - base_url: Embedding API endpoint URL
            - dim: Embedding dimension
            - max_tokens: Maximum tokens for embedding

    Raises:
        ValueError: If required configuration is missing
    """
    binding = _strip_value(os.getenv("EMBEDDING_BINDING", "openai"))
    model = _strip_value(os.getenv("EMBEDDING_MODEL"))
    api_key = _strip_value(os.getenv("EMBEDDING_BINDING_API_KEY"))
    base_url = _strip_value(os.getenv("EMBEDDING_BINDING_HOST"))

    # Strict mode: All model configuration must come from .env, no automatic fallback or default inference
    if not model:
        raise ValueError("Error: EMBEDDING_MODEL not set, please configure it in .env file")
    if not api_key:
        raise ValueError(
            "Error: EMBEDDING_BINDING_API_KEY not set, please configure it in .env file"
        )
    if not base_url:
        raise ValueError("Error: EMBEDDING_BINDING_HOST not set, please configure it in .env file")

    # Get optional configuration
    dim = _to_int(_strip_value(os.getenv("EMBEDDING_DIM")), 3072)
    max_tokens = _to_int(_strip_value(os.getenv("EMBEDDING_MAX_TOKENS")), 8192)

    return {
        "binding": binding,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "dim": dim,
        "max_tokens": max_tokens,
    }


# ============================================================================
# YAML Configuration Loading (from config_loader.py)
# ============================================================================


def load_config_with_main(config_file: str, project_root: Path | None = None) -> dict[str, Any]:
    """
    Load configuration file, automatically merge with main.yaml common configuration

    Args:
        config_file: Sub-module configuration file name (e.g., "solve_config.yaml")
        project_root: Project root directory (if None, will try to auto-detect)

    Returns:
        Merged configuration dictionary
    """
    if project_root is None:
        # Try to infer project root from current file location
        # From src/core/core.py -> project root
        project_root = Path(__file__).parent.parent.parent

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


__all__ = [
    # Environment variable configuration
    "get_llm_config",
    "get_embedding_config",
    "get_tts_config",
    # Agent parameters
    "get_agent_params",
    # YAML configuration loading
    "load_config_with_main",
    "get_path_from_config",
    "_deep_merge",
    # Language parsing
    "parse_language",
]
