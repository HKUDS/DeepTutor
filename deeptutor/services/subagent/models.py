"""Backend option discovery — the synced model + reasoning-effort lists.

The /settings "Partners & Agents" page lets the user pick the model and
reasoning effort DeepTutor drives each backend with. Those lists change over
time (vendors add/retire models), so this is read live, not hard-coded, and the
page's "sync" button just re-reads it:

* **Codex** publishes an authoritative, server-synced cache at
  ``$CODEX_HOME/models_cache.json`` (slugs + per-model reasoning levels) and the
  user's current default in ``config.toml`` — we read both.
* **Claude Code** has no model-list CLI; its ``--model`` takes stable aliases
  (opus / sonnet / haiku) plus any full name, and ``--effort`` a fixed set — so
  we offer those as suggestions and the UI also allows a free-text model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from deeptutor.services.subagent.process import probe_version
from deeptutor.services.subagent.registry import get_backend

logger = logging.getLogger(__name__)

# Claude Code: curated fallback used until a live ``/model`` sync populates the
# cache (see ``claude_models``). The aliases + ``[1m]`` variants mirror the
# ``/model`` picker; the UI also accepts a free-text model name.
_CLAUDE_MODELS = (
    ("opus", "Opus 4.8 · 1M context"),
    ("sonnet", "Sonnet 4.6"),
    ("sonnet[1m]", "Sonnet 4.6 · 1M context"),
    ("haiku", "Haiku 4.5"),
)
_CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(slots=True)
class ModelOption:
    slug: str
    display_name: str
    default_effort: str = ""
    efforts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "display_name": self.display_name,
            "default_effort": self.default_effort,
            "efforts": list(self.efforts),
        }


@dataclass(slots=True)
class BackendOptions:
    kind: str
    display_name: str
    available: bool
    version: str = ""
    default_model: str = ""
    models: list[ModelOption] = field(default_factory=list)
    # Effort scale when it isn't model-specific (Claude Code). For Codex the
    # per-model ``efforts`` are authoritative; this is a fallback/union.
    efforts: list[str] = field(default_factory=list)
    # Whether the UI should allow a free-text model (true when we can't fully
    # enumerate, e.g. Claude Code aliases + full names).
    allow_custom_model: bool = False
    # Freshness of a synced source, if any (Codex cache fetch time).
    synced_at: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "display_name": self.display_name,
            "available": self.available,
            "version": self.version,
            "default_model": self.default_model,
            "models": [m.to_dict() for m in self.models],
            "efforts": list(self.efforts),
            "allow_custom_model": self.allow_custom_model,
            "synced_at": self.synced_at,
            "detail": self.detail,
        }


def _codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".codex"


def _codex_default_model() -> str:
    """Read ``model = "..."`` from the user's Codex config.toml (best-effort)."""
    config = _codex_home() / "config.toml"
    try:
        text = config.read_text(encoding="utf-8")
    except Exception:
        return ""
    # The default model is the top-level ``model = "..."`` (ignore nested
    # ``[profiles.*] model`` by matching only a line-start assignment).
    match = re.search(r'(?m)^\s*model\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else ""


async def _claude_options() -> BackendOptions:
    from deeptutor.services.subagent.claude_models import load_cached_claude_models

    backend = get_backend("claude_code")
    ok, text = await probe_version([backend.cli_command, "--version"]) if backend else (False, "")
    # Prefer a live-synced catalog (scraped from ``/model``); fall back to the
    # curated aliases until the user syncs.
    cached, synced_at = load_cached_claude_models()
    pairs = [(m["slug"], m["display_name"]) for m in cached] or list(_CLAUDE_MODELS)
    return BackendOptions(
        kind="claude_code",
        display_name="Claude Code",
        available=ok,
        version=text if ok else "",
        default_model="",
        models=[
            ModelOption(slug=slug, display_name=name, efforts=list(_CLAUDE_EFFORTS))
            for slug, name in pairs
        ],
        efforts=list(_CLAUDE_EFFORTS),
        allow_custom_model=True,
        synced_at=synced_at,
        detail="" if ok else (text or "claude CLI not found on PATH"),
    )


async def _codex_options() -> BackendOptions:
    backend = get_backend("codex")
    ok, version = (
        await probe_version([backend.cli_command, "--version"]) if backend else (False, "")
    )
    models: list[ModelOption] = []
    synced_at = ""
    cache = _codex_home() / "models_cache.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        synced_at = str(data.get("fetched_at") or "")
        for entry in data.get("models", []):
            if not isinstance(entry, dict) or not entry.get("slug"):
                continue
            efforts = [
                str(level.get("effort"))
                for level in entry.get("supported_reasoning_levels", [])
                if isinstance(level, dict) and level.get("effort")
            ]
            models.append(
                ModelOption(
                    slug=str(entry["slug"]),
                    display_name=str(entry.get("display_name") or entry["slug"]),
                    default_effort=str(entry.get("default_reasoning_level") or ""),
                    efforts=efforts,
                )
            )
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("failed to read codex models cache", exc_info=True)
    return BackendOptions(
        kind="codex",
        display_name="Codex",
        available=ok,
        version=version if ok else "",
        default_model=_codex_default_model(),
        models=models,
        efforts=["none", "minimal", "low", "medium", "high", "xhigh"],
        allow_custom_model=True,
        synced_at=synced_at,
        detail="" if ok else (version or "codex CLI not found on PATH"),
    )


async def list_backend_options() -> list[BackendOptions]:
    """Synced model/effort options for every backend (the /settings sync source)."""
    return [await _claude_options(), await _codex_options()]


async def sync_backend_options(kind: str) -> BackendOptions:
    """Refresh and return one backend's options (the /settings "sync" action).

    Claude Code has no machine-readable catalog, so we actively scrape its
    ``/model`` TUI and cache the result. Codex's cache is maintained by its own
    CLI, so syncing is just a fresh read.
    """
    if kind == "claude_code":
        from deeptutor.services.subagent.claude_models import sync_claude_models

        await sync_claude_models()  # writes the cache that _claude_options reads
        return await _claude_options()
    return await _codex_options()


__all__ = [
    "BackendOptions",
    "ModelOption",
    "list_backend_options",
    "sync_backend_options",
]
