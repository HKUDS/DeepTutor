# -*- coding: utf-8 -*-
"""
Unified Configuration Manager
=============================

Manages configurations for LLM, Embedding, TTS, and Search services.
Supports both .env defaults and user-defined configurations.
"""

from enum import Enum
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)

# Storage directory
SETTINGS_DIR = PROJECT_ROOT / "data" / "user" / "settings"


class ConfigType(str, Enum):
    """Configuration types."""

    LLM = "llm"
    EMBEDDING = "embedding"
    TTS = "tts"
    SEARCH = "search"


# Provider options for each service type
PROVIDER_OPTIONS = {
    ConfigType.LLM: [
        "openai",
        "anthropic",
        "azure_openai",
        "deepseek",
        "ollama",
        "lm_studio",
        "vllm",
    ],
    ConfigType.EMBEDDING: ["openai", "azure_openai", "ollama", "jina", "cohere", "huggingface"],
    ConfigType.TTS: ["openai", "azure_openai"],
    ConfigType.SEARCH: ["perplexity", "tavily", "exa", "jina", "serper", "baidu"],
}

# Environment variable mappings for each service type
ENV_VAR_MAPPINGS = {
    ConfigType.LLM: {
        "provider": "LLM_BINDING",
        "base_url": "LLM_HOST",
        "api_key": "LLM_API_KEY",
        "model": "LLM_MODEL",
        "api_version": "LLM_API_VERSION",
    },
    ConfigType.EMBEDDING: {
        "provider": "EMBEDDING_BINDING",
        "base_url": "EMBEDDING_HOST",
        "api_key": "EMBEDDING_API_KEY",
        "model": "EMBEDDING_MODEL",
        "dimensions": "EMBEDDING_DIMENSION",
        "api_version": "EMBEDDING_API_VERSION",
    },
    ConfigType.TTS: {
        "provider": "TTS_BINDING",
        "base_url": "TTS_URL",
        "api_key": "TTS_API_KEY",
        "model": "TTS_MODEL",
        "voice": "TTS_VOICE",
        "api_version": "TTS_BINDING_API_VERSION",
    },
    ConfigType.SEARCH: {
        "provider": "SEARCH_PROVIDER",
        "api_key": "SEARCH_API_KEY",  # Unified API key for all providers
    },
}


def _resolve_env_value(value: Any) -> Any:
    """
    Resolve a value that may reference an environment variable.

    If value is {"use_env": "VAR_NAME"}, returns os.environ.get("VAR_NAME").
    Otherwise, returns the value as-is.
    """
    if isinstance(value, dict) and "use_env" in value:
        env_var = value["use_env"]
        return os.environ.get(env_var, "")
    return value


def _get_env_value(env_var: str) -> Optional[str]:
    """Get and strip an environment variable value."""
    value = os.environ.get(env_var)
    if value:
        return value.strip().strip("\"'")
    return None


