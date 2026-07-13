from __future__ import annotations

import sys


def _ensure_replace_errors() -> None:
    try:
        if getattr(sys.stdout, "errors", None) != "replace":
            sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


_ensure_replace_errors()


def banner(title: str, lines: list[str] | tuple[str, ...] = ()) -> None:
    print(f"== {title} ==")
    for line in lines:
        print(str(line))


def log_success(message: str) -> None:
    print(f"[ok] {message}")


def log_error(message: str) -> None:
    print(f"[error] {message}")


__all__ = ["banner", "log_error", "log_success"]
