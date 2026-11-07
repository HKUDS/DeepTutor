# -*- coding: utf-8 -*-
"""
Services Layer
==============

Unified service layer for DeepTutor providing:
- LLM client and configuration
- Embedding client and configuration
- RAG pipelines and components
- Prompt management
- Web Search providers
- System setup utilities
- Configuration loading

Usage:
    from src.services.llm import get_llm_client
    from src.services.embedding import get_embedding_client
    from src.services.rag import get_pipeline
    from src.services.prompt import get_prompt_manager
    from src.services.search import web_search
    from src.services.setup import init_user_directories
    from src.services.config import load_config_with_main
"""

# Modules are lazy-loaded via __getattr__ to avoid importing optional
# dependencies (PyYAML, lightrag, llama_index, etc.) at package import time.
from importlib import import_module

__all__ = [
    "llm",
    "embedding",
    "rag",
    "prompt",
    "search",
    "setup",
    "session",
    "config",
    "PathService",
    "get_path_service",
    "BaseSessionManager",
]


def __getattr__(name: str):
    """Lazy import service modules and common service symbols."""
    if name in {"config", "llm", "prompt", "search", "setup", "session", "rag", "embedding"}:
        return import_module(f"{__name__}.{name}")
    if name in {"PathService", "get_path_service"}:
        module = import_module(f"{__name__}.path_service")
        return getattr(module, name)
    if name == "BaseSessionManager":
        module = import_module(f"{__name__}.session")
        return module.BaseSessionManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
