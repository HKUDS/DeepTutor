"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from deeptutor.tutorbot.providers.base import LLMProvider

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.  This avoids free-text parsing
    and the unreliable HEARTBEAT_OK token.

    Phase 2 (execution): only triggered when Phase 1 returns ``run``.  The
    ``on_execute`` callback runs the task through the full agent loop and
    returns the result to deliver.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self._base_interval_s = interval_s
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_mtime: float | None = None
        self._last_content_hash: str | None = None
        self._consecutive_skips: int = 0

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> tuple[str | None, float | None]:
        """Returns (content, mtime) or (None, None) if missing/invalid."""
        if self.heartbeat_file.exists():
            try:
                stat = self.heartbeat_file.stat()
                content = self.heartbeat_file.read_text(encoding="utf-8")
                return content, stat.st_mtime
            except Exception:
                return None, None
        return None, None

    def _apply_adaptive_interval(self) -> None:
        """Double interval after consecutive skips, up to 4x the base."""
        if self._consecutive_skips >= 2:
            multiplier = min(2 ** (self._consecutive_skips - 1), 4)
            new_interval = int(self._base_interval_s * multiplier)
            if new_interval != self.interval_s:
                self.interval_s = new_interval
                logger.debug(
                    "Heartbeat: {} consecutive skips, extended interval to {}s (base={}s)",
                    self._consecutive_skips,
                    self.interval_s,
                    self._base_interval_s,
                )

    def _reset_adaptive_interval(self) -> None:
        """Reset to base interval."""
        if self.interval_s != self._base_interval_s:
            old = self.interval_s
            self.interval_s = self._base_interval_s
            logger.debug(
                "Heartbeat: reset interval from {}s to {}s",
                old,
                self._base_interval_s,
            )

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        response = await self.provider.chat_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision.",
                },
                {
                    "role": "user",
                    "content": (
                        "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                        f"{content}"
                    ),
                },
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        from deeptutor.tutorbot.utils.evaluator import evaluate_response

        content, mtime = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            self._reset_adaptive_interval()
            return

        # Option 2: skip LLM if file hasn't changed since last tick
        if mtime == self._last_mtime and self._last_content_hash is not None:
            if content == self._last_content_hash:
                logger.debug("Heartbeat: HEARTBEAT.md unchanged, skipping LLM")
                self._consecutive_skips += 1
                self._apply_adaptive_interval()
                return

        self._last_mtime = mtime
        self._last_content_hash = content
        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                self._consecutive_skips += 1
                self._apply_adaptive_interval()
                return

            # Reset on active work
            self._reset_adaptive_interval()
            self._consecutive_skips = 0

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                response = await self.on_execute(tasks)

                if response:
                    should_notify = await evaluate_response(
                        response,
                        tasks,
                        self.provider,
                        self.model,
                    )
                    if should_notify and self.on_notify:
                        logger.info("Heartbeat: completed, delivering response")
                        await self.on_notify(response)
                    else:
                        logger.info("Heartbeat: silenced by post-run evaluation")
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content, _ = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)
