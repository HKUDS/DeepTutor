"""
Configuration Service
=====================

Unified configuration loading for all DeepTutor modules.

Usage:
    from src.services.config import load_config_with_main, PROJECT_ROOT

    # Load module configuration
    config = load_config_with_main("solve_config.yaml")

    # Get agent parameters
    params = get_agent_params("guide")
"""

from .loader import (
    BananaPptConfig,
    BananaPptImageConfig,
    BananaPptOutlineConfig,
    PROJECT_ROOT,
    _deep_merge,
    get_agent_params,
    get_banana_ppt_config,
    get_path_from_config,
    get_ppt_config,
    load_config_with_main,
    parse_language,
)

__all__ = [
    "PROJECT_ROOT",
    "load_config_with_main",
    "get_path_from_config",
    "parse_language",
    "get_agent_params",
    "get_ppt_config",
    "get_banana_ppt_config",
    "BananaPptConfig",
    "BananaPptOutlineConfig",
    "BananaPptImageConfig",
    "_deep_merge",
]
