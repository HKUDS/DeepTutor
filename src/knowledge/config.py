#!/usr/bin/env python
"""
Knowledge Base Path Configuration Module - Unified management of all paths
"""

import os
from pathlib import Path

# Project root directory (DeepTutor/)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# Knowledge base base directory
KNOWLEDGE_BASES_DIR = PROJECT_ROOT / "data" / "knowledge_bases"

# raganything module path
RAGANYTHING_PATH = PROJECT_ROOT.parent / "raganything" / "RAG-Anything"


# Ensure raganything path existence check
def check_raganything():
    """Check if raganything module exists"""
    return RAGANYTHING_PATH.exists()


# Environment variable configuration
def get_env_config():
    """Get environment variable configuration (unified read from env_config)"""
    try:
        from src.services.llm import get_llm_config

        cfg = get_llm_config()
        return {
            "api_key": cfg.api_key,
            "base_url": cfg.base_url,
        }
    except Exception:
        # Compatibility fallback: directly read environment variables
        return {
            "api_key": os.getenv("LLM_API_KEY"),
            "base_url": os.getenv("LLM_HOST"),
        }


# Add necessary paths to sys.path
def setup_paths():
    """Set Python module search paths"""
    import sys

    # Add project root directory
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    # Add raganything path (if exists)
    if check_raganything() and str(RAGANYTHING_PATH) not in sys.path:
        sys.path.insert(0, str(RAGANYTHING_PATH))


__all__ = [
    "KNOWLEDGE_BASES_DIR",
    "PROJECT_ROOT",
    "RAGANYTHING_PATH",
    "check_raganything",
    "get_env_config",
    "setup_paths",
]
