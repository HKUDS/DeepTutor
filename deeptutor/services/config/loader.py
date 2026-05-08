#!/usr/bin/env python
"""
Configuration Loader
====================

Unified configuration loading for all DeepTutor modules.
Provides YAML configuration loading, path resolution, and language parsing.
"""

import asyncio
from pathlib import Path
from typing import Any

import yaml

from deeptutor.services.path_service import get_path_service

# PROJECT_ROOT points to the actual project root directory (DeepTutor/)
# Path(__file__) = deeptutor/services/config/loader.py
# .parent = deeptutor/services/config/
# .parent.parent = deeptutor/services/
# .parent.parent.parent = deeptutor/
# .parent.parent.parent.parent = DeepTutor/ (project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_runtime_settings_dir(project_root: Path | None = None) -> Path:
    """Return the canonical runtime settings directory under ``data/user/settings``."""
    root = project_root or PROJECT_ROOT
    return root / "data" / "user" / "settings"


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


def _load_yaml_file(file_path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    with open(file_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _inject_runtime_paths(config: dict[str, Any]) -> dict[str, Any]:
    """Expose canonical runtime paths without treating YAML paths as user-editable state."""
    path_service = get_path_service()
    normalized = dict(config or {})
    tools = dict(normalized.get("tools", {}) or {})
    run_code = dict(tools.get("run_code", {}) or {})
    run_code["workspace"] = str(path_service.get_chat_feature_dir("_detached_code_execution"))
    tools["run_code"] = run_code
    normalized["tools"] = tools
    normalized["paths"] = {
        "user_data_dir": str(path_service.get_user_root()),
        "knowledge_bases_dir": str(path_service.get_knowledge_bases_root()),
        "user_log_dir": str(path_service.get_logs_dir()),
        "performance_log_dir": str(path_service.get_logs_dir() / "performance"),
        "question_output_dir": str(path_service.get_chat_feature_dir("deep_question")),
        "research_output_dir": str(path_service.get_research_dir()),
        "research_reports_dir": str(path_service.get_research_reports_dir()),
        "solve_output_dir": str(path_service.get_chat_feature_dir("deep_solve")),
    }
    return normalized


async def _load_yaml_file_async(file_path: Path) -> dict[str, Any]:
    """Async version of _load_yaml_file."""
    return await asyncio.to_thread(_load_yaml_file, file_path)


def resolve_config_path(
    config_file: str,
    project_root: Path | None = None,
) -> tuple[Path, bool]:
    """
    Resolve *config_file* inside ``data/user/settings/``.

    Returns:
        ``(path, False)``

    Raises:
        FileNotFoundError: If the requested config does not exist.
    """
    if project_root is None:
        project_root = PROJECT_ROOT

    settings_dir = get_runtime_settings_dir(project_root)
    config_path = settings_dir / config_file
    if config_path.exists():
        return config_path, False
    raise FileNotFoundError(
        f"Configuration file not found: {config_file} (expected under {settings_dir})"
    )


def load_config_with_main(config_file: str, project_root: Path | None = None) -> dict[str, Any]:
    """
    Load configuration file, automatically merge with main.yaml common configuration

    Args:
        config_file: Configuration file name (e.g., "main.yaml")
        project_root: Project root directory (if None, will try to auto-detect)

    Returns:
        Merged configuration dictionary
    """
    if project_root is None:
        project_root = PROJECT_ROOT

    config_path, _ = resolve_config_path(config_file, project_root)
    return _inject_runtime_paths(_load_yaml_file(config_path))


async def load_config_with_main_async(
    config_file: str, project_root: Path | None = None
) -> dict[str, Any]:
    """
    Async version of load_config_with_main for non-blocking file operations.

    Load configuration file, automatically merge with main.yaml common configuration

    Args:
        config_file: Configuration file name (e.g., "main.yaml")
        project_root: Project root directory (if None, will try to auto-detect)

    Returns:
        Merged configuration dictionary
    """
    if project_root is None:
        project_root = PROJECT_ROOT

    config_path, _ = resolve_config_path(config_file, project_root)
    return _inject_runtime_paths(await _load_yaml_file_async(config_path))


def get_path_from_config(config: dict[str, Any], path_key: str, default: str = None) -> str:
    """
    Get path from configuration.

    Args:
        config: Configuration dictionary
        path_key: Path key name (e.g., "log_dir", "workspace")
        default: Default value

    Returns:
        Path string
    """
    injected = _inject_runtime_paths(config)
    if "paths" in injected and path_key in injected["paths"]:
        return injected["paths"][path_key]
    if path_key == "workspace":
        return injected.get("tools", {}).get("run_code", {}).get("workspace", default)
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
        if lang_lower in ["zh", "chinese", "cn"]:
            return "zh"

    return "zh"  # Default Chinese


def get_agent_params(module_name: str) -> dict:
    """
    Get agent parameters (temperature, max_tokens) for a specific module.

    This function loads parameters from config/agents.yaml which serves as the
    SINGLE source of truth for all agent temperature and max_tokens settings.

    Args:
        module_name: Module name, one of:
            - "solve": Solve module agents
            - "research": Research module agents
            - "question": Question module agents
            - "brainstorm": Brainstorm tool settings
            - "co_writer": CoWriter module agents
            - "narrator": Narrator agent (independent, for TTS)
            - "llm_probe": Settings → LLM diagnostic probe

    Returns:
        dict: Dictionary containing:
            - temperature: float, default 0.5
            - max_tokens: int, default 4096

    Example:
        >>> params = get_agent_params("solve")
        >>> params["temperature"]  # 0.3
        >>> params["max_tokens"]   # 8192
    """
    defaults = {
        "temperature": 0.5,
        "max_tokens": 4096,
    }
    section_map = {
        "solve": ("capabilities", "solve"),
        "research": ("capabilities", "research"),
        "question": ("capabilities", "question"),
        "co_writer": ("capabilities", "co_writer"),
        "brainstorm": ("tools", "brainstorm"),
        "vision_solver": ("plugins", "vision_solver"),
        "math_animator": ("plugins", "math_animator"),
        "llm_probe": ("diagnostics", "llm_probe"),
    }
    path = get_runtime_settings_dir(PROJECT_ROOT) / "agents.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Missing required configuration file: {path}")
    section = section_map.get(module_name)
    if section is None:
        return defaults
    with open(path, encoding="utf-8") as f:
        agents_config = yaml.safe_load(f) or {}
    module_config: dict[str, Any] = agents_config
    for key in section:
        module_config = module_config.get(key, {})
    return {
        "temperature": module_config.get("temperature", defaults["temperature"]),
        "max_tokens": module_config.get("max_tokens", defaults["max_tokens"]),
    }


DEFAULT_CHAT_PARAMS: dict[str, Any] = {
    "temperature": 0.2,
    "responding": {"max_tokens": 8000},
    "answer_now": {"max_tokens": 8000},
    "thinking": {"max_tokens": 2000},
    "observing": {"max_tokens": 2000},
    "acting": {"max_tokens": 2000},
    "react_fallback": {"max_tokens": 1500},
}


def get_chat_params() -> dict[str, Any]:
    """
    Read ``capabilities.chat`` from agents.yaml with deep-merged defaults.

    Unlike :func:`get_agent_params`, the chat capability has per-stage
    sub-sections (``responding``, ``answer_now``, ``thinking``, ``observing``,
    ``acting``, ``react_fallback``), each with its own ``max_tokens``. A single
    ``temperature`` is shared across all stages.

    Returns:
        dict: Deep-merged chat configuration. Always contains every stage key
        from :data:`DEFAULT_CHAT_PARAMS` so callers can index without checks.
    """
    path = get_runtime_settings_dir(PROJECT_ROOT) / "agents.yaml"
    cfg: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            agents_config = yaml.safe_load(f) or {}
        cfg = (agents_config.get("capabilities", {}) or {}).get("chat", {}) or {}
    return _deep_merge(DEFAULT_CHAT_PARAMS, cfg)


__all__ = [
    "PROJECT_ROOT",
    "get_runtime_settings_dir",
    "load_config_with_main",
    "get_path_from_config",
    "parse_language",
    "get_agent_params",
    "get_chat_params",
    "DEFAULT_CHAT_PARAMS",
    "_deep_merge",
]
