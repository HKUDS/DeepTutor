"""Unapplied settings, held off the runtime path.

Settings offers two promises — "Save Draft" and "Apply" — and until now they
were the same write: both persisted to the live files and both invalidated the
runtime caches, so the only thing distinguishing them was their labels. Worse,
"Save Draft" only ever wrote the model catalog, while half the settings pages
(memory, starting points, network, attachments, document parsing) keep their
state outside it. Editing one of those, pressing Save Draft and reading
"Draft saved" persisted nothing at all, and navigating away lost the edit.

So a draft is now a real place: one envelope, stored beside the live settings
but read by nothing except this module. Apply is what moves it into the files
the runtime resolves against, and clears it.

    Save Draft  → envelope written, runtime untouched
    Apply       → live files written, envelope cleared

The envelope holds the whole catalog and an opaque payload per settings page
that owns state outside it, keyed by the same string the page registers with.
Payloads are opaque on purpose: the pages that produce them are the only code
that understands them, and inventing a server-side schema for each one would
buy validation at the cost of a second definition to keep in sync.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from deeptutor.services.path_service import get_path_service

from .model_catalog import redact_catalog_secrets, restore_catalog_secrets

DRAFT_VERSION = 1


def _empty_draft() -> dict[str, Any]:
    return {"version": DRAFT_VERSION, "updated_at": "", "catalog": None, "extensions": {}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SettingsDraftService:
    """Read/write the unapplied settings envelope."""

    _instances: dict[str, "SettingsDraftService"] = {}

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls, path: Path | None = None) -> "SettingsDraftService":
        resolved = (path or get_path_service().get_settings_file("settings_draft")).resolve()
        key = str(resolved)
        if key not in cls._instances:
            cls._instances[key] = cls(resolved)
        return cls._instances[key]

    def load(self) -> dict[str, Any]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return _empty_draft()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            # A corrupt draft is not worth failing a settings page over; the
            # live configuration is unaffected either way.
            return _empty_draft()
        if not isinstance(loaded, dict):
            return _empty_draft()
        draft = _empty_draft()
        draft.update({key: loaded.get(key, draft[key]) for key in draft})
        if not isinstance(draft.get("extensions"), dict):
            draft["extensions"] = {}
        return draft

    def save(self, draft: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            normalized = _empty_draft()
            normalized.update({key: draft.get(key, normalized[key]) for key in normalized})
            if not isinstance(normalized.get("extensions"), dict):
                normalized["extensions"] = {}
            normalized["version"] = DRAFT_VERSION
            normalized["updated_at"] = _now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(normalized, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.path)
            finally:
                temp_path.unlink(missing_ok=True)
            return normalized

    def clear(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)

    def has_content(self, draft: dict[str, Any] | None = None) -> bool:
        loaded = draft if draft is not None else self.load()
        return bool(loaded.get("catalog")) or bool(loaded.get("extensions"))


def is_empty_draft(draft: dict[str, Any] | None) -> bool:
    if not draft:
        return True
    return not draft.get("catalog") and not draft.get("extensions")


def redact_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Return an API-safe envelope.

    Only the catalog half can be redacted meaningfully — extension payloads are
    opaque here. None of the settings pages backed by them hold credentials
    (they carry counts, budgets, ports and toggles), so there is nothing to
    mask; a page that ever does needs its own handling rather than a guess at
    this layer.
    """
    safe = deepcopy(draft)
    catalog = safe.get("catalog")
    if isinstance(catalog, dict):
        safe["catalog"] = redact_catalog_secrets(catalog)
    return safe


def merge_draft_secrets(
    proposed: dict[str, Any],
    stored: dict[str, Any],
    live_catalog: dict[str, Any],
) -> dict[str, Any]:
    """Resolve masked credentials in an incoming draft.

    A key typed into a draft and never applied lives only in the draft file, so
    the placeholder that comes back has to resolve against the draft first and
    the live catalog second. Getting that order wrong would quietly replace a
    newly typed key with the old one every time the draft was re-saved.
    """
    merged = deepcopy(proposed)
    catalog = merged.get("catalog")
    if not isinstance(catalog, dict):
        return merged
    stored_catalog = stored.get("catalog")
    if isinstance(stored_catalog, dict):
        catalog = restore_catalog_secrets(catalog, stored_catalog)
    merged["catalog"] = restore_catalog_secrets(catalog, live_catalog)
    return merged


def get_settings_draft_service() -> SettingsDraftService:
    """Resolve the draft for the acting scope, mirroring the model catalog.

    A non-admin never edits these settings, so their draft — if the UI somehow
    offered one — belongs to the admin scope they are reading, not to a private
    file that nothing would ever apply.
    """
    try:
        from deeptutor.multi_user.context import get_current_user
        from deeptutor.multi_user.paths import get_admin_path_service

        if not get_current_user().is_admin:
            return SettingsDraftService.get_instance(
                get_admin_path_service().get_settings_file("settings_draft")
            )
    except Exception:
        pass
    return SettingsDraftService.get_instance(get_path_service().get_settings_file("settings_draft"))


__all__ = [
    "SettingsDraftService",
    "get_settings_draft_service",
    "is_empty_draft",
    "merge_draft_secrets",
    "redact_draft",
]
