"""Long-running setup work: installing a parsing engine, fetching its weights.

Both jobs already exist as background subprocess managers with a cursor-based
line log — the settings page starts one and polls it. This module wraps them so
the *chat* surface can run the same job differently: start it, then follow the
log to completion inside a single tool call, relaying each new line through the
turn's event sink.

That shape is chosen for the user, not for convenience. A model that had to
poll would burn one LLM round-trip per check, so progress would arrive in
lurches between silences, and a ten-minute model download would cost a dozen
paid turns. Following the log inside one call gives a live feed for the price
of one.

What may be run is fixed by the same allow-lists the HTTP endpoints use
(``ENGINE_PIP_SPECS``, ``ENGINE_MODEL_DOWNLOADERS``, MinerU's own resolver).
The model supplies an engine id, never a package name or a command, so no
prompt — or anything an attacker managed to get into one — can turn this into
arbitrary installation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

JobAction = Literal["install_engine", "download_models"]

# A job may legitimately run for a long time (multi-GB weights over a slow
# link). The cap only bounds how long the *tool call* follows it: the job keeps
# running in the background afterwards and the user is told how to check back,
# rather than the turn hanging indefinitely.
_MAX_FOLLOW_SECONDS = 30 * 60
_POLL_INTERVAL_SECONDS = 1.0
# Emit a keep-alive after this much silence. Must stay comfortably under the
# chat client's smallest configurable response timeout (30s), which measures
# time since the last event rather than total turn duration.
_HEARTBEAT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class JobOutcome:
    ok: bool
    action: str
    engine: str
    state: str = ""
    message: str = ""
    lines: list[str] = field(default_factory=list)
    still_running: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "engine": self.engine,
            "state": self.state,
            "message": self.message,
            # Only the tail is returned to the model: the full log streamed to
            # the user live, and a pip transcript would otherwise crowd out the
            # turn's context for no decision-making value.
            "log_tail": self.lines[-20:],
            "still_running": self.still_running,
        }


def available_jobs() -> list[dict[str, Any]]:
    """Describe every setup job that could be started right now.

    Availability is computed from the engine registry, so an engine that is
    already installed does not offer an install, and an engine with no
    downloader does not offer a download.
    """
    from deeptutor.services.parsing.engines._install import (
        installable_engines,
        model_downloadable_engines,
    )
    from deeptutor.services.parsing.engines.factory import is_engine_available, list_engines

    out: list[dict[str, Any]] = []
    installable = installable_engines()
    downloadable = model_downloadable_engines()
    for engine in list_engines():
        engine_id = str(engine.get("id") or "")
        if not engine_id:
            continue
        installed = is_engine_available(engine_id)
        if engine_id in installable and not installed:
            out.append(
                {
                    "action": "install_engine",
                    "engine": engine_id,
                    "label": f"Install {engine.get('name') or engine_id}",
                    "detail": str(engine.get("description") or ""),
                }
            )
        if engine_id in downloadable and installed:
            out.append(
                {
                    "action": "download_models",
                    "engine": engine_id,
                    "label": f"Download {engine.get('name') or engine_id} model weights",
                    "detail": "Required before this engine can parse locally. Several GB.",
                }
            )
    # MinerU downloads its weights through its own CLI rather than the shared
    # downloader table, so it is not in ``model_downloadable_engines`` today. The
    # membership check keeps this from becoming a duplicate entry if it is ever
    # added there — the loop above would already have listed it.
    if "mineru" not in downloadable and is_engine_available("mineru"):
        out.append(
            {
                "action": "download_models",
                "engine": "mineru",
                "label": "Download MinerU model weights",
                "detail": "Required for local MinerU parsing. Several GB.",
            }
        )
    return out


def _start_install(engine: str) -> tuple[bool, str, Any]:
    from deeptutor.services.parsing.engines._install import (
        ENGINE_PIP_SPECS,
        get_background_job_manager,
    )

    specs = ENGINE_PIP_SPECS.get(engine)
    if not specs:
        return False, f"There is no one-step install for the '{engine}' engine.", None
    manager = get_background_job_manager()
    started = manager.start_install(engine=engine, specs=specs)
    return bool(started.get("ok")), str(started.get("message") or ""), manager


def _start_model_download(engine: str) -> tuple[bool, str, Any]:
    if engine == "mineru":
        return _start_mineru_download()

    from deeptutor.services.parsing.engines._install import (
        get_background_job_manager,
        model_downloadable_engines,
        resolve_model_downloader,
    )

    if engine not in model_downloadable_engines():
        return False, f"The '{engine}' engine has no model download step.", None
    cmd = resolve_model_downloader(engine)
    if not cmd:
        return (
            False,
            (
                f"The {engine} model downloader was not found. Reinstalling the engine puts "
                "its command back on PATH."
            ),
            None,
        )
    manager = get_background_job_manager()
    started = manager.start_model_download(engine=engine, cmd=cmd)
    return bool(started.get("ok")), str(started.get("message") or ""), manager


def _start_mineru_download() -> tuple[bool, str, Any]:
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service
    from deeptutor.services.parsing.engines.mineru.models import (
        get_model_download_manager,
        resolve_models_downloader,
    )

    settings = get_runtime_settings_service().load_document_parsing()
    engine_settings = (settings.get("engines") or {}).get("mineru") or {}
    resolved = resolve_models_downloader(str(engine_settings.get("local_cli_path") or ""))
    if not resolved.get("found"):
        return (
            False,
            (
                "The MinerU model downloader was not found. MinerU 2.x needs to be installed "
                "first (its 1.x predecessor has no one-step download)."
            ),
            None,
        )
    manager = get_model_download_manager()
    started = manager.start(
        downloader=str(resolved.get("path") or ""),
        model_type=str(engine_settings.get("model_version") or "pipeline"),
        source=str(engine_settings.get("model_download_source") or "huggingface"),
        endpoint=str(engine_settings.get("model_download_endpoint") or ""),
    )
    return bool(started.get("ok")), str(started.get("message") or ""), manager


async def run_job(
    action: str,
    engine: str,
    *,
    on_line: Callable[[str], Awaitable[None]] | None = None,
) -> JobOutcome:
    """Start a setup job and follow its log until it ends.

    ``on_line`` receives each new log line as it appears so the caller can
    relay it live. Returns once the job reaches a terminal state, or once the
    follow budget runs out — in which case ``still_running`` is True and the
    job continues in the background.
    """
    normalized = str(action or "").strip().lower()
    engine_id = str(engine or "").strip().lower().replace("-", "_")

    if normalized == "install_engine":
        ok, message, manager = _start_install(engine_id)
    elif normalized == "download_models":
        ok, message, manager = _start_model_download(engine_id)
    else:
        return JobOutcome(
            ok=False,
            action=normalized,
            engine=engine_id,
            message=f"Unknown setup job '{action}'.",
        )

    if not ok or manager is None:
        return JobOutcome(ok=False, action=normalized, engine=engine_id, message=message)

    lines: list[str] = []
    cursor = 0
    waited = 0.0
    quiet = 0.0
    state = "running"
    final_message = ""
    while waited < _MAX_FOLLOW_SECONDS:
        # ``status`` only touches an in-memory buffer under a short lock, but it
        # is still a blocking call — keep it off the event loop so the turn's
        # other streaming is not stalled by it.
        status = await asyncio.to_thread(manager.status, cursor)
        cursor = int(status.get("next_cursor") or cursor)
        new_lines = [str(line) for line in status.get("lines") or []]
        for text in new_lines:
            lines.append(text)
            if on_line is not None:
                await on_line(text)
        quiet = 0.0 if new_lines else quiet + _POLL_INTERVAL_SECONDS
        state = str(status.get("state") or "running")
        final_message = str(status.get("message") or "")
        if state in {"done", "failed", "cancelled"}:
            break
        if quiet >= _HEARTBEAT_SECONDS and on_line is not None:
            # Long silences are normal — pip downloading a large wheel emits
            # nothing for minutes. The chat client times out on *time since the
            # last event*, not total duration, so without a heartbeat the user's
            # turn is declared dead while the install is healthy and running.
            await on_line(f"… still working ({int(waited)}s elapsed)")
            quiet = 0.0
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        waited += _POLL_INTERVAL_SECONDS

    if state == "running":
        return JobOutcome(
            ok=True,
            action=normalized,
            engine=engine_id,
            state=state,
            message=(
                f"Still running after {_MAX_FOLLOW_SECONDS // 60} minutes; it continues in "
                "the background. Check back with inspect_setup."
            ),
            lines=lines,
            still_running=True,
        )
    return JobOutcome(
        ok=state == "done",
        action=normalized,
        engine=engine_id,
        state=state,
        message=final_message,
        lines=lines,
    )


__all__ = ["JobAction", "JobOutcome", "available_jobs", "run_job"]
