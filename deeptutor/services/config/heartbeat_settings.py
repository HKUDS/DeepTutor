"""心跳配置持久化与加载。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import get_path_service

DEFAULT_HEARTBEAT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "interval_s": 1800,
    "llm_selection": None,
}

MIN_INTERVAL_S = 60
MAX_INTERVAL_S = 86400


def _heartbeat_settings_file() -> Path:
    return get_path_service().get_settings_file("heartbeat")


def load_heartbeat_settings() -> dict[str, Any]:
    """加载心跳配置，不存在时返回默认值。"""
    path = _heartbeat_settings_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _normalize_heartbeat_settings(data)
        except Exception:
            pass
    return dict(DEFAULT_HEARTBEAT_SETTINGS)


def save_heartbeat_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """保存心跳配置，返回规范化后的配置。"""
    normalized = _normalize_heartbeat_settings(settings)
    path = _heartbeat_settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return normalized


def _normalize_heartbeat_settings(data: dict[str, Any]) -> dict[str, Any]:
    """规范化心跳配置。"""
    result = dict(DEFAULT_HEARTBEAT_SETTINGS)
    result.update({k: v for k, v in data.items() if k in DEFAULT_HEARTBEAT_SETTINGS})

    # interval_s 范围校验
    try:
        interval = int(result["interval_s"])
        result["interval_s"] = max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, interval))
    except (TypeError, ValueError):
        result["interval_s"] = DEFAULT_HEARTBEAT_SETTINGS["interval_s"]

    # llm_selection 格式校验
    selection = result.get("llm_selection")
    if selection is not None:
        if not isinstance(selection, dict):
            result["llm_selection"] = None
        elif not selection.get("profile_id") or not selection.get("model_id"):
            result["llm_selection"] = None

    return result
