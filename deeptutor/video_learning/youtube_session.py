"""Consent marker for using the host Mac's existing Chrome session.

No browser profile, Cookie database, or Cookie value is copied by this module.
The marker merely lets the subtitle worker ask yt-dlp to use Chrome at the
moment a subtitle request is made.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import stat

from deeptutor.multi_user.paths import owner_secrets_dir


def chrome_available() -> bool:
    return bool(
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").is_file()
        or Path("/Applications/Chromium.app/Contents/MacOS/Chromium").is_file()
    )


class HostChromeSessionStore:
    """Owner consent, stored privately without any browser credential data."""

    @classmethod
    def _path(cls, owner_id: str) -> Path:
        directory = owner_secrets_dir(owner_id) / "private" / "youtube"
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, stat.S_IRWXU)
        return directory / "host-chrome.json"

    @classmethod
    def metadata(cls, owner_id: str) -> dict[str, object] | None:
        try:
            payload = json.loads(cls._path(owner_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) and payload.get("enabled") is True else None

    @classmethod
    def enabled(cls, owner_id: str) -> bool:
        return cls.metadata(owner_id) is not None

    @classmethod
    def enable(cls, owner_id: str) -> None:
        path = cls._path(owner_id)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump({"enabled": True, "enabled_at": datetime.now(timezone.utc).isoformat()}, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temporary, path)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def delete(cls, owner_id: str) -> None:
        cls._path(owner_id).unlink(missing_ok=True)
