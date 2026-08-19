"""Configuration helpers backed by runtime files under data/user/settings."""

import importlib

from .knowledge_base_config import (
    KnowledgeBaseConfigService,
    get_kb_config_service,
)
from .launch_settings import LaunchSettings, load_launch_settings
from .loader import (
    DEFAULT_CHAT_PARAMS,
    PROJECT_ROOT,
    get_agent_params,
    get_chat_params,
    get_path_from_config,
    get_runtime_settings_dir,
    load_config_with_main,
    parse_language,
    resolve_config_path,
)
from .model_catalog import (
    CATALOG_SECRET_MASK,
    ModelCatalogService,
    get_model_catalog_service,
    redact_catalog_secrets,
    restore_catalog_secrets,
)
from .runtime_settings import (
    HTTP_KEEP_ALIVE_TIMEOUT,
    ChatAttachmentLimits,
    RuntimeSettingsService,
    ensure_runtime_settings_files,
    export_runtime_settings_to_env,
    get_chat_attachment_limits,
    get_runtime_settings_service,
    get_ws_max_size,
    load_auth_settings,
    load_graphrag_settings,
    load_integrations_settings,
    load_lightrag_settings,
    load_llamaindex_settings,
    load_mineru_settings,
    load_system_settings,
)

# Re-export the loader module itself for code paths that monkeypatch via the
# package namespace, e.g. ``deeptutor.services.config.loader.PROJECT_ROOT``.
loader = importlib.import_module(f"{__name__}.loader")

__all__ = [
    "LaunchSettings",
    "load_launch_settings",
    # From loader.py
    "PROJECT_ROOT",
    "get_runtime_settings_dir",
    "load_config_with_main",
    "resolve_config_path",
    "get_path_from_config",
    "parse_language",
    "get_agent_params",
    "get_chat_params",
    "DEFAULT_CHAT_PARAMS",
    "ResolvedLLMConfig",
    "ResolvedEmbeddingConfig",
    "ResolvedSearchConfig",
    "resolve_llm_runtime_config",
    "resolve_embedding_runtime_config",
    "resolve_search_runtime_config",
    "search_provider_state",
    "NANOBOT_LLM_PROVIDERS",
    "SUPPORTED_SEARCH_PROVIDERS",
    "DEPRECATED_SEARCH_PROVIDERS",
    "SEARCH_PROVIDERS",
    "SEARCH_FALLBACK_PROVIDER",
    "SearchProviderSpec",
    "search_provider_spec",
    "search_provider_credentials",
    "search_missing_credential",
    "search_fallback_candidates",
    "supported_search_providers_hint",
    # From knowledge_base_config.py
    "KnowledgeBaseConfigService",
    "get_kb_config_service",
    "ModelCatalogService",
    "get_model_catalog_service",
    "CATALOG_SECRET_MASK",
    "redact_catalog_secrets",
    "restore_catalog_secrets",
    "ConfigTestRunner",
    "TestRun",
    "get_config_test_runner",
    "HTTP_KEEP_ALIVE_TIMEOUT",
    "ChatAttachmentLimits",
    "RuntimeSettingsService",
    "ensure_runtime_settings_files",
    "export_runtime_settings_to_env",
    "get_chat_attachment_limits",
    "get_runtime_settings_service",
    "get_ws_max_size",
    "load_auth_settings",
    "load_graphrag_settings",
    "load_integrations_settings",
    "load_lightrag_settings",
    "load_llamaindex_settings",
    "load_mineru_settings",
    "load_system_settings",
]


def __getattr__(name: str):
    """Lazy-load provider_runtime exports to avoid circular imports."""
    if name in {
        "DEPRECATED_SEARCH_PROVIDERS",
        "NANOBOT_LLM_PROVIDERS",
        "SEARCH_FALLBACK_PROVIDER",
        "SEARCH_PROVIDERS",
        "SUPPORTED_SEARCH_PROVIDERS",
        "ResolvedLLMConfig",
        "ResolvedEmbeddingConfig",
        "ResolvedSearchConfig",
        "SearchProviderSpec",
        "resolve_embedding_runtime_config",
        "resolve_llm_runtime_config",
        "resolve_search_runtime_config",
        "search_fallback_candidates",
        "search_missing_credential",
        "search_provider_credentials",
        "search_provider_spec",
        "search_provider_state",
        "supported_search_providers_hint",
    }:
        provider_runtime = importlib.import_module(f"{__name__}.provider_runtime")

        return getattr(provider_runtime, name)
    if name in {"ConfigTestRunner", "TestRun", "get_config_test_runner"}:
        test_runner = importlib.import_module(f"{__name__}.test_runner")
        return getattr(test_runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
