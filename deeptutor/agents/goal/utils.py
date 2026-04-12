"""Utility helpers for Goal mode."""

from __future__ import annotations

from datetime import date, timedelta
import re


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "_", value.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "item"


def build_session_id(prefix: str = "goal", sequence: int = 1) -> str:
    today = date.today().strftime("%Y%m%d")
    return f"{prefix}_{today}_{sequence:03d}"


def future_dates(days: int, start: date | None = None) -> list[str]:
    origin = start or date.today()
    return [(origin + timedelta(days=index)).isoformat() for index in range(days)]
