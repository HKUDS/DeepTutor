"""Path helpers for the Partners data tree — per-owner isolation.

Partner 数据按 owner 隔离存储：

- Admin 的 partners: ``data/user/partners/``（单机模式为 ``data/partners/``）
- 普通用户的 partners: ``data/users/<uid>/partners/``

核心约束：``_base_dir_for_owner()`` 接受显式的 ``owner_id`` 参数，
**不能**使用 ``get_current_user()`` 解析路径，因为 partner 运行时
通过 ``user_context(partner_user(partner_id))`` 设置了 synthetic
partner scope，会导致递归。
"""

from __future__ import annotations

import warnings
from pathlib import Path

from deeptutor.partners.helpers import ensure_dir


# ── Owner-resolved base dirs ─────────────────────────────────────


def _admin_base_dir() -> Path:
    """Admin workspace partners dir — used by process-level operations."""
    from deeptutor.multi_user.paths import get_admin_path_service

    return ensure_dir(get_admin_path_service().workspace_root / "partners")


def _base_dir_for_owner(owner_id: str) -> Path:
    """按 owner_id 解析 partners 目录。

    - 空 owner_id → admin workspace（data/user/partners/ 或 data/partners/）
    - 非空 owner_id → user workspace（data/users/<uid>/partners/）
    """
    from deeptutor.multi_user.paths import ADMIN_WORKSPACE_ROOT, USERS_ROOT

    if owner_id:
        return ensure_dir(USERS_ROOT / owner_id / "partners")
    return _admin_base_dir()


# ── Owner resolution ─────────────────────────────────────────────

# 缓存 partner_id → owner_id 映射，避免反复扫描磁盘
_owner_cache: dict[str, str] = {}


def _resolve_owner_id(partner_id: str) -> str:
    """通过扫描已知位置查找 partner 的 owner_id。

    先检查 admin 目录，再检查各用户目录。未找到时默认返回空串（admin）。
    """
    if partner_id in _owner_cache:
        return _owner_cache[partner_id]

    # 先检查 admin 目录
    admin_cfg = _admin_base_dir() / partner_id / "config.yaml"
    if admin_cfg.exists():
        _owner_cache[partner_id] = ""
        return ""

    # 再检查各用户目录
    from deeptutor.multi_user.paths import USERS_ROOT

    if USERS_ROOT.exists():
        for user_dir in USERS_ROOT.iterdir():
            if user_dir.is_dir():
                cfg = user_dir / "partners" / partner_id / "config.yaml"
                if cfg.exists():
                    _owner_cache[partner_id] = user_dir.name
                    return user_dir.name

    # fallback: 默认 admin
    _owner_cache[partner_id] = ""
    return ""


def resolve_owner_for_partner(partner_id: str) -> str:
    """公开接口：反查 partner 的 owner_id。空串表示 admin。"""
    return _resolve_owner_id(partner_id)


def invalidate_owner_cache(partner_id: str | None = None) -> None:
    """清除 owner 缓存。partner_id 为 None 时清除全部。"""
    if partner_id is None:
        _owner_cache.clear()
    else:
        _owner_cache.pop(partner_id, None)


# ── Deprecated global helpers ────────────────────────────────────


def get_data_dir() -> Path:
    """Admin partners 数据目录（仅用于兼容旧调用）。"""
    return _admin_base_dir()


def get_runtime_subdir(name: str) -> Path:
    """已废弃：请使用 ``get_partner_runtime_subdir``。"""
    warnings.warn(
        "get_runtime_subdir() 已废弃，请使用 get_partner_runtime_subdir()",
        DeprecationWarning,
        stacklevel=2,
    )
    return ensure_dir(_admin_base_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """已废弃：请使用 ``get_partner_media_dir``。"""
    warnings.warn(
        "get_media_dir() 已废弃，请使用 get_partner_media_dir()",
        DeprecationWarning,
        stacklevel=2,
    )
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


# ── Per-partner path helpers ─────────────────────────────────────


def get_partner_dir(partner_id: str, *, owner_id: str | None = None) -> Path:
    """data/[user|users/<uid>]/partners/{partner_id}/ — config, sessions, and workspace."""
    if owner_id is None:
        owner_id = _resolve_owner_id(partner_id)
    return ensure_dir(_base_dir_for_owner(owner_id) / partner_id)


def get_partner_workspace(partner_id: str, *, owner_id: str | None = None) -> Path:
    """The partner's scope root (chat user-workspace layout lives below it)."""
    return ensure_dir(get_partner_dir(partner_id, owner_id=owner_id) / "workspace")


def get_partner_sessions_dir(partner_id: str, *, owner_id: str | None = None) -> Path:
    return ensure_dir(get_partner_dir(partner_id, owner_id=owner_id) / "sessions")


def get_partner_runtime_subdir(
    partner_id: str, name: str, *, owner_id: str | None = None
) -> Path:
    """Partner 级别的运行时子目录（如 media）。"""
    return ensure_dir(get_partner_dir(partner_id, owner_id=owner_id) / name)


def get_partner_media_dir(
    partner_id: str, channel: str | None = None, *, owner_id: str | None = None
) -> Path:
    base = get_partner_runtime_subdir(partner_id, "media", owner_id=owner_id)
    return ensure_dir(base / channel) if channel else base
