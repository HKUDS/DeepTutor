import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Dict, List, Optional

import yaml

from ..services.config.loader import get_runtime_settings_dir


class ConfigManager:
    """
    Minimal runtime YAML manager for `data/user/settings/main.yaml`.

    The long-lived configuration model is now:
    - `data/user/settings/model_catalog.json` for providers and credentials
    - `data/user/settings/*.json` / `*.yaml` for runtime behavior
    """

    _instance: Optional["ConfigManager"] = None
    _lock = RLock()

    def __new__(cls, project_root: Optional[Path] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ConfigManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, project_root: Optional[Path] = None):
        if getattr(self, "_initialized", False):
            return

        self.project_root = project_root or Path(__file__).parent.parent.parent
        self.config_path = get_runtime_settings_dir(self.project_root) / "main.yaml"
        self._config_cache: Dict[str, Any] = {}
        self._last_mtime: float = 0.0
        self._initialized = True

    def _read_yaml(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}
        with open(self.config_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _deep_update(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def load_config(self, force_reload: bool = False) -> Dict[str, Any]:
        with self._lock:
            if not self.config_path.exists():
                self._config_cache = {}
                self._last_mtime = 0
                return {}

            current_mtime = self.config_path.stat().st_mtime
            if not self._config_cache or force_reload or current_mtime > self._last_mtime:
                self._config_cache = self._read_yaml()
                self._last_mtime = current_mtime

            return yaml.safe_load(yaml.safe_dump(self._config_cache, sort_keys=False)) or {}

    def save_config(self, config: Dict[str, Any]) -> bool:
        with self._lock:
            current = self.load_config(force_reload=True)
            self._deep_update(current, config)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            yaml_str = yaml.safe_dump(
                current,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

            fd, tmp_path = tempfile.mkstemp(prefix="main.yaml.", dir=str(self.config_path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                    tmp.write(yaml_str)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_path, self.config_path)
                self._config_cache = current
                self._last_mtime = self.config_path.stat().st_mtime
                return True
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    def get_env_info(self) -> Dict[str, str]:
        return {"model": self._runtime_key_values().get("LLM_MODEL", "")}

    def validate_required_env(self, keys: List[str]) -> Dict[str, List[str]]:
        values = self._runtime_key_values()
        missing = [key for key in keys if not values.get(key)]
        return {"missing": missing}

    def _runtime_key_values(self) -> Dict[str, str]:
        from deeptutor.services.config.model_catalog import ModelCatalogService
        from deeptutor.services.config.runtime_settings import RuntimeSettingsService

        settings_dir = get_runtime_settings_dir(self.project_root)
        catalog_service = ModelCatalogService(settings_dir / "model_catalog.json")
        catalog = catalog_service.load()
        llm_profile = catalog_service.get_active_profile(catalog, "llm") or {}
        llm_model = catalog_service.get_active_model(catalog, "llm") or {}
        system = RuntimeSettingsService.get_instance(settings_dir).load_system()
        return {
            "BACKEND_PORT": str(system["backend_port"]),
            "FRONTEND_PORT": str(system["frontend_port"]),
            "LLM_BINDING": str(llm_profile.get("binding") or ""),
            "LLM_MODEL": str(llm_model.get("model") or ""),
            "LLM_API_KEY": str(llm_profile.get("api_key") or ""),
            "LLM_HOST": str(llm_profile.get("base_url") or ""),
        }

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._instance = None
