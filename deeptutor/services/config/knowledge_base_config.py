from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import get_path_service
from deeptutor.services.rag.factory import DEFAULT_PROVIDER
from deeptutor.services.rag.index_versioning import list_kb_versions

logger = logging.getLogger(__name__)

# Legacy fallback only — frozen at admin scope at import time. Production code
# must enter through ``get_kb_config_service()`` (not used directly here, see
# ``deeptutor/services/config/__init__.py``) which resolves the path lazily.
DEFAULT_CONFIG_PATH = get_path_service().get_knowledge_bases_root() / "kb_config.json"


def _default_payload() -> dict[str, Any]:
    return {
        "defaults": {
            "default_kb": None,
            "rag_provider": DEFAULT_PROVIDER,
            "search_mode": "hybrid",
        },
        "knowledge_bases": {},
    }


class KnowledgeBaseConfigService:
    _instances: dict[str, "KnowledgeBaseConfigService"] = {}

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config = self._load_config()

    @classmethod
    def get_instance(cls, config_path: Path | None = None) -> "KnowledgeBaseConfigService":
        resolved = (config_path or get_path_service().get_knowledge_bases_root() / "kb_config.json").resolve()
        key = str(resolved)
        if key not in cls._instances:
            cls._instances[key] = cls(resolved)
        return cls._instances[key]

    def _load_config(self) -> dict[str, Any]:
        payload = _default_payload()
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle) or {}
                payload.update({k: v for k, v in loaded.items() if k != "defaults"})
                payload["defaults"].update(loaded.get("defaults", {}))
            except Exception as exc:
                logger.warning(f"Failed to load KB config: {exc}")
        payload.setdefault("knowledge_bases", {})
        payload.setdefault("defaults", _default_payload()["defaults"])
        payload = self._normalize_payload(payload)
        return payload

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = payload.setdefault("defaults", _default_payload()["defaults"])
        defaults["rag_provider"] = DEFAULT_PROVIDER

        knowledge_bases = payload.setdefault("knowledge_bases", {})
        kb_base_dir = self.config_path.parent
        for kb_name, config in knowledge_bases.items():
            if not isinstance(config, dict):
                continue

            raw_provider = config.get("rag_provider")
            config["rag_provider"] = DEFAULT_PROVIDER

            if isinstance(raw_provider, str) and raw_provider.strip().lower() not in {
                "",
                DEFAULT_PROVIDER,
            }:
                config["needs_reindex"] = True

            kb_dir = kb_base_dir / kb_name
            legacy_storage = kb_dir / "rag_storage"
            has_llamaindex_index = any(
                bool(version.get("ready")) for version in list_kb_versions(kb_dir)
            )
            if legacy_storage.exists() and legacy_storage.is_dir() and not has_llamaindex_index:
                config["needs_reindex"] = True

        return payload

    def _save(self) -> None:
        self._config = self._normalize_payload(self._config)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(self._config, handle, indent=2, ensure_ascii=False)

    def _ensure_kb(self, kb_name: str) -> dict[str, Any]:
        knowledge_bases = self._config.setdefault("knowledge_bases", {})
        if kb_name not in knowledge_bases:
            knowledge_bases[kb_name] = {
                "path": kb_name,
                "description": f"Knowledge base: {kb_name}",
            }
        return knowledge_bases[kb_name]

    def get_kb_config(self, kb_name: str) -> dict[str, Any]:
        defaults = dict(self._config.get("defaults", {}))
        kb_config = dict(self._config.get("knowledge_bases", {}).get(kb_name, {}))
        merged = {
            "default_kb": defaults.get("default_kb"),
            "rag_provider": DEFAULT_PROVIDER,
            "search_mode": kb_config.get("search_mode") or defaults.get("search_mode", "hybrid"),
            "needs_reindex": bool(kb_config.get("needs_reindex", False)),
            **kb_config,
        }
        merged["rag_provider"] = DEFAULT_PROVIDER
        return merged

    def set_kb_config(self, kb_name: str, config: dict[str, Any]) -> None:
        entry = self._ensure_kb(kb_name)
        entry.update(config)
        self._save()

    def get_rag_provider(self, kb_name: str) -> str:
        return DEFAULT_PROVIDER

    def set_rag_provider(self, kb_name: str, provider: str) -> None:
        self.set_kb_config(kb_name, {"rag_provider": DEFAULT_PROVIDER})

    def get_search_mode(self, kb_name: str) -> str:
        return str(self.get_kb_config(kb_name).get("search_mode", "hybrid"))

    def set_search_mode(self, kb_name: str, mode: str) -> None:
        self.set_kb_config(kb_name, {"search_mode": mode})

    def delete_kb_config(self, kb_name: str) -> None:
        knowledge_bases = self._config.get("knowledge_bases", {})
        if kb_name in knowledge_bases:
            del knowledge_bases[kb_name]
            self._save()

    def get_all_configs(self) -> dict[str, Any]:
        return self._config

    def set_global_defaults(self, defaults: dict[str, Any]) -> None:
        current = self._config.setdefault("defaults", _default_payload()["defaults"])
        current.update(defaults)
        self._save()

    def set_default_kb(self, kb_name: str | None) -> None:
        self._config.setdefault("defaults", _default_payload()["defaults"])["default_kb"] = kb_name
        self._save()

    def get_default_kb(self) -> str | None:
        return self._config.get("defaults", {}).get("default_kb")

    def sync_from_metadata(self, kb_name: str, kb_base_dir: Path) -> None:
        metadata_file = kb_base_dir / kb_name / "metadata.json"
        if not metadata_file.exists():
            return
        try:
            with open(metadata_file, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except Exception as exc:
            logger.warning(f"Failed to load KB metadata for {kb_name}: {exc}")
            return
        config: dict[str, Any] = {}
        if metadata.get("rag_provider"):
            raw_provider = metadata["rag_provider"]
            config["rag_provider"] = DEFAULT_PROVIDER
            if str(raw_provider).strip().lower() not in {"", DEFAULT_PROVIDER}:
                config["needs_reindex"] = True
        if metadata.get("search_mode"):
            config["search_mode"] = metadata["search_mode"]
        if config:
            self.set_kb_config(kb_name, config)

    def sync_all_from_metadata(self, kb_base_dir: Path) -> None:
        if not kb_base_dir.exists():
            return
        for kb_dir in kb_base_dir.iterdir():
            if kb_dir.is_dir() and not kb_dir.name.startswith("."):
                self.sync_from_metadata(kb_dir.name, kb_base_dir)


def get_kb_config_service() -> KnowledgeBaseConfigService:
    return KnowledgeBaseConfigService.get_instance(
        get_path_service().get_knowledge_bases_root() / "kb_config.json"
    )


__all__ = ["KnowledgeBaseConfigService", "get_kb_config_service"]
