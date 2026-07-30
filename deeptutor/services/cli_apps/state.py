"""What is installed, and who may use it.

Two independent pieces of state, kept apart because they answer different
questions and are owned by different people:

**Installed** (``data/cli-apps/state.json``) — deployment-wide, written only by an
administrator's install. Installing runs somebody else's ``setup.py`` in the
application container, so it is not a self-service action and this file is not
per account.

**Enabled** (``data/system/user-cli-apps/<owner>.json``) — one account's own
preference over the apps it has been *granted*. Stored as an opt-**out** list so
a newly installed app is usable immediately rather than waiting for every user to
revisit a settings page; and stored under ``data/system``, which the sandbox never
sees, so a command running inside a CLI app cannot enable another app for the
next turn.

Neither file is an authorisation boundary on its own. The permission is
``grant.cli_apps``; this module only records installation and preference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any

from deeptutor.services.cli_apps.models import APP_ID_RE, AppRuntime, InstallKind
from deeptutor.services.cli_apps.paths import ensure_root, state_path

logger = logging.getLogger(__name__)

_PREFS_DIRNAME = "user-cli-apps"


@dataclass(frozen=True, slots=True)
class InstalledApp:
    """One app as it exists on disk right now."""

    id: str
    entry_point: str
    runtime: AppRuntime
    kind: InstallKind
    #: The requirement or package that was installed, including any pin.
    target: str
    #: Catalog commit at install time — what "reinstall to update" moves from.
    pin: str
    #: Interpreter/platform this environment is only valid under.
    abi: str
    installed_at: str
    #: Version the package reports, when it could be determined.
    version: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entry_point": self.entry_point,
            "runtime": self.runtime.value,
            "kind": self.kind.value,
            "target": self.target,
            "pin": self.pin,
            "abi": self.abi,
            "installed_at": self.installed_at,
            "version": self.version,
        }

    @classmethod
    def from_json(cls, row: Any) -> "InstalledApp | None":
        if not isinstance(row, dict):
            return None
        app_id = str(row.get("id") or "")
        if APP_ID_RE.match(app_id) is None:
            return None
        try:
            runtime = AppRuntime(str(row.get("runtime") or "python"))
            kind = InstallKind(str(row.get("kind") or "pip"))
        except ValueError:
            return None
        return cls(
            id=app_id,
            entry_point=str(row.get("entry_point") or ""),
            runtime=runtime,
            kind=kind,
            target=str(row.get("target") or ""),
            pin=str(row.get("pin") or ""),
            abi=str(row.get("abi") or ""),
            installed_at=str(row.get("installed_at") or ""),
            version=str(row.get("version") or ""),
        )


# ── deployment: what is installed ────────────────────────────────────────


def load_installed() -> dict[str, InstalledApp]:
    """Every installed app, by id. Unreadable state reads as "nothing installed"."""
    path = state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("CLI app state at %s is unreadable; treating as empty", path)
        return {}
    rows = payload.get("apps") if isinstance(payload, dict) else None
    out: dict[str, InstalledApp] = {}
    for row in rows if isinstance(rows, list) else []:
        app = InstalledApp.from_json(row)
        if app is not None:
            out[app.id] = app
    return out


def record_install(app: InstalledApp) -> None:
    """Add or replace *app* in the deployment state."""
    installed = load_installed()
    installed[app.id] = app
    _write_installed(installed)


def forget_install(app_id: str) -> None:
    installed = load_installed()
    if installed.pop(app_id, None) is None:
        return
    _write_installed(installed)


def now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_installed(apps: dict[str, InstalledApp]) -> None:
    ensure_root()
    path = state_path()
    payload = {
        "version": 1,
        "apps": [apps[app_id].to_json() for app_id in sorted(apps)],
    }
    _write_json(path, payload)


# ── per account: what is enabled ─────────────────────────────────────────


def prefs_path(owner_id: str) -> Path:
    """Where *owner_id*'s app preferences live.

    Under ``data/system`` on purpose — see the module docstring. The owner id is
    validated because it becomes a filename.
    """
    from deeptutor.multi_user.paths import SYSTEM_ROOT

    if not owner_id or "/" in owner_id or "\\" in owner_id or owner_id.startswith("."):
        raise ValueError(f"Unsafe owner id for a CLI app preferences file: {owner_id!r}")
    return SYSTEM_ROOT / _PREFS_DIRNAME / f"{owner_id}.json"


def disabled_apps(owner_id: str) -> set[str]:
    """App ids this account has switched off for itself."""
    try:
        path = prefs_path(owner_id)
    except ValueError:
        return set()
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = payload.get("disabled") if isinstance(payload, dict) else None
    return {str(item) for item in values} if isinstance(values, list) else set()


def set_app_enabled(owner_id: str, app_id: str, enabled: bool) -> set[str]:
    """Record one preference; returns the resulting disabled set."""
    disabled = disabled_apps(owner_id)
    if enabled:
        disabled.discard(app_id)
    else:
        disabled.add(app_id)
    path = prefs_path(owner_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, {"version": 1, "disabled": sorted(disabled)})
    return disabled


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* atomically, so a crash cannot leave a torn file.

    The reader treats unparseable state as empty, which for the deployment file
    means "nothing installed" — every app would silently vanish from every turn.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


__all__ = [
    "InstalledApp",
    "disabled_apps",
    "forget_install",
    "load_installed",
    "now_stamp",
    "prefs_path",
    "record_install",
    "set_app_enabled",
]
