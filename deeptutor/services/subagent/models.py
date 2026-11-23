"""Backend option discovery — the synced model + reasoning-effort lists.

The /settings "Partners & Agents" page lets the user pick the model and
reasoning effort DeepTutor drives each backend with. Those lists change over
time (vendors add/retire models), so this is read live, not hard-coded, and the
page's "sync" button just re-reads it:

* **Codex** publishes an authoritative, server-synced cache at
  ``$CODEX_HOME/models_cache.json`` (slugs + per-model reasoning levels) and the
  user's current default in ``config.toml`` — we read both.
* **Claude Code** sync prefers the optional official SDK's initialization
  catalog, then falls back to the terminal picker. Without a successful sync
  we offer version-neutral aliases; the UI also accepts a free-text model.
* **Kimi CLI** has no model-list surface — free text only.
* **Grok CLI** keeps its account-specific CLI defaults, with free-text model
  and effort overrides (the human-readable ``grok models`` catalog is not parsed).
* **opencode / MiMo Code** enumerate ``provider/model`` slugs via their own
  ``<cli> models`` command (models.dev catalog); syncing re-runs it with
  ``--refresh``. Reasoning effort is their ``--variant`` scale.
* **Hermes Agent / OpenClaw / DeepSeek Harness** accept free-text model ids.
  Their official reasoning surfaces are exposed as curated suggestions while
  still allowing the underlying config to carry newer values.

Each backend kind maps to one options provider in ``_PROVIDERS`` — adding a
backend means adding a provider here, nothing else changes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import signal
import time
from typing import Any

from deeptutor.services.subagent.process import (
    not_found_detail,
    probe_version,
    resolve_cli_command,
)
from deeptutor.services.subagent.registry import get_backend

logger = logging.getLogger(__name__)

# Claude Code: curated fallback used until a live ``/model`` sync populates the
# cache (see ``claude_models``). The aliases + ``[1m]`` variants mirror the
# ``/model`` picker; the UI also accepts a free-text model name.
_CLAUDE_MODELS = (
    ("opus", "Opus (CLI alias)"),
    ("sonnet", "Sonnet (CLI alias)"),
    ("sonnet[1m]", "Sonnet (1M CLI alias)"),
    ("haiku", "Haiku (CLI alias)"),
)
_CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# Antigravity CLI: ``--effort`` accepts low|medium|high|xhigh|max.
_ANTIGRAVITY_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_AGY_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_AGY_HEADER_SLUGS = frozenset({"model", "models", "id", "slug"})
_AGY_HEADER_NAMES = frozenset({"name", "display", "display name", "description"})

# opencode family: ``--variant`` — provider-relative reasoning effort.
_OPENCODE_EFFORTS = ("minimal", "high", "max")

_HERMES_EFFORTS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)
_OPENCLAW_EFFORTS = ("off", "minimal", "low", "medium", "high", "xhigh")
_DEEPSEEK_HARNESS_EFFORTS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)


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
    # Where the current ``models`` list came from: "sdk", "tui", "cache", "cli",
    # "fallback", or "none" when the backend has no enumerable catalog.
    catalog_source: str = ""
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
            "catalog_source": self.catalog_source,
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
    from deeptutor.services.subagent.claude_models import load_cached_claude_catalog

    backend = get_backend("claude_code")
    ok, text = await probe_version([backend.cli_command, "--version"]) if backend else (False, "")
    # Prefer a live-synced catalog (SDK handshake or ``/model`` scrape); fall
    # back to curated aliases until the user syncs.
    cached, synced_at, cached_source = load_cached_claude_catalog()
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
        catalog_source=cached_source if cached else "fallback",
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
        catalog_source="cache" if models else "none",
        detail="" if ok else (version or "codex CLI not found on PATH"),
    )


async def _probe(kind: str) -> tuple[bool, str]:
    backend = get_backend(kind)
    if backend is None:
        return False, ""
    return await probe_version([backend.cli_command, "--version"])


def _parse_antigravity_models(text: str) -> list[ModelOption]:
    """Parse ``agy models`` output into ``ModelOption`` entries.

    Non-TTY stdout uses ``<slug>\\t<display name>``; TTY output uses padded
    columns (2+ spaces) and may prepend spinner frames separated by ``\\r``.
    """
    models: list[ModelOption] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = _ANSI_ESCAPE_RE.sub("", raw.rsplit("\r", 1)[-1]).strip()
        if not line:
            continue
        parts = re.split(r"\t+|\s{2,}", line, maxsplit=1)
        slug = parts[0].strip()
        display = parts[1].strip() if len(parts) > 1 else ""
        if (
            not slug
            or slug.endswith(".")
            or ".." in slug
            or not _AGY_SLUG_RE.match(slug)
        ):
            continue
        if slug.lower() in _AGY_HEADER_SLUGS and display.lower() in _AGY_HEADER_NAMES:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        models.append(
            ModelOption(
                slug=slug,
                display_name=display or slug,
                efforts=list(_ANTIGRAVITY_EFFORTS),
            )
        )
    return models


_ANTIGRAVITY_CACHE_TTL_S = 300.0
_antigravity_models_cache: tuple[str, list[ModelOption], str, float] | None = None


async def _terminate_subprocess(
    process: asyncio.subprocess.Process,
    *,
    force_group: bool = False,
) -> None:
    """Terminate a timed-out or cancelled subprocess (and its POSIX process group).

    When ``force_group`` is true, signal the POSIX process group even if the
    group leader already exited (a descendant may still hold stdout open).
    """
    if process.returncode is not None and not force_group:
        return
    if os.name == "posix":
        with suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.returncode is None:
        with suppress(ProcessLookupError, OSError):
            process.kill()
        with suppress(TimeoutError, asyncio.TimeoutError, OSError):
            await asyncio.wait_for(process.wait(), timeout=2.0)


async def _list_antigravity_models(cli_command: str) -> list[ModelOption]:
    """Run ``agy models`` and return its live account model catalog."""
    cmd = resolve_cli_command([cli_command, "models"])
    process: asyncio.subprocess.Process | None = None
    timed_out_or_cancelled = False
    spawn_kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.DEVNULL,
    }
    if os.name == "posix":
        spawn_kwargs["start_new_session"] = True
    try:
        process = await asyncio.create_subprocess_exec(*cmd, **spawn_kwargs)
        out, _ = await asyncio.wait_for(process.communicate(), timeout=20.0)
    except FileNotFoundError:
        return []
    except (TimeoutError, asyncio.TimeoutError):
        timed_out_or_cancelled = True
        return []
    except asyncio.CancelledError:
        timed_out_or_cancelled = True
        raise
    except Exception:  # pragma: no cover - defensive
        logger.warning("failed to enumerate %s models", cli_command, exc_info=True)
        return []
    finally:
        if process is not None and (process.returncode is None or timed_out_or_cancelled):
            await asyncio.shield(
                _terminate_subprocess(process, force_group=timed_out_or_cancelled)
            )
    if process.returncode != 0:
        return []
    return _parse_antigravity_models((out or b"").decode("utf-8", "replace"))


async def _antigravity_options(
    *,
    include_models: bool = True,
    refresh: bool = False,
) -> BackendOptions:
    global _antigravity_models_cache
    from deeptutor.services.subagent.antigravity import (
        _NOT_FOUND_DETAIL as _ANTIGRAVITY_NOT_FOUND,
    )

    backend = get_backend("antigravity")
    cli = backend.cli_command if backend else "agy"
    ok, version = await _probe("antigravity")
    models: list[ModelOption] = []
    synced_at = ""
    if ok and include_models:
        now = time.monotonic()
        cached = _antigravity_models_cache
        if (
            not refresh
            and cached is not None
            and cached[0] == cli
            and now - cached[3] < _ANTIGRAVITY_CACHE_TTL_S
        ):
            models = list(cached[1])
            synced_at = cached[2]
        else:
            models = await _list_antigravity_models(cli)
            synced_at = datetime.now(timezone.utc).isoformat() if models else ""
            if models:
                _antigravity_models_cache = (cli, list(models), synced_at, now)
    return BackendOptions(
        kind="antigravity",
        display_name="Antigravity CLI",
        available=ok,
        version=version if ok else "",
        models=models,
        efforts=list(_ANTIGRAVITY_EFFORTS),
        allow_custom_model=True,
        synced_at=synced_at,
        catalog_source="cli" if models else "none",
        detail="" if ok else not_found_detail(version, _ANTIGRAVITY_NOT_FOUND),
    )


async def _kimi_options() -> BackendOptions:
    ok, version = await _probe("kimi")
    return BackendOptions(
        kind="kimi",
        display_name="Kimi CLI",
        available=ok,
        version=version if ok else "",
        models=[],  # no model-list surface; free text only
        efforts=[],
        allow_custom_model=True,
        catalog_source="none",
        detail="" if ok else (version or "kimi CLI not found on PATH"),
    )


async def _grok_options() -> BackendOptions:
    backend = get_backend("grok")
    detected = await backend.detect() if backend else None
    return BackendOptions(
        kind="grok",
        display_name="Grok CLI",
        available=detected.available if detected else False,
        version=detected.version if detected else "",
        # `grok models` is human-readable and account-specific. Keep the CLI
        # default or accept a model/effort the operator has verified there.
        models=[],
        efforts=[],
        allow_custom_model=True,
        catalog_source="none",
        detail=detected.detail if detected else "Grok CLI backend unavailable",
    )


async def _list_cli_models(cli_command: str, *, refresh: bool = False) -> list[ModelOption]:
    """Parse ``<cli> models`` output — one ``provider/model`` slug per line."""
    cmd = [cli_command, "models"]
    if refresh:
        cmd.append("--refresh")
    cmd = resolve_cli_command(cmd)
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(process.communicate(), timeout=60.0 if refresh else 20.0)
    except FileNotFoundError:
        return []
    except (TimeoutError, asyncio.TimeoutError):
        return []
    except Exception:  # pragma: no cover - defensive
        logger.warning("failed to enumerate %s models", cli_command, exc_info=True)
        return []
    models: list[ModelOption] = []
    for raw in (out or b"").decode("utf-8", "replace").splitlines():
        slug = raw.strip()
        # Slugs are provider/model tokens; anything with spaces is decoration.
        if not slug or "/" not in slug or " " in slug:
            continue
        models.append(ModelOption(slug=slug, display_name=slug, efforts=list(_OPENCODE_EFFORTS)))
    return models


async def _opencode_family_options(
    kind: str, display_name: str, *, refresh: bool = False
) -> BackendOptions:
    backend = get_backend(kind)
    cli = backend.cli_command if backend else kind
    ok, version = await _probe(kind)
    models = await _list_cli_models(cli, refresh=refresh) if ok else []
    return BackendOptions(
        kind=kind,
        display_name=display_name,
        available=ok,
        version=version if ok else "",
        models=models,
        efforts=list(_OPENCODE_EFFORTS),
        allow_custom_model=True,
        synced_at=datetime.now(timezone.utc).isoformat() if models else "",
        catalog_source="cli" if models else "none",
        detail="" if ok else (version or f"{cli} CLI not found on PATH"),
    )


async def _opencode_options(*, refresh: bool = False) -> BackendOptions:
    return await _opencode_family_options("opencode", "opencode", refresh=refresh)


async def _mimo_options(*, refresh: bool = False) -> BackendOptions:
    return await _opencode_family_options("mimo", "MiMo Code", refresh=refresh)


async def _free_text_options(
    kind: str, display_name: str, efforts: tuple[str, ...]
) -> BackendOptions:
    backend = get_backend(kind)
    ok, version = await _probe(kind)
    sdk_available = False
    if kind == "deepseek_harness" and not ok:
        from deeptutor.services.subagent.deepseek_harness import _sdk_available

        sdk_available = _sdk_available()
    available = ok or sdk_available
    cli = backend.cli_command if backend else kind
    return BackendOptions(
        kind=kind,
        display_name=display_name,
        available=available,
        version=version if ok else ("Python SDK" if sdk_available else ""),
        models=[],
        efforts=list(efforts),
        allow_custom_model=True,
        catalog_source="none",
        detail="" if available else not_found_detail(version, f"{cli} CLI not found on PATH"),
    )


async def _hermes_options() -> BackendOptions:
    return await _free_text_options("hermes", "Hermes Agent", _HERMES_EFFORTS)


async def _hermes_remote_options() -> BackendOptions:
    backend = get_backend("hermes_remote")
    detected = await backend.detect() if backend else None
    return BackendOptions(
        kind="hermes_remote",
        display_name="Hermes Agent (remote)",
        available=detected.available if detected else False,
        version=detected.version if detected else "",
        models=[],
        efforts=list(_HERMES_EFFORTS),
        allow_custom_model=True,
        catalog_source="none",
        detail=detected.detail if detected else "incompatible",
    )


async def _openclaw_options() -> BackendOptions:
    return await _free_text_options("openclaw", "OpenClaw", _OPENCLAW_EFFORTS)


async def _deepseek_harness_options() -> BackendOptions:
    return await _free_text_options(
        "deepseek_harness", "DeepSeek Harness", _DEEPSEEK_HARNESS_EFFORTS
    )


# One provider per backend kind — the discovery order is the settings order.
_PROVIDERS: dict[str, Callable[..., Awaitable[BackendOptions]]] = {
    "claude_code": _claude_options,
    "codex": _codex_options,
    "grok": _grok_options,
    "antigravity": _antigravity_options,
    "kimi": _kimi_options,
    "opencode": _opencode_options,
    "mimo": _mimo_options,
    "hermes": _hermes_options,
    "hermes_remote": _hermes_remote_options,
    "openclaw": _openclaw_options,
    "deepseek_harness": _deepseek_harness_options,
}


async def list_backend_options(*, include_account_catalogs: bool = True) -> list[BackendOptions]:
    """Synced model/effort options for every backend (the /settings sync source)."""

    async def _run(kind: str, provider: Callable[..., Awaitable[BackendOptions]]) -> BackendOptions:
        if kind == "antigravity" and not include_account_catalogs:
            return await _antigravity_options(include_models=False)
        return await provider()

    results = await asyncio.gather(*(_run(k, p) for k, p in _PROVIDERS.items()))
    return list(results)


async def sync_backend_options(kind: str) -> BackendOptions:
    """Refresh and return one backend's options (the /settings "sync" action).

    Claude Code has no machine-readable catalog, so we actively scrape its
    ``/model`` TUI and cache the result. Codex's cache is maintained by its own
    CLI (a fresh read suffices), Antigravity re-runs ``agy models``, and the
    opencode family re-runs ``models --refresh``. The rest have nothing
    external to refresh.
    """
    if kind == "claude_code":
        from deeptutor.services.subagent.claude_models import sync_claude_models

        await sync_claude_models()  # writes the cache that _claude_options reads
        return await _claude_options()
    if kind == "antigravity":
        return await _antigravity_options(include_models=True, refresh=True)
    if kind in ("opencode", "mimo"):
        return await _PROVIDERS[kind](refresh=True)
    provider = _PROVIDERS.get(kind, _codex_options)
    return await provider()


__all__ = [
    "BackendOptions",
    "ModelOption",
    "list_backend_options",
    "sync_backend_options",
]