class UnifiedConfigManager:
    """
    Manages configurations for all service types.

    Each service type has:
    - A "default" configuration that comes from .env (cannot be deleted)
    - User-defined configurations that can be added/edited/deleted
    - An "active" configuration that is currently in use
    """

    _instance: Optional["UnifiedConfigManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UnifiedConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        self._initialized = True

        # Ensure default configs exist and are synced with env on startup
        self._ensure_default_configs()

    def _ensure_default_configs(self) -> None:
        """
        Ensure default configurations exist in storage files and sync with env.

        This method is called on startup to:
        1. Create a "default" config entry in each config file if it doesn't exist
        2. Sync the model/provider fields from env variables (these may change)
        3. Store base_url/api_key as {"use_env": "VAR_NAME"} references
        """
        for config_type in ConfigType:
            try:
                self._ensure_default_config_for_type(config_type)
            except Exception as e:
                logger.warning(f"Failed to ensure default config for {config_type.value}: {e}")

    def _ensure_default_config_for_type(self, config_type: ConfigType) -> None:
        """Ensure default config exists and is synced for a specific config type."""
        env_mapping = ENV_VAR_MAPPINGS.get(config_type, {})
        data = self._load_configs(config_type)

        # Find existing default config in the configs list
        default_config = None
        default_index = -1
        for i, cfg in enumerate(data.get("configs", [])):
            if cfg.get("id") == "default":
                default_config = cfg
                default_index = i
                break

        # Build the default config to store
        stored_default = self._build_stored_default_config(config_type, env_mapping)

        if default_config is None:
            # Add default config to the list
            if "configs" not in data:
                data["configs"] = []
            data["configs"].insert(0, stored_default)
            logger.info(f"Created default config for {config_type.value}")
        else:
            # Update only the dynamic fields (model, provider) from env
            # Keep other fields unchanged (they reference env vars)
            if config_type == ConfigType.LLM:
                default_config["model"] = _get_env_value(env_mapping.get("model")) or ""
                default_config["provider"] = _get_env_value(env_mapping.get("provider")) or "openai"
            elif config_type == ConfigType.EMBEDDING:
                default_config["model"] = _get_env_value(env_mapping.get("model")) or ""
                default_config["provider"] = _get_env_value(env_mapping.get("provider")) or "openai"
                dim_str = _get_env_value(env_mapping.get("dimensions"))
                default_config["dimensions"] = (
                    int(dim_str) if dim_str and dim_str.isdigit() else 3072
                )
            elif config_type == ConfigType.TTS:
                default_config["model"] = _get_env_value(env_mapping.get("model")) or ""
                default_config["provider"] = _get_env_value(env_mapping.get("provider")) or "openai"
                default_config["voice"] = _get_env_value(env_mapping.get("voice")) or "alloy"
            elif config_type == ConfigType.SEARCH:
                default_config["provider"] = (
                    _get_env_value(env_mapping.get("provider")) or "perplexity"
                )

            data["configs"][default_index] = default_config
            logger.debug(f"Updated default config for {config_type.value}")

        self._save_configs(config_type, data)

    def _build_stored_default_config(
        self, config_type: ConfigType, env_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        """Build the default configuration to be stored in JSON (with env references)."""
        base_config = {
            "id": "default",
            "name": "Default (from .env)",
            "is_default": True,
        }

        if config_type == ConfigType.LLM:
            return {
                **base_config,
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "base_url": {"use_env": "LLM_HOST"},
                "api_key": {"use_env": "LLM_API_KEY"},
                "api_version": {"use_env": "LLM_API_VERSION"},
            }

        elif config_type == ConfigType.EMBEDDING:
            dim_str = _get_env_value(env_mapping.get("dimensions"))
            return {
                **base_config,
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "dimensions": int(dim_str) if dim_str and dim_str.isdigit() else 3072,
                "base_url": {"use_env": "EMBEDDING_HOST"},
                "api_key": {"use_env": "EMBEDDING_API_KEY"},
                "api_version": {"use_env": "EMBEDDING_API_VERSION"},
            }

        elif config_type == ConfigType.TTS:
            return {
                **base_config,
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "voice": _get_env_value(env_mapping.get("voice")) or "alloy",
                "base_url": {"use_env": "TTS_URL"},
                "api_key": {"use_env": "TTS_API_KEY"},
                "api_version": {"use_env": "TTS_BINDING_API_VERSION"},
            }

        elif config_type == ConfigType.SEARCH:
            return {
                **base_config,
                "provider": _get_env_value(env_mapping.get("provider")) or "perplexity",
                "api_key": {"use_env": "SEARCH_API_KEY"},
            }

        return base_config

    def _get_storage_path(self, config_type: ConfigType) -> Path:
        """Get the storage file path for a config type."""
        return SETTINGS_DIR / f"{config_type.value}_configs.json"

    def _load_configs(self, config_type: ConfigType) -> Dict[str, Any]:
        """Load configurations from storage."""
        path = self._get_storage_path(config_type)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load {config_type.value} configs: {e}")
        return {"configs": [], "active_id": "default"}

    def _save_configs(self, config_type: ConfigType, data: Dict[str, Any]) -> bool:
        """Save configurations to storage."""
        path = self._get_storage_path(config_type)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            logger.error(f"Failed to save {config_type.value} configs: {e}")
            return False

    def _build_default_config(self, config_type: ConfigType) -> Dict[str, Any]:
        """Build the default configuration from environment variables."""
        env_mapping = ENV_VAR_MAPPINGS.get(config_type, {})

        if config_type == ConfigType.LLM:
            return {
                "id": "default",
                "name": "Default (from .env)",
                "is_default": True,
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "base_url": _get_env_value(env_mapping.get("base_url")) or "",
                "api_key": "***",  # Hidden for security
                "model": _get_env_value(env_mapping.get("model")) or "",
                "api_version": _get_env_value(env_mapping.get("api_version")),
            }

        elif config_type == ConfigType.EMBEDDING:
            dim_str = _get_env_value(env_mapping.get("dimensions"))
            return {
                "id": "default",
                "name": "Default (from .env)",
                "is_default": True,
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "base_url": _get_env_value(env_mapping.get("base_url")) or "",
                "api_key": "***",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "dimensions": int(dim_str) if dim_str and dim_str.isdigit() else 3072,
                "api_version": _get_env_value(env_mapping.get("api_version")),
            }

        elif config_type == ConfigType.TTS:
            return {
                "id": "default",
                "name": "Default (from .env)",
                "is_default": True,
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "base_url": _get_env_value(env_mapping.get("base_url")) or "",
                "api_key": "***",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "voice": _get_env_value(env_mapping.get("voice")) or "alloy",
                "api_version": _get_env_value(env_mapping.get("api_version")),
            }

        elif config_type == ConfigType.SEARCH:
            provider = _get_env_value(env_mapping.get("provider")) or "perplexity"
            return {
                "id": "default",
                "name": "Default (from .env)",
                "is_default": True,
                "provider": provider,
                "api_key": "***",
            }

        return {"id": "default", "name": "Default (from .env)", "is_default": True}

    def _get_default_config_resolved(self, config_type: ConfigType) -> Dict[str, Any]:
        """Get the default configuration with actual values resolved (for internal use)."""
        env_mapping = ENV_VAR_MAPPINGS.get(config_type, {})

        if config_type == ConfigType.LLM:
            return {
                "id": "default",
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "base_url": _get_env_value(env_mapping.get("base_url")) or "",
                "api_key": _get_env_value(env_mapping.get("api_key")) or "",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "api_version": _get_env_value(env_mapping.get("api_version")),
            }

        elif config_type == ConfigType.EMBEDDING:
            dim_str = _get_env_value(env_mapping.get("dimensions"))
            return {
                "id": "default",
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "base_url": _get_env_value(env_mapping.get("base_url")) or "",
                "api_key": _get_env_value(env_mapping.get("api_key")) or "",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "dimensions": int(dim_str) if dim_str and dim_str.isdigit() else 3072,
                "api_version": _get_env_value(env_mapping.get("api_version")),
            }

        elif config_type == ConfigType.TTS:
            return {
                "id": "default",
                "provider": _get_env_value(env_mapping.get("provider")) or "openai",
                "base_url": _get_env_value(env_mapping.get("base_url")) or "",
                "api_key": _get_env_value(env_mapping.get("api_key")) or "",
                "model": _get_env_value(env_mapping.get("model")) or "",
                "voice": _get_env_value(env_mapping.get("voice")) or "alloy",
                "api_version": _get_env_value(env_mapping.get("api_version")),
            }

        elif config_type == ConfigType.SEARCH:
            provider = _get_env_value(env_mapping.get("provider")) or "perplexity"
            return {
                "id": "default",
                "provider": provider,
                "api_key": _get_env_value(env_mapping.get("api_key")) or "",
            }

        return {"id": "default"}

    def _resolve_config(self, config: Dict[str, Any], config_type: ConfigType) -> Dict[str, Any]:
        """Resolve all {"use_env": ...} references in a configuration."""
        resolved = {}
        env_mapping = ENV_VAR_MAPPINGS.get(config_type, {})

        for key, value in config.items():
            if isinstance(value, dict) and "use_env" in value:
                env_var = value["use_env"]
                resolved[key] = _get_env_value(env_var) or ""
            else:
                resolved[key] = value

        return resolved

    def get_provider_options(self, config_type: ConfigType) -> List[str]:
        """Get available provider options for a config type."""
        return PROVIDER_OPTIONS.get(config_type, [])

    def list_configs(self, config_type: ConfigType) -> List[Dict[str, Any]]:
        """
        List all configurations for a service type.
        Includes the default config (from .env) and user-defined configs.

        For display purposes, the default config shows:
        - Current model/provider from env (dynamically refreshed)
        - base_url/api_key as "***" (hidden for security)
        """
        data = self._load_configs(config_type)
        configs = data.get("configs", [])
        active_id = data.get("active_id", "default")

        # Build a display version of the default config (with current env values)
        display_default = self._build_default_config(config_type)

        # Process all configs for display
        result = []
        has_default = False

        for cfg in configs:
            if cfg.get("id") == "default":
                # Use the dynamically built display config for default
                has_default = True
                display_cfg = display_default.copy()
                display_cfg["is_active"] = active_id == "default"
                result.append(display_cfg)
            else:
                # For user configs, create a display copy
                display_cfg = dict(cfg)
                # Hide api_key if it's not an env reference
                if "api_key" in display_cfg:
                    api_key = display_cfg["api_key"]
                    if not isinstance(api_key, dict):  # Not {"use_env": ...}
                        display_cfg["api_key"] = "***"
                display_cfg["is_active"] = cfg.get("id") == active_id
                result.append(display_cfg)

        # If no default config found in file, prepend the display default
        if not has_default:
            display_default["is_active"] = active_id == "default"
            result.insert(0, display_default)

        return result

    def get_config(self, config_type: ConfigType, config_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific configuration by ID."""
        if config_id == "default":
            return self._build_default_config(config_type)

        data = self._load_configs(config_type)
        for cfg in data.get("configs", []):
            if cfg.get("id") == config_id:
                return cfg
        return None

    def get_active_config(self, config_type: ConfigType) -> Optional[Dict[str, Any]]:
        """
        Get the currently active configuration with all values resolved.
        This is used internally when services need actual configuration values.
        """
        data = self._load_configs(config_type)
        active_id = data.get("active_id", "default")

        if active_id == "default":
            return self._get_default_config_resolved(config_type)

        for cfg in data.get("configs", []):
            if cfg.get("id") == active_id:
                return self._resolve_config(cfg, config_type)

        # Fallback to default if active config not found
        return self._get_default_config_resolved(config_type)

    def add_config(self, config_type: ConfigType, config: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new configuration."""
        data = self._load_configs(config_type)

        # Generate ID if not provided
        if "id" not in config:
            config["id"] = str(uuid.uuid4())[:8]

        # Ensure required fields
        config["is_default"] = False

        # Add to list
        data["configs"].append(config)
        self._save_configs(config_type, data)

        return config

    def update_config(
        self, config_type: ConfigType, config_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update an existing configuration."""
        if config_id == "default":
            return None  # Cannot update default config

        data = self._load_configs(config_type)

        for i, cfg in enumerate(data.get("configs", [])):
            if cfg.get("id") == config_id:
                # Update fields
                cfg.update(updates)
                cfg["id"] = config_id  # Preserve ID
                cfg["is_default"] = False  # Ensure it's not marked as default
                data["configs"][i] = cfg
                self._save_configs(config_type, data)
                return cfg

        return None

    def delete_config(self, config_type: ConfigType, config_id: str) -> bool:
        """Delete a configuration."""
        if config_id == "default":
            return False  # Cannot delete default config

        data = self._load_configs(config_type)
        original_len = len(data.get("configs", []))
        data["configs"] = [c for c in data.get("configs", []) if c.get("id") != config_id]

        if len(data["configs"]) < original_len:
            # If deleted config was active, switch to default
            if data.get("active_id") == config_id:
                data["active_id"] = "default"
            self._save_configs(config_type, data)
            return True

        return False

    def set_active_config(self, config_type: ConfigType, config_id: str) -> bool:
        """Set a configuration as active."""
        data = self._load_configs(config_type)

        # Verify config exists
        if config_id != "default":
            found = any(c.get("id") == config_id for c in data.get("configs", []))
            if not found:
                return False

        data["active_id"] = config_id
        success = self._save_configs(config_type, data)

        # Update environment variables for LightRAG compatibility when LLM config changes
        if success and config_type == ConfigType.LLM:
            self._update_openai_env_vars_for_lightrag()

        return success

    def _update_openai_env_vars_for_lightrag(self):
        """
        Update OPENAI_API_KEY and OPENAI_BASE_URL environment variables for LightRAG.

        LightRAG's internal functions read directly from os.environ["OPENAI_API_KEY"]
        instead of using passed parameters. This method ensures the environment
        variables are updated when the active LLM configuration changes.
        """
        try:
            config = self.get_active_config(ConfigType.LLM)
            if not config:
                return

            provider = config.get("provider", "openai")
            api_key = config.get("api_key", "")
            base_url = config.get("base_url", "")

            # Only set env vars for OpenAI-compatible providers
            if provider in ("openai", "azure_openai", "gemini", "deepseek"):
                if api_key:
                    os.environ["OPENAI_API_KEY"] = api_key
                    logger.debug("Updated OPENAI_API_KEY env var for LightRAG compatibility")

                if base_url:
                    os.environ["OPENAI_BASE_URL"] = base_url
                    logger.debug(f"Updated OPENAI_BASE_URL env var to {base_url}")

            # Reset LLM client singleton to pick up new configuration
            try:
                from src.services.llm import reset_llm_client

                reset_llm_client()
                logger.debug("Reset LLM client singleton after config change")
            except ImportError:
                pass

        except Exception as e:
            logger.warning(f"Failed to update OpenAI env vars: {e}")

    def get_env_status(self, config_type: ConfigType) -> Dict[str, bool]:
        """Check which environment variables are configured for a service type."""
        env_mapping = ENV_VAR_MAPPINGS.get(config_type, {})
        status = {}

        for field, env_var in env_mapping.items():
            if not env_var.endswith("_key"):  # Skip individual search provider keys
                status[field] = bool(_get_env_value(env_var))

        return status

    def get_default_config(self, config_type: ConfigType) -> Dict[str, Any]:
        """
        Get the default configuration with actual values resolved.
        Used for testing the default configuration.
        """
        return self._get_default_config_resolved(config_type)

    def resolve_config_env_values(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve all {"use_env": "VAR_NAME"} references in a user configuration.
        Returns a copy with actual values from environment variables.
        """
        resolved = dict(config)
        for key, value in config.items():
            if isinstance(value, dict) and "use_env" in value:
                env_var = value["use_env"]
                resolved[key] = _get_env_value(env_var) or ""
        return resolved


# Global instance
_config_manager: Optional[UnifiedConfigManager] = None


def get_config_manager() -> UnifiedConfigManager:
    """Get the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = UnifiedConfigManager()
    return _config_manager


# Convenience functions for services
def get_active_llm_config() -> Optional[Dict[str, Any]]:
    """Get the active LLM configuration."""
    return get_config_manager().get_active_config(ConfigType.LLM)


def get_active_embedding_config() -> Optional[Dict[str, Any]]:
    """Get the active embedding configuration."""
    return get_config_manager().get_active_config(ConfigType.EMBEDDING)


def get_active_tts_config() -> Optional[Dict[str, Any]]:
    """Get the active TTS configuration."""
    return get_config_manager().get_active_config(ConfigType.TTS)


def get_active_search_config() -> Optional[Dict[str, Any]]:
    """Get the active search configuration."""
    return get_config_manager().get_active_config(ConfigType.SEARCH)
