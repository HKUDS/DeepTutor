# -*- coding: utf-8 -*-
"""
Knowledge Base Configuration Service
=====================================

Centralized configuration management for knowledge bases.
Stores KB-specific settings like RAG provider, search mode, etc.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.logging import get_logger

logger = get_logger("KBConfigService")

# Default config file path
DEFAULT_CONFIG_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "data"
    / "user"
    / "settings"
    / "knowledge_base_configs.json"
)


class KnowledgeBaseConfigService:
    """
    Service for managing knowledge base configurations.

    Provides a centralized way to store and retrieve KB-specific settings,
    separate from the per-KB metadata.json files.
    """

    _instance: Optional["KnowledgeBaseConfigService"] = None

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = self._load_config()

    @classmethod
    def get_instance(cls, config_path: Optional[Path] = None) -> "KnowledgeBaseConfigService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load KB config: {e}")

        # Return default config
        return {
            "configs": {},
            "default_kb": None,
            "global_defaults": {"rag_provider": "llamaindex", "search_mode": "hybrid"},
        }

    def _save_config(self):
        """Save configuration to file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save KB config: {e}")

    def get_kb_config(self, kb_name: str) -> Dict[str, Any]:
        """
        Get configuration for a specific knowledge base.

        Args:
            kb_name: Knowledge base name

        Returns:
            KB configuration dict with defaults applied
        """
        kb_config = self._config.get("configs", {}).get(kb_name, {})
        defaults = self._config.get("global_defaults", {})

        # Merge with defaults
        return {
            "rag_provider": kb_config.get("rag_provider")
            or defaults.get("rag_provider", "llamaindex"),
            "search_mode": kb_config.get("search_mode") or defaults.get("search_mode", "hybrid"),
            **kb_config,
        }

    def set_kb_config(self, kb_name: str, config: Dict[str, Any]):
        """
        Set configuration for a specific knowledge base.

        Args:
            kb_name: Knowledge base name
            config: Configuration dict
        """
        if "configs" not in self._config:
            self._config["configs"] = {}

        # Merge with existing config
        existing = self._config["configs"].get(kb_name, {})
        existing.update(config)
        self._config["configs"][kb_name] = existing

        self._save_config()
        logger.info(f"Updated config for KB '{kb_name}': {config}")

    def get_rag_provider(self, kb_name: str) -> str:
        """Get RAG provider for a knowledge base."""
        return self.get_kb_config(kb_name).get("rag_provider", "llamaindex")

    def set_rag_provider(self, kb_name: str, provider: str):
        """Set RAG provider for a knowledge base."""
        self.set_kb_config(kb_name, {"rag_provider": provider})

    def get_search_mode(self, kb_name: str) -> str:
        """Get search mode for a knowledge base."""
        return self.get_kb_config(kb_name).get("search_mode", "hybrid")

    def set_search_mode(self, kb_name: str, mode: str):
        """Set search mode for a knowledge base."""
        self.set_kb_config(kb_name, {"search_mode": mode})

    def delete_kb_config(self, kb_name: str):
        """Delete configuration for a knowledge base."""
        if "configs" in self._config and kb_name in self._config["configs"]:
            del self._config["configs"][kb_name]
            self._save_config()
            logger.info(f"Deleted config for KB '{kb_name}'")

    def get_all_configs(self) -> Dict[str, Any]:
        """Get all knowledge base configurations."""
        return self._config

    def set_global_defaults(self, defaults: Dict[str, Any]):
        """Set global default values."""
        if "global_defaults" not in self._config:
            self._config["global_defaults"] = {}

        self._config["global_defaults"].update(defaults)
        self._save_config()
        logger.info(f"Updated global defaults: {defaults}")

    def set_default_kb(self, kb_name: Optional[str]):
        """Set the default knowledge base."""
        self._config["default_kb"] = kb_name
        self._save_config()
        logger.info(f"Set default KB: {kb_name}")

    def get_default_kb(self) -> Optional[str]:
        """Get the default knowledge base name."""
        return self._config.get("default_kb")

    def sync_from_metadata(self, kb_name: str, kb_base_dir: Path):
        """
        Sync configuration from a KB's metadata.json file.

        Useful for migrating existing KBs to the centralized config.

        Args:
            kb_name: Knowledge base name
            kb_base_dir: Base directory for knowledge bases
        """
        metadata_file = kb_base_dir / kb_name / "metadata.json"

        if not metadata_file.exists():
            return

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # Extract relevant config from metadata
            config = {}
            if "rag_provider" in metadata and metadata["rag_provider"]:
                config["rag_provider"] = metadata["rag_provider"]

            if config:
                self.set_kb_config(kb_name, config)
                logger.info(f"Synced config for KB '{kb_name}' from metadata.json")

        except Exception as e:
            logger.warning(f"Failed to sync config from metadata for '{kb_name}': {e}")

    def sync_all_from_metadata(self, kb_base_dir: Path):
        """
        Sync configurations from all KBs' metadata.json files.

        Args:
            kb_base_dir: Base directory for knowledge bases
        """
        if not kb_base_dir.exists():
            return

        for kb_dir in kb_base_dir.iterdir():
            if kb_dir.is_dir() and kb_dir.name != "__pycache__":
                metadata_file = kb_dir / "metadata.json"
                if metadata_file.exists():
                    self.sync_from_metadata(kb_dir.name, kb_base_dir)


# Convenience function
def get_kb_config_service() -> KnowledgeBaseConfigService:
    """Get the knowledge base config service instance."""
    return KnowledgeBaseConfigService.get_instance()
