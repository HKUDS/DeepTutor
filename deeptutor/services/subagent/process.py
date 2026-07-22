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
import logging
import os

logger = logging.getLogger(__name__)

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
    process = await asyncio.create_subprocess_exec(
        *cmd,
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


async def probe_version(cmd: Sequence[str], *, timeout: float = 8.0) -> tuple[bool, str]:
    """Run a fast ``--version``-style probe; return ``(ok, stdout-or-error)``.

    Used by backend ``detect`` to answer "is this CLI installed here?" without
    the no-timeout consult semantics — a probe that hangs is a failed probe.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
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


__all__ = ["ProcessLine", "stream_process_lines", "probe_version"]
