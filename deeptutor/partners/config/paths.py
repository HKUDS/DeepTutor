"""Path helpers for the Partners data tree (``data/partners/``)."""

from __future__ import annotations

from pathlib import Path

from deeptutor.partners.helpers import ensure_dir


def _base_dir() -> Path:
    # Anchored to the admin workspace root (data/partners), NOT the
    # current-user path service: partner runtimes execute inside a synthetic
    # partner scope whose workspace_root lives below this very tree, so
    # resolving through the contextvar here would recurse the layout.
    from deeptutor.multi_user.paths import get_admin_path_service

    return ensure_dir(get_admin_path_service().workspace_root / "partners")


def get_data_dir() -> Path:
    return _base_dir()


def get_runtime_subdir(name: str) -> Path:
    return ensure_dir(_base_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Shared media download dir used by channel implementations."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


# ── Per-partner path helpers ──────────────────────────────────────


def get_partner_dir(partner_id: str) -> Path:
    """data/partners/{partner_id}/ — config, sessions, and workspace."""
    return ensure_dir(_base_dir() / partner_id)


def get_partner_workspace(partner_id: str) -> Path:
    """The partner's scope root (chat user-workspace layout lives below it)."""
    return ensure_dir(get_partner_dir(partner_id) / "workspace")


def get_partner_sessions_dir(partner_id: str) -> Path:
    return ensure_dir(get_partner_dir(partner_id) / "sessions")


def get_partner_media_dir(partner_id: str, channel: str | None = None) -> Path:
    base = ensure_dir(get_partner_dir(partner_id) / "media")
    return ensure_dir(base / channel) if channel else base
