"""JSON storage helpers for immersive reading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeptutor.services.file_io import atomic_write_text


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
