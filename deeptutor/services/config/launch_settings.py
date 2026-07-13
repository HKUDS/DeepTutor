from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from deeptutor.runtime.home import get_runtime_home

from .runtime_settings import RuntimeSettingsService

PROJECT_ROOT = get_runtime_home()
DEFAULT_BACKEND_PORT = 8001
DEFAULT_FRONTEND_PORT = 3782
DEFAULT_LANGUAGE = "en"


@dataclass(frozen=True, slots=True)
class LaunchSettings:
    backend_port: int
    frontend_port: int
    language: str
    source: str
    settings_dir: Path
    interface_json_path: Path
    system_json_path: Path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _coerce_port(value: Any) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _normalize_language(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    language = value.strip().lower()
    if language in {"en", "english"} or language.startswith("en_"):
        return "en"
    if language in {"zh", "cn", "chinese"} or language.startswith("zh_"):
        return "zh"
    return None


def load_launch_settings(project_root: Path | None = None) -> LaunchSettings:
    """Load ports and UI language for launcher-style entry points.

    Launch ports come from ``data/user/settings/system.json``. Environment
    variables are treated as explicit deployment overrides (for example Docker
    port mapping), not as a second application configuration file. UI language
    remains in ``data/user/settings/interface.json``.
    """

    root = project_root or PROJECT_ROOT
    settings_dir = root / "data" / "user" / "settings"
    interface_json_path = settings_dir / "interface.json"
    system_json_path = settings_dir / "system.json"

    interface_settings = _load_json_object(interface_json_path)
    service = RuntimeSettingsService.get_instance(settings_dir)
    system_from_file = service.load_system(include_process_overrides=False)
    system_settings = service.load_system(include_process_overrides=True)

    settings_backend_port = _coerce_port(system_from_file.get("backend_port"))
    settings_frontend_port = _coerce_port(system_from_file.get("frontend_port"))
    process_backend_port = _coerce_port(os.getenv("BACKEND_PORT"))
    process_frontend_port = _coerce_port(os.getenv("FRONTEND_PORT"))
    interface_language = _normalize_language(interface_settings.get("language"))
    process_language = _normalize_language(os.getenv("UI_LANGUAGE")) or _normalize_language(
        os.getenv("LANGUAGE")
    )
    backend_port = _coerce_port(system_settings.get("backend_port")) or DEFAULT_BACKEND_PORT
    frontend_port = _coerce_port(system_settings.get("frontend_port")) or DEFAULT_FRONTEND_PORT
    language = interface_language or process_language or DEFAULT_LANGUAGE

    sources: list[str] = []
    if settings_backend_port is not None or settings_frontend_port is not None:
        sources.append("data/user/settings/system.json")
    if process_backend_port is not None or process_frontend_port is not None:
        sources.append("environment")
    if not sources:
        sources.append("defaults")
    if process_language is not None:
        sources.append("environment")
    if interface_language is not None:
        sources.append("data/user/settings/interface.json")
    else:
        sources.append("default language")

    return LaunchSettings(
        backend_port=backend_port,
        frontend_port=frontend_port,
        language=language,
        source=" + ".join(sources),
        settings_dir=settings_dir,
        interface_json_path=interface_json_path,
        system_json_path=system_json_path,
    )


__all__ = [
    "DEFAULT_BACKEND_PORT",
    "DEFAULT_FRONTEND_PORT",
    "DEFAULT_LANGUAGE",
    "LaunchSettings",
    "load_launch_settings",
]
