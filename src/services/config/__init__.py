# -*- coding: utf-8 -*-
"""
Configuration Service
=====================

Provides three types of configuration:

1. **YAML Configuration (loader.py)** - For application settings from config/*.yaml
   - PROJECT_ROOT, load_config_with_main, get_path_from_config, parse_language, get_agent_params

2. **Unified Config Service (unified_config.py)** - For service configurations (LLM, Embedding, TTS, Search)
   - ConfigType, UnifiedConfigManager, get_config_manager
   - get_active_llm_config, get_active_embedding_config, get_active_tts_config, get_active_search_config

3. **Knowledge Base Config Service (knowledge_base_config.py)** - For KB-specific settings
   - KnowledgeBaseConfigService, get_kb_config_service
"""

# Re-export everything from loader.py (existing functionality)
# Export knowledge base config service
from .knowledge_base_config import (
    KnowledgeBaseConfigService,
    get_kb_config_service,
)
from .loader import (
    PROJECT_ROOT,
    get_agent_params,
    get_path_from_config,
    load_config_with_main,
    parse_language,
)

# Export new unified config service
from .unified_config import (
    ConfigType,
    UnifiedConfigManager,
    get_active_embedding_config,
    get_active_llm_config,
    get_active_search_config,
    get_active_tts_config,
    get_config_manager,
)

__all__ = [
    # From loader.py
    "PROJECT_ROOT",
    "load_config_with_main",
    "get_path_from_config",
    "parse_language",
    "get_agent_params",
    # From unified_config.py
    "ConfigType",
    "UnifiedConfigManager",
    "get_config_manager",
    "get_active_llm_config",
    "get_active_embedding_config",
    "get_active_tts_config",
    "get_active_search_config",
    # From knowledge_base_config.py
    "KnowledgeBaseConfigService",
    "get_kb_config_service",
]
