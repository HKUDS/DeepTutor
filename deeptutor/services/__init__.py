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
    from deeptutor.services.llm import get_llm_client
    from deeptutor.services.embedding import get_embedding_client
    from deeptutor.services.rag import get_pipeline
    from deeptutor.services.prompt import get_prompt_manager
    from deeptutor.services.search import web_search
    from deeptutor.services.setup import init_user_directories
    from deeptutor.services.config import load_config_with_main

    # LLM
    llm = get_llm_client()
    response = await llm.complete("Hello, world!")

    # Embedding
    embed = get_embedding_client()
    vectors = await embed.embed(["text1", "text2"])

    # RAG
    pipeline = get_pipeline("llamaindex")
    result = await pipeline.search("query", "kb_name")

    # Prompt
    pm = get_prompt_manager()
    prompts = pm.load_prompts("guide", "tutor_agent")

    # Search
    result = web_search("What is AI?")
"""

# Keep service package import side-effects minimal.
# Modules are lazy-loaded in __getattr__ to avoid circular imports.
from .path_service import PathService, get_path_service

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
    """Lazy import for modules that depend on heavy libraries."""
    import importlib

    if name == "llm":
        return importlib.import_module(f"{__name__}.llm")
    if name == "prompt":
        return importlib.import_module(f"{__name__}.prompt")
    if name == "search":
        return importlib.import_module(f"{__name__}.search")
    if name == "setup":
        return importlib.import_module(f"{__name__}.setup")
    if name == "session":
        return importlib.import_module(f"{__name__}.session")
    if name == "config":
        return importlib.import_module(f"{__name__}.config")
    if name == "rag":
        return importlib.import_module(f"{__name__}.rag")
    if name == "embedding":
        return importlib.import_module(f"{__name__}.embedding")
    if name == "BaseSessionManager":
        from .session import BaseSessionManager

        return BaseSessionManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
