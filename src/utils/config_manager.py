import logging
import os
from pathlib import Path
import tempfile
from threading import Lock
from typing import Any, Dict, List, Optional

from dotenv import dotenv_values, load_dotenv
from pydantic import ValidationError
import yaml

from ..config.defaults import DEFAULTS

# Use package-relative imports to avoid PYTHONPATH issues
from ..config.schema import AppConfig, migrate_config
from ..core.errors import ConfigError

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Thread-safe manager for reading and writing configuration files.
    Primarily manages config/main.yaml and reads .env.

    Governance additions:
    - Schema validation via pydantic (AppConfig); invalid configs are rejected.
    - Versioned migrations via migrate_config.
    - Atomic writes with temp file and os.replace; creates main.yaml.bak.
    - Single lock guards mtime read, load, and save.
    - Deterministic YAML dumps; returns deep copies.
    - Layered env: .env, then .env.local (override), then process env.
    """

    _instance: Optional["ConfigManager"] = None
    _lock = Lock()

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
        self.config_path = self.project_root / "config" / "main.yaml"
        self._config_cache: Dict[str, Any] = {}
        self._last_mtime: float = 0.0
        self._initialized = True

        # Layered env loading
        load_dotenv(dotenv_path=self.project_root / ".env", override=False)
        load_dotenv(dotenv_path=self.project_root / ".env.local", override=True)

    def _load_env_file(self, path: Path) -> Dict[str, str]:
        """Load a .env file and return non-None values as strings."""
        if not path.exists():
            return {}
        return {k: str(v) for k, v in dotenv_values(path).items() if v is not None}

    def _read_yaml(self) -> Dict[str, Any]:
        """Read the main YAML configuration file safely."""
        if not self.config_path.exists():
            return {}
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _deep_update(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def _validate_and_migrate(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        self._deep_update(merged, DEFAULTS)
        self._deep_update(merged, raw)
        migrated = migrate_config(merged)
        try:
            return AppConfig(**migrated).dict()
        except ValidationError as e:
            raise ConfigError("Config validation failed", details={"errors": e.errors()})

    def load_config(self, force_reload: bool = False) -> Dict[str, Any]:
        """
        Load configuration from main.yaml.
        Uses caching based on file modification time and validates against schema.
        """
        with self._lock:
            if not self.config_path.exists():
                logger.info("Config not found at %s", self.config_path)
                self._config_cache = {}
                self._last_mtime = 0
                return {}

            current_mtime = self.config_path.stat().st_mtime
            if not self._config_cache or force_reload or current_mtime > self._last_mtime:
                try:
                    raw = self._read_yaml()
                    validated = self._validate_and_migrate(raw)
                    self._config_cache = validated
                    self._last_mtime = current_mtime
                except ConfigError as ce:
                    logger.error("%s", ce, extra={"context": getattr(ce, "context", {})})
                    return {}
                except Exception as e:
                    logger.exception("Error loading config: %s", e)
                    return {}

            # deep copy via dump/load for immutability
            return yaml.safe_load(yaml.safe_dump(self._config_cache, sort_keys=False)) or {}

    def save_config(self, config: Dict[str, Any]) -> bool:
        """
        Save configuration to main.yaml.
        Deep-merges provided config with existing one; writes atomically.
        Rejects invalid configs per schema.
        """
        try:
            with self._lock:
                current = self.load_config(force_reload=True)
                self._deep_update(current, config)
                validated = self._validate_and_migrate(current)

                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                yaml_str = yaml.safe_dump(
                    validated,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

                # Atomic write with backup
                fd, tmp_path = tempfile.mkstemp(
                    prefix="main.yaml.", dir=str(self.config_path.parent)
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                        tmp.write(yaml_str)
                        tmp.flush()
                        os.fsync(tmp.fileno())
                    backup_path = self.config_path.with_suffix(".yaml.bak")
                    if self.config_path.exists():
                        try:
                            os.replace(self.config_path, backup_path)
                        except Exception:
                            logger.debug("Backup replace failed; continuing.")
                    os.replace(tmp_path, self.config_path)
                    self._config_cache = validated
                    self._last_mtime = self.config_path.stat().st_mtime
                    return True
                finally:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
        except ConfigError as ce:
            logger.error(
                "Refusing to save invalid config: %s",
                ce,
                extra={"context": getattr(ce, "context", {})},
            )
            return False
        except Exception as e:
            logger.exception("Error saving config: %s", e)
            return False

    def get_env_info(self) -> Dict[str, str]:
        """
        Read relevant environment variables using layered .env files and process env.
        Returns only non-sensitive metadata.
        """
        env_path = self.project_root / ".env"
        local_path = self.project_root / ".env.local"
        parsed_env = self._load_env_file(env_path)
        parsed_env.update(self._load_env_file(local_path))

        def _get(key: str, default: str = "") -> str:
            return str(parsed_env.get(key) or os.environ.get(key, default))

        return {
            "model": _get("LLM_MODEL", DEFAULTS.get("llm", {}).get("model", "Pro/Flash")),
        }

    def validate_required_env(self, keys: List[str]) -> Dict[str, List[str]]:
        env_path = self.project_root / ".env"
        local_path = self.project_root / ".env.local"
        parsed_env = self._load_env_file(env_path)
        parsed_env.update(self._load_env_file(local_path))
        missing = [k for k in keys if not (parsed_env.get(k) or os.environ.get(k))]
        if missing:
            logger.warning("Missing required env keys", extra={"missing": missing})
        return {"missing": missing}

    @classmethod
    def reset_for_tests(cls) -> None:
        """Reset singleton to allow re-initialization in tests with a different project_root."""
        with cls._lock:
            cls._instance = None
