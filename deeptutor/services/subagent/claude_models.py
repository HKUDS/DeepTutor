"""Sync Claude Code's model catalog by scraping its ``/model`` TUI.

Unlike Codex (which keeps a clean ``models_cache.json``), Claude Code exposes no
machine-readable model list — ``/model`` lives only inside its interactive
terminal UI. So on an explicit sync we drive ``claude`` in a pseudo-terminal,
open ``/model``, render the screen with an in-memory terminal emulator (``pyte``)
so the columns come out intact, parse the picker rows, and cache the result to
``data/user/settings/claude_models_cache.json`` (mirroring Codex's cache). The
options endpoint then reads that cache; if it's absent (never synced, or capture
failed) the curated fallback in :mod:`models` is used.

The capture is best-effort and POSIX-only (needs a pty); any failure returns an
empty list so the caller falls back to the curated catalog.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import re
import select
import signal
import tempfile
import time

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_CACHE_FILE = "claude_models_cache.json"

# Bounds for the capture: total wall-clock, and the terminal geometry (wide
# enough that description columns don't wrap into the model name).
_CAPTURE_TIMEOUT = 35.0
_COLS, _ROWS = 200, 60

# A picker row: optional cursor marker, an index, then "Name<2+ spaces>desc".
_ROW_RE = re.compile(r"^\s*(?:[❯>›*]\s*)?(\d+)\.\s+(.+?)\s*$")
_SELECT_MARKERS = "✔✓●◉※"


def _cache_path():
    return get_path_service().get_settings_file(_CACHE_FILE)


def load_cached_claude_models() -> tuple[list[dict[str, str]], str]:
    """Return ``(models, fetched_at)`` from the cache, or ``([], "")`` if none.

    Each model is ``{"slug", "display_name"}``. Pure read — no capture.
    """
    path = _cache_path()
    if not path.exists():
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("failed to read %s; ignoring", path, exc_info=True)
        return [], ""
    models = [
        {"slug": str(m["slug"]), "display_name": str(m.get("display_name") or m["slug"])}
        for m in data.get("models", [])
        if isinstance(m, dict) and m.get("slug")
    ]
    return models, str(data.get("fetched_at") or "")


async def sync_claude_models() -> tuple[list[dict[str, str]], str]:
    """Scrape ``/model`` live, cache the result, and return ``(models, fetched_at)``.

    Runs the blocking pty capture off the event loop. On any failure returns
    ``([], "")`` and leaves the existing cache untouched.
    """
    import asyncio

    try:
        screen = await asyncio.to_thread(_capture_model_screen)
    except Exception:
        logger.warning("claude /model capture failed", exc_info=True)
        return [], ""
    if not screen:
        return [], ""
    models = _parse_model_screen(screen)
    if not models:
        logger.warning("claude /model capture parsed no models")
        return [], ""
    fetched_at = datetime.now(timezone.utc).isoformat()
    _write_cache(models, fetched_at)
    return models, fetched_at


def _write_cache(models: list[dict[str, str]], fetched_at: str) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": fetched_at, "models": models}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_model_screen(text: str) -> list[dict[str, str]]:
    """Parse the rendered ``/model`` picker into ``{slug, display_name}`` entries.

    Maps each selectable row to the value ``--model`` accepts: the tier alias
    (``opus``/``sonnet``/``haiku``), with a ``[1m]`` suffix for the 1M-context
    variant. The recommended *default* row maps to the CLI default (the empty
    option the UI already offers) and disabled rows (e.g. an unavailable Fable)
    are dropped, so the list is exactly what the user can actually pick.
    """
    started = False
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if not started:
            if "select model" in line.lower():
                started = True
            continue
        match = _ROW_RE.match(line)
        if not match:
            continue  # continuation / blank / footer line
        rest = match.group(2)
        parts = re.split(r"\s{2,}", rest.strip(), maxsplit=1)
        name = parts[0].translate({ord(c): None for c in _SELECT_MARKERS}).strip()
        desc = parts[1].strip() if len(parts) > 1 else ""
        low = name.lower()
        if "(disabled)" in low or "unavailable" in desc.lower():
            continue
        if "recommended" in low or low.startswith("default"):
            continue  # the CLI default — already the UI's empty option
        base = re.sub(r"\(.*?\)", "", name).strip().split(" ")[0].lower()
        if base not in {"opus", "sonnet", "haiku"}:
            continue
        slug = f"{base}[1m]" if "1m context" in low else base
        if slug in seen:
            continue
        seen.add(slug)
        display = desc.split("·")[0].strip() or name
        out.append({"slug": slug, "display_name": display})
    return out


def _capture_model_screen() -> str | None:
    """Drive ``claude``'s ``/model`` TUI in a pty and return the rendered screen.

    Returns the full screen text (one line per terminal row) once the picker is
    on screen, or ``None`` if we couldn't get there. POSIX-only; gracefully
    returns ``None`` when ``pyte`` is unavailable or the platform has no pty.
    """
    if os.name != "posix":
        return None
    try:
        import pty

        import pyte
    except Exception:
        return None

    screen = pyte.Screen(_COLS, _ROWS)
    stream = pyte.ByteStream(screen)
    workdir = tempfile.mkdtemp(prefix="dt-claude-model-")
    pid, fd = pty.fork()
    if pid == 0:  # child: become the claude TUI
        os.environ["TERM"] = "xterm-256color"
        os.environ["COLUMNS"] = str(_COLS)
        os.environ["LINES"] = str(_ROWS)
        try:
            os.chdir(workdir)
            os.execvp("claude", ["claude"])  # nosec B606 B607 — PATH-resolved CLI in a forked PTY child, no shell
        except Exception:
            os._exit(127)

    trusted = opened = False
    settled_at: float | None = None
    start = time.time()
    try:
        while time.time() - start < _CAPTURE_TIMEOUT:
            ready, _, _ = select.select([fd], [], [], 0.3)
            if ready:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                stream.feed(data)
            packed = "".join(screen.display).replace(" ", "").lower()
            # 1) Accept the workspace-trust prompt for our temp dir.
            if not trusted and "trustthisfolder" in packed:
                time.sleep(0.3)
                os.write(fd, b"\r")
                trusted = True
                time.sleep(1.3)
                continue
            # 2) Once the composer is ready, open the model picker.
            if (
                trusted
                and not opened
                and ("forshortcuts" in packed or "tryedit" in packed or 'try"' in packed)
            ):
                os.write(fd, b"/model")
                time.sleep(0.5)
                os.write(fd, b"\r")
                opened = True
                time.sleep(1.5)
                continue
            # 3) Let the picker settle, then snapshot.
            if opened and "selectmodel" in packed and settled_at is None:
                settled_at = time.time()
            if settled_at is not None and time.time() - settled_at > 1.2:
                break
        return "\n".join(screen.display) if opened else None
    finally:
        for keys in (b"\x1b", b"\x03\x03"):  # Esc, then Ctrl-C twice
            try:
                os.write(fd, keys)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        _cleanup_dir(workdir)


def _cleanup_dir(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


__all__ = ["load_cached_claude_models", "sync_claude_models"]
