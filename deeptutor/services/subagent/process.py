"""Stream a child process's stdout/stderr line-by-line as it runs.

The single low-level primitive the subagent backends share: spawn a command and
yield every stdout and stderr line the moment it arrives — so a long, multi-step
agent run surfaces live in the sidebar instead of all at once at the end — then
guarantee the process is torn down when the consumer stops early or the turn is
cancelled.

There is deliberately **no timeout** on the wait: per the product contract,
DeepTutor waits unconditionally for the subagent's own logic to finish; only the
subagent exiting (cleanly or with an error) ends the stream. Cancellation (the
user aborting the turn) propagates as ``CancelledError`` and the ``finally``
block terminates the child so no orphaned agent process is left behind.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
import contextlib
import json
import logging
import os
import shutil
from typing import Any

logger = logging.getLogger(__name__)


def resolve_cli_command(cmd: Sequence[str], *, path: str | None = None) -> list[str]:
    """Resolve ``cmd[0]`` to a full path via PATH/PATHEXT before spawning.

    On Windows, ``asyncio.create_subprocess_exec`` (and the underlying
    ``CreateProcess``) only appends ``.exe`` when resolving a bare command
    name, so CLIs installed by npm ship as ``.cmd``/``.bat``/``.ps1`` shims
    (e.g. ``claude``/``codex``) are invisible and the spawn raises
    ``FileNotFoundError`` — the backend then reports "not installed" even
    though the CLI is on PATH. ``shutil.which`` honors ``PATHEXT`` (and a
    caller-supplied PATH) and returns the shim's full path, so the spawn
    finds it.

    Returns the command unchanged when ``cmd`` is empty, when ``cmd[0]`` is
    already an absolute path (resolved back to itself), or when nothing on
    PATH matches — in that last case the OS spawn behaves exactly as before,
    preserving the existing ``FileNotFoundError`` semantics callers handle.
    """
    if not cmd:
        return list(cmd)
    resolved = shutil.which(cmd[0], path=path)
    if resolved:
        return [resolved, *list(cmd[1:])]
    return list(cmd)


# (channel, text) where channel is "stdout", "stderr", or "exit" (the final
# item, whose text is the integer return code as a string).
ProcessLine = tuple[str, str]

_TERMINATE_GRACE_SECONDS = 5.0


async def stream_process_lines(
    cmd: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> AsyncIterator[ProcessLine]:
    """Yield ``(channel, line)`` for each stdout/stderr line until the process exits.

    The final item is always ``("exit", "<returncode>")`` so callers can tell a
    clean finish from an early break. stdout and stderr are interleaved in
    arrival order via a shared queue.
    """
    full_env = {**os.environ, **(env or {})}
    resolved_cmd = resolve_cli_command(cmd, path=full_env.get("PATH"))
    process = await asyncio.create_subprocess_exec(
        *resolved_cmd,
        cwd=cwd or None,
        env=full_env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    queue: asyncio.Queue[ProcessLine | None] = asyncio.Queue()

    async def _pump(stream: asyncio.StreamReader | None, channel: str) -> None:
        if stream is None:
            await queue.put(None)
            return
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                await queue.put((channel, raw.decode("utf-8", "replace").rstrip("\r\n")))
        except Exception:  # pragma: no cover - defensive: a broken pipe must not hang the queue
            logger.debug("subagent %s pump failed", channel, exc_info=True)
        finally:
            await queue.put(None)  # sentinel: this channel is drained

    readers = [
        asyncio.create_task(_pump(process.stdout, "stdout")),
        asyncio.create_task(_pump(process.stderr, "stderr")),
    ]
    drained = 0
    try:
        while drained < len(readers):
            item = await queue.get()
            if item is None:
                drained += 1
                continue
            yield item
        returncode = await process.wait()
        yield "exit", str(returncode)
    finally:
        for task in readers:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*readers, return_exceptions=True)
        await _terminate(process)


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Best-effort teardown: terminate, wait briefly, then kill."""
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        return
    except (TimeoutError, asyncio.TimeoutError):
        pass
    except ProcessLookupError:  # pragma: no cover
        return
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    with contextlib.suppress(Exception):
        await process.wait()


def not_found_detail(probe_text: str, fallback: str) -> str:
    """What to show a reader when a CLI probe failed.

    :func:`probe_version` reports a bare ``"not installed"`` for a missing
    binary, which repeats what the status chip already says and crowds out the
    backend's own guidance — every caller writing ``version or "<cli> not found
    on PATH"`` was in fact unreachable for the common case. Real probe output (a
    version banner, a permission error) is more informative and still wins.
    """
    text = (probe_text or "").strip()
    return fallback if text in ("", "not installed") else text


async def probe_version(cmd: Sequence[str], *, timeout: float = 8.0) -> tuple[bool, str]:
    """Run a fast ``--version``-style probe; return ``(ok, stdout-or-error)``.

    Used by backend ``detect`` to answer "is this CLI installed here?" without
    the no-timeout consult semantics — a probe that hangs is a failed probe.
    """
    try:
        resolved_cmd = resolve_cli_command(cmd)
        process = await asyncio.create_subprocess_exec(
            *resolved_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return False, "not installed"
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        await _terminate(process)
        return False, "probe timed out"
    text = (out or b"").decode("utf-8", "replace").strip()
    return process.returncode == 0, text


#: How much of one event field reaches the trace. Four CLI backends render
#: the same kind of line, so they bound it the same way.
MAX_FIELD_CHARS = 4000


def truncate_field(text: str) -> str:
    """Trim one trace field to :data:`MAX_FIELD_CHARS`, marking the cut."""
    text = text.strip()
    if len(text) > MAX_FIELD_CHARS:
        return text[:MAX_FIELD_CHARS].rstrip() + " …"
    return text


def compact_field(obj: Any) -> str:
    """Render an arbitrary event value as one bounded, single-line string."""
    try:
        text = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(obj)
    return truncate_field(text)


__all__ = [
    "MAX_FIELD_CHARS",
    "ProcessLine",
    "compact_field",
    "not_found_detail",
    "probe_version",
    "truncate_field",
    "resolve_cli_command",
    "stream_process_lines",
]
