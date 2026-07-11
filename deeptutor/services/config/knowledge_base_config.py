from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Callable

from deeptutor.knowledge.config_store import KBConfigStore
from deeptutor.services.path_service import get_path_service
from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    KNOWN_PROVIDERS,
    has_ready_provider_index,
    normalize_provider_name,
)

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
            # Per-engine default retrieval mode, set from the engine cards
            # (e.g. {"lightrag": "hybrid", "graphrag": "local"}). A KB's own
            # ``search_mode`` still wins; this is the fallback for that engine.
            "provider_modes": {},
        },
        "knowledge_bases": {},
    }


class KnowledgeBaseConfigService:
    _instances: dict[str, "KnowledgeBaseConfigService"] = {}

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        # Shares the sidecar lock + atomic-replace write path with
        # ``KnowledgeBaseManager``: both mutate the same file, so both must
        # go through the same locked read-modify-write transactions.
        self._store = KBConfigStore(self.config_path, default_factory=_default_payload)
        self._config = self._load_config()

    @classmethod
    def get_instance(cls, config_path: Path | None = None) -> "KnowledgeBaseConfigService":
        resolved = (
            config_path or get_path_service().get_knowledge_bases_root() / "kb_config.json"
        ).resolve()
        key = str(resolved)
        if key not in cls._instances:
            cls._instances[key] = cls(resolved)
        return cls._instances[key]

    def _load_config(self) -> dict[str, Any]:
        """Read the latest on-disk config, coerced and normalized.

        Raises ``KBConfigCorruptionError`` when the file exists but does not
        parse — the legacy fallback to a default payload let the next write
        overwrite the damaged file with a near-empty config.
        """
        state = self._store.read()
        self._coerce_payload(state)
        return self._normalize_payload(state)

    def _coerce_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        """Shape a raw payload in place: full defaults section + KB map.

        The file is shared with ``KnowledgeBaseManager``, which knows nothing
        about the ``defaults`` section — merge the stored values over the
        stock defaults so partially-written sections stay complete.
        """
        defaults = _default_payload()["defaults"]
        stored_defaults = state.get("defaults")
        if isinstance(stored_defaults, dict):
            defaults.update(stored_defaults)
        state["defaults"] = defaults
        state.setdefault("knowledge_bases", {})
        return state

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = payload.setdefault("defaults", _default_payload()["defaults"])
        defaults["rag_provider"] = normalize_provider_name(defaults.get("rag_provider"))

        knowledge_bases = payload.setdefault("knowledge_bases", {})
        kb_base_dir = self.config_path.parent
        for kb_name, config in knowledge_bases.items():
            if not isinstance(config, dict):
                continue

            raw_provider = config.get("rag_provider")
            config["rag_provider"] = normalize_provider_name(raw_provider)

            # A KB indexed with an engine that no longer exists collapses to the
            # default and must be rebuilt.
            if (
                isinstance(raw_provider, str)
                and raw_provider.strip()
                and raw_provider.strip().lower() not in KNOWN_PROVIDERS
            ):
                config["needs_reindex"] = True

            kb_dir = kb_base_dir / kb_name
            legacy_storage = kb_dir / "rag_storage"
            has_llamaindex_index = has_ready_provider_index(kb_dir, DEFAULT_PROVIDER)
            if (
                config["rag_provider"] == DEFAULT_PROVIDER
                and legacy_storage.exists()
                and legacy_storage.is_dir()
                and not has_llamaindex_index
            ):
                config["needs_reindex"] = True
                if config.get("status") == "ready":
                    config["status"] = "needs_reindex"

        return payload

    def _mutate(self, mutate: Callable[[dict[str, Any]], Any]) -> Any:
        """Run one locked read-modify-write transaction on kb_config.json.

        The mutator sees the latest coerced on-disk state — never the cached
        ``self._config``, which may be stale — and edits it in place; the
        committed, normalized snapshot becomes the new cache. Returns the
        mutator's result.
        """

        def wrapped(state: dict[str, Any]) -> Any:
            self._coerce_payload(state)
            result = mutate(state)
            self._normalize_payload(state)
            return result

        state, result = self._store.transaction(wrapped)
        self._config = state
        return result

    def _refresh(self) -> None:
        """Re-read kb_config.json so this singleton sees changes made by
        ``KnowledgeBaseManager`` (orphan pruning, new KB registrations).
        Read-only paths call this; mutations always start from the latest
        on-disk state inside ``_mutate`` regardless.
        """
        self._config = self._load_config()

    @staticmethod
    def _ensure_kb(state: dict[str, Any], kb_name: str) -> dict[str, Any] | None:
        knowledge_bases = state.setdefault("knowledge_bases", {})
        if kb_name not in knowledge_bases:
            deleted = state.get("_deleted_knowledge_bases")
            if isinstance(deleted, dict) and kb_name in deleted:
                return None
            knowledge_bases[kb_name] = {
                "path": kb_name,
                "description": f"Knowledge base: {kb_name}",
            }
        return knowledge_bases[kb_name]

    def get_kb_config(self, kb_name: str) -> dict[str, Any]:
        self._refresh()
        defaults = dict(self._config.get("defaults", {}))
        kb_config = dict(self._config.get("knowledge_bases", {}).get(kb_name, {}))
        merged = {
            "default_kb": defaults.get("default_kb"),
            "rag_provider": defaults.get("rag_provider", DEFAULT_PROVIDER),
            "search_mode": kb_config.get("search_mode") or defaults.get("search_mode", "hybrid"),
            "needs_reindex": bool(kb_config.get("needs_reindex", False)),
            **kb_config,
        }
        merged["rag_provider"] = normalize_provider_name(merged.get("rag_provider"))
        return merged

    def set_kb_config(self, kb_name: str, config: dict[str, Any]) -> None:
        def mutate(state: dict[str, Any]) -> None:
            kb_config = self._ensure_kb(state, kb_name)
            if kb_config is not None:
                kb_config.update(config)

        self._mutate(mutate)

    def get_rag_provider(self, kb_name: str) -> str:
        return normalize_provider_name(self.get_kb_config(kb_name).get("rag_provider"))

    def set_rag_provider(self, kb_name: str, provider: str) -> None:
        self.set_kb_config(kb_name, {"rag_provider": normalize_provider_name(provider)})

    def get_search_mode(self, kb_name: str) -> str:
        return str(self.get_kb_config(kb_name).get("search_mode", "hybrid"))

    def set_search_mode(self, kb_name: str, mode: str) -> None:
        self.set_kb_config(kb_name, {"search_mode": mode})

    def get_provider_mode(self, provider: str) -> str:
        """Global default retrieval mode for an engine ("" when unset)."""
        self._refresh()
        modes = self._config.get("defaults", {}).get("provider_modes", {})
        return str(modes.get(provider, "")) if isinstance(modes, dict) else ""

    def set_provider_mode(self, provider: str, mode: str) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["defaults"].setdefault("provider_modes", {})[provider] = mode

        self._mutate(mutate)

    def delete_kb_config(self, kb_name: str) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state.get("knowledge_bases", {}).pop(kb_name, None)
            deleted = state.setdefault("_deleted_knowledge_bases", {})
            deleted[kb_name] = datetime.now().isoformat()
            defaults = state.get("defaults")
            if isinstance(defaults, dict) and defaults.get("default_kb") == kb_name:
                remaining = sorted(state.get("knowledge_bases", {}))
                defaults["default_kb"] = remaining[0] if remaining else None

        self._mutate(mutate)

    def get_all_configs(self) -> dict[str, Any]:
        self._refresh()
        return self._config

    def set_global_defaults(self, defaults: dict[str, Any]) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["defaults"].update(defaults)

        self._mutate(mutate)

    def set_default_kb(self, kb_name: str | None) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["defaults"]["default_kb"] = kb_name

        self._mutate(mutate)

    def get_default_kb(self) -> str | None:
        self._refresh()
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
            config["rag_provider"] = normalize_provider_name(raw_provider)
            if str(raw_provider).strip().lower() not in KNOWN_PROVIDERS:
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
