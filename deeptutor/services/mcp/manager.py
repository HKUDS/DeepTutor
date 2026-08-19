"""
MCP connection manager
======================

App-level singleton that owns the lifecycle of every configured MCP server
connection and exposes their tools as chat :class:`BaseTool` adapters.

Lifecycle model
---------------

DeepTutor's chat runs as per-turn tasks inside one event loop, while MCP
sessions must be opened and closed inside the same task (the SDK's anyio
cancel scopes are task-bound). Each server therefore gets a dedicated
*connection task* that owns its ``AsyncExitStack`` end-to-end::

    connect → enter transports/session in the task → publish adapters →
    wait on a shutdown event → exit the stack in the same task

``ensure_started()`` is lazy (first turn pays the connect cost, capped by a
per-server timeout) and cheap afterwards. ``reload()`` diffs the persisted
config against live connections and only restarts servers whose
configuration actually changed.

Tool adapters are flagged ``deferred`` — their schemas reach the model via
the ``load_tools`` progressive-disclosure flow, not the initial tool list —
and are synced into the global :class:`ToolRegistry` so the regular dispatch
path executes them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import hashlib
import logging
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.services.mcp.config import (
    MCPConfig,
    MCPServerConfig,
    load_mcp_config,
)

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_S = 15
_NAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]")

#: Owner key for the deployment's servers from the admin ``mcp.json``.
#: Connections are keyed by ``(owner, server_name)`` so a
#: future per-user server cannot collide with — or be routed into — another
#: tenant's live session.
SHARED_OWNER = "_shared"

#: Matches the MCP SDK's ``ProgressFnT``: ``(progress, total, message)``. Spelled
#: out here rather than imported so this module keeps its lazy ``mcp`` import —
#: the package is an optional dependency.
ProgressCallback = Callable[[float, float | None, str | None], Awaitable[None]]

# A server that failed to connect is retried, with backoff, on later turns
# instead of staying dead for the process's lifetime.
_RETRY_BACKOFF_START_S = 30.0
_RETRY_BACKOFF_MAX_S = 300.0

# Bounds on per-account scopes: every connected server is a live session in this
# one process, so a deployment with hundreds of accounts must not accumulate
# them. Cold scopes are dropped when a new one arrives; the next turn for that
# account reconnects.
_MAX_OWNER_SCOPES = 64
_SCOPE_IDLE_TTL_S = 900.0


class ConnectionLost(RuntimeError):
    """A server's connection task ended while one of its tools was in flight."""


def _connection_lost_result(server_name: str, exc: BaseException) -> str:
    """What the model is told when the transport died under its tool call."""
    return f"(MCP server {server_name!r} connection failed during the call: {exc})"


# The literal prefix of ``secrets.SECRET_REFERENCE_RE``. Kept as a plain string
# so fingerprinting never has to import the secrets module.
_SECRET_REFERENCE_MARKER = "${secret:"


# Transient transport errors worth exactly one retry (mirrors nanobot).
_TRANSIENT_ERRORS = (
    BrokenPipeError,
    ConnectionResetError,
)


def wrapped_tool_name(server: str, tool: str) -> str:
    """``mcp_<server>_<tool>`` with non-identifier characters sanitised."""
    return f"mcp_{_NAME_SANITIZE_RE.sub('_', server)}_{_NAME_SANITIZE_RE.sub('_', tool)}"


class MCPToolAdapter(BaseTool):
    """One MCP server tool exposed as a chat tool (deferred by default)."""

    deferred = True
    #: Provider kind read by the deferred-tool manifest and the trace layer.
    provider_kind = "mcp"

    def __init__(
        self,
        *,
        manager: "MCPConnectionManager",
        server_name: str,
        original_name: str,
        description: str,
        input_schema: dict[str, Any] | None,
        tool_timeout: int,
        owner: str = SHARED_OWNER,
    ) -> None:
        self._manager = manager
        self._owner = owner
        self._server_name = server_name
        self._original_name = original_name
        self._wrapped_name = wrapped_tool_name(server_name, original_name)
        self._description = description or original_name
        self._input_schema = input_schema or {"type": "object", "properties": {}}
        self._tool_timeout = tool_timeout

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def provider_id(self) -> str:
        """Provider grouping key (this server's name)."""
        return self._server_name

    @property
    def server_name(self) -> str:
        """Deprecated alias for :attr:`provider_id`; kept for API compatibility."""
        return self._server_name

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._wrapped_name,
            description=f"[{self._server_name}] {self._description}",
            raw_parameters=self._input_schema,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        # The sink is the dispatcher's channel into this call's own sub-trace.
        # Handed on rather than discarded: MCP servers report progress as
        # notifications during a long call, and that is the only thing a reader
        # has to look at while a five-minute render or crawl is running.
        event_sink = kwargs.pop("event_sink", None)
        text = await self._manager.call_tool(
            self._owner,
            self._server_name,
            self._original_name,
            kwargs,
            timeout=self._tool_timeout,
            on_progress=_progress_reporter(event_sink, self._server_name) if event_sink else None,
        )
        return ToolResult(
            content=text,
            metadata={
                "mcp_server": self._server_name,
                "mcp_tool": self._original_name,
            },
        )


def _progress_reporter(event_sink: Any, server_name: str) -> "ProgressCallback":
    """Turn a server's progress notifications into trace events.

    Shaped to the MCP SDK's ``ProgressFnT`` — ``(progress, total, message)``,
    where a server may send any subset: a message with no numbers, numbers with
    no message, or a bare tick. Each case still has to render as *something*, or
    a server that reports diligently would look identical to one that reports
    nothing.

    Never raises: this runs inside the SDK's notification handler, and a failure
    here would surface as a broken tool call rather than a missing status line.
    """

    async def _report(progress: float, total: float | None, message: str | None) -> None:
        text = (message or "").strip()
        fraction: float | None = None
        if total and total > 0:
            fraction = max(0.0, min(1.0, progress / total))
            percent = int(round(fraction * 100))
            text = f"{text} ({percent}%)" if text else f"{percent}%"
        elif not text:
            # A bare tick, which is still the difference between "working" and
            # "hung". Report the raw counter rather than inventing a percentage.
            text = f"step {progress:g}"
        try:
            await event_sink(
                "tool_progress",
                text,
                {
                    "tool_source": "mcp",
                    "tool_provider": server_name,
                    **({"progress_fraction": fraction} if fraction is not None else {}),
                },
            )
        except Exception:  # noqa: BLE001 - a status line must never fail a call
            logger.debug("could not publish MCP progress for %s", server_name, exc_info=True)

    return _report


@dataclass
class _ServerConnection:
    """Live state for one configured server."""

    name: str
    config: MCPServerConfig
    signature: str
    owner: str = SHARED_OWNER
    status: str = "connecting"  # connecting | connected | error | needs_auth | disabled
    error: str = ""
    adapters: list[MCPToolAdapter] = field(default_factory=list)
    session: Any = None
    task: asyncio.Task | None = None
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    # Backoff state for a failed connection (monotonic loop time).
    retry_at: float = 0.0
    retry_delay: float = _RETRY_BACKOFF_START_S


class MCPConnectionManager:
    """Owns all MCP server connections; one instance per process.

    Connections are keyed by ``(owner, server_name)``. A tool adapter carries
    its owner and passes it to :meth:`call_tool`, so a call can only ever reach
    the session it was created from — two owners may legitimately name a server
    the same thing.
    """

    def __init__(self) -> None:
        self._connections: dict[tuple[str, str], _ServerConnection] = {}
        # One lock per owner: a cold connect for one owner must not serialise
        # every other owner's turn behind it.
        self._locks: dict[str, asyncio.Lock] = {}
        # Monotonic time each owner scope was last used, for idle eviction.
        self._scope_used: dict[str, float] = {}
        self._started = False

    def _lock_for(self, owner: str) -> asyncio.Lock:
        lock = self._locks.get(owner)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[owner] = lock
        return lock

    # ── public lifecycle ───────────────────────────────────────────────

    async def ensure_started(self) -> None:
        """Connect every enabled deployment server that isn't live yet.

        Lazy: callers invoke this at turn start; after the first call it only
        retries connections that previously failed and whose backoff expired,
        or picks up servers added via :meth:`reload`.
        """
        if self._started:
            await self._retry_failed(SHARED_OWNER)
            return
        async with self._lock_for(SHARED_OWNER):
            if self._started:
                return
            await self._sync_to_config(load_mcp_config())
            self._started = True

    async def reload(self) -> None:
        """Re-read the persisted config and apply the diff to live connections."""
        async with self._lock_for(SHARED_OWNER):
            await self._sync_to_config(load_mcp_config())
            self._started = True

    async def shutdown(self) -> None:
        for owner in list(self._locks) or [SHARED_OWNER]:
            async with self._lock_for(owner):
                for key, conn in list(self._connections.items()):
                    if key[0] != owner:
                        continue
                    await self._disconnect(conn)
                    self._connections.pop(key, None)
        self._connections.clear()
        self._scope_used.clear()
        self._started = False

    async def ensure_scope(self, owner: str) -> list[MCPToolAdapter]:
        """Connect *owner*'s own servers and return their live tool adapters.

        These adapters are deliberately **not** published to the process
        registry (see :meth:`_register_adapters`): they reach a turn through the
        scoped registry's overlay, so two accounts whose servers share a name
        cannot clobber each other.
        """
        if owner == SHARED_OWNER:
            return self.adapters_for(SHARED_OWNER)
        from deeptutor.services.mcp.user_config import load_user_mcp_config

        async with self._lock_for(owner):
            config, _rejected = load_user_mcp_config(owner)
            if not config.servers and not self._has_scope(owner):
                self._scope_used.pop(owner, None)
                return []
            await self._sync_to_config(config, owner=owner)
            await self._retry_failed_locked(owner)
            self._scope_used[owner] = asyncio.get_running_loop().time()
        await self._evict_cold_scopes(keep=owner)
        return self.adapters_for(owner)

    async def reload_scope(self, owner: str) -> None:
        """Apply *owner*'s config after it changed (a save or a delete).

        Without this the account would keep talking to the server it just
        edited until an idle eviction or a restart.
        """
        if owner == SHARED_OWNER:
            await self.reload()
            return
        from deeptutor.services.mcp.user_config import load_user_mcp_config

        async with self._lock_for(owner):
            config, _rejected = load_user_mcp_config(owner)
            await self._sync_to_config(config, owner=owner)
            self._scope_used[owner] = asyncio.get_running_loop().time()

    def _has_scope(self, owner: str) -> bool:
        return any(conn_owner == owner for conn_owner, _name in self._connections)

    async def _evict_cold_scopes(self, *, keep: str) -> None:
        """Disconnect idle owner scopes so one process cannot hold thousands.

        Lazy rather than swept by a background task: eviction only matters when
        a new scope arrives, and a timer would have to be owned, cancelled, and
        reasoned about across the app's lifespan for no extra benefit.
        """
        now = asyncio.get_running_loop().time()
        cold = [
            owner
            for owner, used in self._scope_used.items()
            if owner != keep and now - used > _SCOPE_IDLE_TTL_S
        ]
        if len(self._scope_used) > _MAX_OWNER_SCOPES:
            ranked = sorted(
                (owner for owner in self._scope_used if owner != keep),
                key=lambda owner: self._scope_used[owner],
            )
            cold.extend(ranked[: len(self._scope_used) - _MAX_OWNER_SCOPES])
        for owner in dict.fromkeys(cold):
            async with self._lock_for(owner):
                for key, conn in list(self._connections.items()):
                    if key[0] != owner:
                        continue
                    await self._disconnect(conn)
                    self._connections.pop(key, None)
            self._scope_used.pop(owner, None)
            self._locks.pop(owner, None)

    async def _retry_failed(self, owner: str) -> None:
        """Reconnect this owner's failed servers whose backoff has expired.

        Without this a server that was briefly unreachable at process start
        stays dead — and keeps advertising tools that always answer "not
        connected" — until an administrator saves the config again.
        """
        async with self._lock_for(owner):
            await self._retry_failed_locked(owner)

    async def _retry_failed_locked(self, owner: str) -> None:
        """As :meth:`_retry_failed`; caller holds this owner's lock."""
        now = asyncio.get_running_loop().time()
        due = [
            conn
            for (conn_owner, _name), conn in self._connections.items()
            if conn_owner == owner and conn.status == "error" and conn.retry_at <= now
        ]
        for conn in due:
            delay, key = conn.retry_delay, (conn.owner, conn.name)
            self._connections.pop(key, None)
            await self._connect(conn.name, conn.config, owner=owner, retry_delay=delay)

    # ── public queries ─────────────────────────────────────────────────

    def status(self, owner: str = SHARED_OWNER) -> list[dict[str, Any]]:
        """Connection status rows for the settings UI (one owner's servers)."""
        rows: list[dict[str, Any]] = []
        for (conn_owner, name), conn in sorted(self._connections.items()):
            if conn_owner != owner:
                continue
            rows.append(
                {
                    "name": name,
                    "transport": conn.config.resolved_type() or "",
                    "status": conn.status,
                    "error": conn.error,
                    "tools": [
                        {
                            "name": a.name,
                            "description": a.get_definition().description,
                        }
                        for a in conn.adapters
                    ],
                }
            )
        return rows

    def adapters_for(self, owner: str = SHARED_OWNER) -> list[MCPToolAdapter]:
        """Live tool adapters belonging to *owner*."""
        out: list[MCPToolAdapter] = []
        for (conn_owner, _name), conn in self._connections.items():
            if conn_owner == owner:
                out.extend(conn.adapters)
        return out

    async def call_tool(
        self,
        owner: str,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: int,
        on_progress: "ProgressCallback | None" = None,
    ) -> str:
        """Invoke a tool on a connected server; one retry on transient errors."""
        conn = self._connections.get((owner, server_name))
        if conn is None or conn.session is None or conn.status != "connected":
            return f"(MCP server {server_name!r} is not connected)"
        try:
            return await self._call_watching_connection(
                conn, tool_name, arguments, timeout, on_progress
            )
        except ConnectionLost as exc:
            logger.warning("MCP tool %s/%s lost its connection: %s", server_name, tool_name, exc)
            return _connection_lost_result(server_name, exc)
        except _TRANSIENT_ERRORS:
            logger.warning(
                "MCP tool %s/%s hit a transient transport error; retrying once",
                server_name,
                tool_name,
            )
            try:
                # Watched like the first attempt. A retry is if anything *more*
                # likely to meet a dead transport, which is exactly the failure
                # this reports as itself rather than as a timeout.
                return await self._call_watching_connection(
                    conn, tool_name, arguments, timeout, on_progress
                )
            except ConnectionLost as exc:
                return _connection_lost_result(server_name, exc)
            except Exception as exc:
                return f"(MCP tool call failed after retry: {type(exc).__name__})"
        except asyncio.TimeoutError:
            return f"(MCP tool call timed out after {timeout}s)"
        except asyncio.CancelledError:
            # The MCP SDK's anyio scopes can leak CancelledError on internal
            # failures; re-raise only when our own task was cancelled.
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            return "(MCP tool call was cancelled)"
        except Exception as exc:
            logger.exception("MCP tool %s/%s failed", server_name, tool_name)
            return f"(MCP tool call failed: {type(exc).__name__}: {exc})"

    async def _call_watching_connection(
        self,
        conn: _ServerConnection,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: int,
        on_progress: "ProgressCallback | None" = None,
    ) -> str:
        """Run one call, abandoning it as soon as the connection task dies.

        A transport-level failure on the POST that carries the call — an HTTP
        error, most often auth — is raised inside the SDK's *own* task group,
        not on the awaiting caller. The request future is simply never resolved,
        so the bare call sits until ``tool_timeout`` expires and then reports a
        timeout: the one explanation that rules out the actual cause. Watching
        the connection task lets the real error, which that task has already
        recorded, be the thing the model and the user are told, in the second it
        actually took rather than the full timeout.
        """
        call = asyncio.ensure_future(
            self._call_once(conn, tool_name, arguments, timeout, on_progress)
        )
        watcher = conn.task
        if watcher is None or watcher.done():
            return await call
        try:
            done, _pending = await asyncio.wait(
                {call, watcher}, return_when=asyncio.FIRST_COMPLETED
            )
        except BaseException:
            # Unlike ``gather``, ``wait`` leaves the futures it was waiting on
            # running when the waiter itself is cancelled — and ``call`` is a
            # free-standing task, so nothing else would ever stop it. A turn
            # cancelled from the UI would leave the tool running against the
            # server and its result discarded.
            await self._abandon(call, conn)
            raise
        if call in done:
            return call.result()
        # The connection died first.
        await self._abandon(call, conn)
        raise ConnectionLost(conn.error or "the connection task ended")

    @staticmethod
    async def _abandon(call: "asyncio.Task[str]", conn: _ServerConnection) -> None:
        """Cancel an in-flight call and absorb whatever it ends up raising.

        Absorbing is the point: nobody is waiting on this result any more, and
        an un-awaited task that raises makes the loop log "task exception was
        never retrieved" for a failure that is no longer anyone's problem.
        """
        call.cancel()
        try:
            await call
        except asyncio.CancelledError:
            # Ours, not the turn's — unless this task is itself being cancelled,
            # in which case swallowing it would strand that cancellation.
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
        except Exception:
            logger.debug("MCP call for %r discarded after it was abandoned", conn.name)

    @staticmethod
    async def _call_once(
        conn: _ServerConnection,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: int,
        on_progress: "ProgressCallback | None" = None,
    ) -> str:
        from mcp import types

        result = await asyncio.wait_for(
            conn.session.call_tool(
                tool_name,
                arguments=arguments,
                # Opt-in per call: the SDK only asks the server for progress when
                # a callback is supplied, so a call with no sub-trace to publish
                # into does not ask for notifications it would throw away.
                progress_callback=on_progress,
            ),
            timeout=timeout,
        )
        parts: list[str] = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            elif isinstance(block, types.ImageContent):
                parts.append("[MCP image omitted]")
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"

    # ── connection internals ───────────────────────────────────────────

    @classmethod
    def _signature(cls, cfg: MCPServerConfig, owner: str) -> str:
        """``cfg``'s connection fingerprint, sensitive to its resolved secrets.

        :meth:`MCPServerConfig.connection_signature` fingerprints the *stored*
        config, which holds ``${secret:...}`` references rather than values (see
        :mod:`deeptutor.services.mcp.secrets`). Rotating a credential therefore
        leaves that fingerprint byte-identical, and the reload diff concludes
        nothing changed — so the account keeps talking to the server with the
        key it just replaced until the process restarts.

        Mixing in a digest of the materialized config closes that hole. Only the
        digest is kept: a signature is held on a live connection and compared in
        logs-adjacent code, so the credential itself must not be in it. Configs
        with no references keep their plain signature, so upgrading this code
        does not invalidate — and drop — every live session.
        """
        base = cfg.connection_signature()
        if _SECRET_REFERENCE_MARKER not in base:
            # Nothing to resolve, so nothing can change behind the diff. Worth
            # checking first: this runs for every live connection on every
            # reload, which ``ensure_scope`` performs once per turn, and
            # resolving does per-reference disk work (mkdir + chmod + read, see
            # ``secrets._secrets_dir``) synchronously on that path.
            return base
        try:
            resolved = cls._materialize(cfg, owner).connection_signature()
        except Exception:  # pragma: no cover - unreadable secrets store
            logger.warning("Could not resolve secrets while fingerprinting a server config")
            return base
        if resolved == base:
            return base
        return f"{base}#{hashlib.sha256(resolved.encode('utf-8')).hexdigest()}"

    async def _sync_to_config(self, config: MCPConfig, *, owner: str = SHARED_OWNER) -> None:
        """Diff *owner*'s live connections against *config*; caller holds the lock."""
        desired = {name: cfg for name, cfg in config.servers.items() if cfg.enabled}
        # Drop removed/disabled/changed servers.
        for key in list(self._connections):
            if key[0] != owner:
                continue
            cfg = desired.get(key[1])
            if cfg is None or self._signature(cfg, owner) != self._connections[key].signature:
                await self._disconnect(self._connections.pop(key))
        # Connect new/changed servers concurrently.
        pending = [
            self._connect(name, cfg, owner=owner)
            for name, cfg in desired.items()
            if (owner, name) not in self._connections
        ]
        if pending:
            await asyncio.gather(*pending)

    async def _connect(
        self,
        name: str,
        cfg: MCPServerConfig,
        *,
        owner: str = SHARED_OWNER,
        retry_delay: float = _RETRY_BACKOFF_START_S,
    ) -> None:
        conn = _ServerConnection(
            name=name,
            config=cfg,
            signature=self._signature(cfg, owner),
            owner=owner,
            retry_delay=retry_delay,
        )
        self._connections[(owner, name)] = conn
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.task = asyncio.create_task(self._run_server(conn, ready), name=f"mcp-server-{name}")
        try:
            await asyncio.wait_for(ready, timeout=_CONNECT_TIMEOUT_S)
            conn.status = "connected"
            conn.error = ""
            conn.retry_delay = _RETRY_BACKOFF_START_S
            self._register_adapters(conn)
            logger.info("MCP server %r connected (%d tools)", name, len(conn.adapters))
        except asyncio.TimeoutError:
            self._mark_failed(conn, f"connect timed out after {_CONNECT_TIMEOUT_S}s")
            logger.error("MCP server %r: %s", name, conn.error)
        except Exception as exc:
            # Unwrapped, same as the probe: this string is what the store shows
            # under a server's row, and "unhandled errors in a TaskGroup" tells
            # the reader nothing about the 401 or the DNS failure behind it.
            self._mark_failed(conn, describe_connect_failure(exc))
            if _needs_authorization(exc):
                # Not broken — waiting on a person. Kept out of "error" so the UI
                # offers a Connect button instead of a retry, and so the backoff
                # does not spend the next five minutes re-discovering that nobody
                # has consented yet.
                conn.status = "needs_auth"
            logger.error("MCP server %r failed to connect: %s", name, conn.error)

    def _mark_failed(self, conn: _ServerConnection, error: str) -> None:
        """Record a connect failure and schedule the next attempt."""
        conn.status = "error"
        conn.error = error
        conn.shutdown.set()
        conn.retry_at = asyncio.get_running_loop().time() + conn.retry_delay
        conn.retry_delay = min(conn.retry_delay * 2, _RETRY_BACKOFF_MAX_S)

    async def _run_server(self, conn: _ServerConnection, ready: asyncio.Future) -> None:
        """Connection task: owns the AsyncExitStack for one server."""
        from contextlib import AsyncExitStack

        try:
            # Imported inside the guarded block on purpose (issue #792): if the
            # `mcp` package is missing, an import at function scope raises before
            # anything can fail *ready*, so the task dies with an unretrieved
            # ModuleNotFoundError while the connect waits out the full timeout.
            # Inside the block the real cause reaches the caller immediately.
            from mcp import ClientSession

            async with AsyncExitStack() as stack:
                read, write = await self._open_transport(
                    stack, conn.config, owner=conn.owner, server_name=conn.name
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listing = await session.list_tools()
                adapters = [
                    MCPToolAdapter(
                        manager=self,
                        owner=conn.owner,
                        server_name=conn.name,
                        original_name=tool_def.name,
                        description=tool_def.description or "",
                        input_schema=tool_def.inputSchema,
                        tool_timeout=conn.config.tool_timeout,
                    )
                    for tool_def in listing.tools
                    if conn.config.tool_allowed(
                        tool_def.name, wrapped_tool_name(conn.name, tool_def.name)
                    )
                ]
                conn.session = session
                conn.adapters = adapters
                if not ready.done():
                    ready.set_result(None)
                await conn.shutdown.wait()
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                # The session died after going live. Stop advertising its tools:
                # leaving them registered burns prompt tokens on a manifest whose
                # every call answers "not connected".
                logger.warning("MCP server %r connection task ended: %s", conn.name, exc)
                self._unregister_adapters(conn)
                conn.adapters = []
                # Unwrapped like the connect path: this string is now also what a
                # tool call reports when the connection dies under it, and
                # "ExceptionGroup: unhandled errors in a TaskGroup" names nothing.
                self._mark_failed(conn, describe_connect_failure(exc))
        finally:
            conn.session = None

    @staticmethod
    def _materialize(cfg: MCPServerConfig, owner: str) -> MCPServerConfig:
        """Resolve ``${secret:...}`` references into a connect-time-only config.

        The returned object carries real credential values and must never be
        persisted, logged, or returned by an API — it exists for the duration of
        one transport open. See :mod:`deeptutor.services.mcp.secrets` for why the
        stored config holds references instead.
        """
        from deeptutor.services.mcp.secrets import resolve_references, resolve_url_references

        resolved = resolve_references(owner, cfg.model_dump(mode="json"))
        # Several hosted services authenticate with a query parameter, so the
        # url needs component-wise resolution: the whole string is not a
        # reference, only one of its query values is.
        url = resolved.get("url")
        if isinstance(url, str) and url:
            resolved["url"] = resolve_url_references(owner, url)
        return MCPServerConfig.model_validate(resolved)

    @staticmethod
    async def _open_transport(
        stack: Any,
        cfg: MCPServerConfig,
        *,
        owner: str = SHARED_OWNER,
        server_name: str = "",
    ) -> tuple[Any, Any]:
        """Enter the configured transport on *stack*; return (read, write)."""
        from mcp import StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client

        # A server the deployment owns is administrator-configured; one owned by
        # an account is user input, and this request is made by the app process,
        # which holds every provider key. So user-owned servers get the strict
        # address policy and may not be redirected — an approved public URL that
        # 302s to 169.254.169.254 or to an internal service would otherwise walk
        # straight past a save-time-only check.
        self_service = owner != SHARED_OWNER
        cfg = MCPConnectionManager._materialize(cfg, owner)

        transport = cfg.resolved_type()
        if transport == "stdio":
            if self_service:
                raise ValueError("stdio MCP servers are administrator-only")
            params = StdioServerParameters(
                command=cfg.command,
                args=list(cfg.args),
                env=dict(cfg.env) or None,
                cwd=cfg.cwd or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
            return read, write

        if self_service:
            # Re-validated here, not only where the server was saved: DNS can
            # change between the two, and this is the last point before a socket.
            from deeptutor.services.mcp.network import validate_mcp_url_async

            ok, error = await validate_mcp_url_async(cfg.url, strict=True)
            if not ok:
                raise ValueError(error)
        follow_redirects = not self_service

        # OAuth, when the server declares it. Non-interactive here on purpose:
        # this runs from a connection task with nobody in front of it, so it uses
        # and refreshes stored tokens and raises AuthorizationRequired rather than
        # blocking on a consent screen. The interactive form is built by the route
        # a person clicked (`space_mcp.authorize`).
        oauth_auth = None
        if cfg.auth == "oauth":
            from deeptutor.services.mcp.oauth import build_auth, oauth_redirect_uri

            oauth_auth = build_auth(
                server_url=cfg.url,
                server_name=server_name,
                owner_id=owner,
                redirect_uri=oauth_redirect_uri(),
            )

        if transport == "sse":

            def httpx_client_factory(
                headers: dict[str, str] | None = None,
                timeout: httpx.Timeout | None = None,
                auth: httpx.Auth | None = None,
            ) -> httpx.AsyncClient:
                merged = {**(cfg.headers or {}), **(headers or {})}
                return httpx.AsyncClient(
                    headers=merged or None,
                    follow_redirects=follow_redirects,
                    timeout=timeout,
                    # The transport supplies its own auth for some flows; ours
                    # wins when the server is OAuth-backed.
                    auth=oauth_auth or auth,
                )

            read, write = await stack.enter_async_context(
                sse_client(cfg.url, httpx_client_factory=httpx_client_factory)
            )
            return read, write
        if transport == "streamableHttp":
            # Explicit client so the transport doesn't inherit httpx's 5s
            # default timeout and preempt the per-tool timeout.
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=cfg.headers or None,
                    follow_redirects=follow_redirects,
                    timeout=httpx.Timeout(60.0, connect=10.0),
                    auth=oauth_auth,
                )
            )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(cfg.url, http_client=http_client)
            )
            return read, write
        raise ValueError(f"MCP server has no usable transport (type={cfg.type!r})")

    async def _disconnect(self, conn: _ServerConnection) -> None:
        self._unregister_adapters(conn)
        conn.shutdown.set()
        if conn.task is not None:
            try:
                await asyncio.wait_for(conn.task, timeout=10)
            except (asyncio.TimeoutError, Exception):
                conn.task.cancel()
        conn.status = "disabled"
        conn.adapters = []

    # ── registry sync ──────────────────────────────────────────────────

    @staticmethod
    def _registry():
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        return get_tool_registry()

    def _register_adapters(self, conn: _ServerConnection) -> None:
        """Publish a *deployment* server's tools to the process registry.

        Owner-scoped tools deliberately stay out of it: the registry is a
        last-writer-wins dict keyed by tool name, so two tenants whose servers
        share a name would clobber each other — and unregistering one would
        evict the survivor. Those reach a turn through the scoped registry's
        overlay instead (see ``runtime.registry.scoped_registry``).
        """
        if conn.owner != SHARED_OWNER:
            return
        registry = self._registry()
        for adapter in conn.adapters:
            registry.register(adapter)

    def _unregister_adapters(self, conn: _ServerConnection) -> None:
        # Symmetric with _register_adapters: an owner-scoped connection never
        # registered, so unregistering by name here could evict a *shared*
        # tool that happens to have the same name.
        if conn.owner != SHARED_OWNER:
            return
        registry = self._registry()
        for adapter in conn.adapters:
            registry.unregister(adapter.name)


async def probe_server(
    cfg: MCPServerConfig,
    *,
    timeout: int = _CONNECT_TIMEOUT_S,
    owner: str = SHARED_OWNER,
) -> dict[str, Any]:
    """One-off connect + list_tools for a Test button.

    Opens and closes its own connection; never touches the live manager. Pass
    the *owner* so the probe runs under the same address policy, redirect rule,
    and stored credentials the real connection would use — a Test that is more
    permissive than the connection it previews is worse than no Test.
    """
    from contextlib import AsyncExitStack

    from mcp import ClientSession

    async def _probe() -> list[dict[str, str]]:
        # Collected inside the stack, returned outside it: returning from within
        # an ``AsyncExitStack`` block leaves mypy unable to see that the function
        # always returns (``__aexit__`` may swallow), and this module is now
        # covered by the type gate.
        tools: list[dict[str, str]] = []
        async with AsyncExitStack() as stack:
            read, write = await MCPConnectionManager._open_transport(stack, cfg, owner=owner)
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listing = await session.list_tools()
            tools = [{"name": t.name, "description": t.description or ""} for t in listing.tools]
        return tools

    try:
        tools = await asyncio.wait_for(_probe(), timeout=timeout)
        return {"ok": True, "tools": tools, "error": ""}
    except asyncio.TimeoutError:
        return {"ok": False, "tools": [], "error": f"connect timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "tools": [], "error": describe_connect_failure(exc)}


def describe_connect_failure(exc: BaseException) -> str:
    """A one-line reason a connection failed, with the real cause in it.

    The MCP SDK runs its transport in an anyio task group, so almost every
    failure arrives wrapped: the plain ``f"{type(exc).__name__}: {exc}"`` renders
    as *"ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)"*,
    which is what a person typing a URL into the store used to be told. The
    interesting exception is always a leaf, so this unwraps to the leaves and
    reports those instead.

    Nested groups are flattened and duplicates collapsed — a retrying transport
    can contribute the same error several times, and "401 Unauthorized" said
    three times is not more informative than once.
    """
    leaves = _exception_leaves(exc)
    if not leaves:
        return _redact_urls(f"{type(exc).__name__}: {exc}")
    seen: list[str] = []
    for leaf in leaves:
        text = _redact_urls(f"{type(leaf).__name__}: {leaf}".strip().rstrip(":").strip())
        if text not in seen:
            seen.append(text)
    return "; ".join(seen[:3])


# httpx names the full request URL in its error messages ("Client error '403
# Forbidden' for url '<url>'"). A catalog server may carry its credential in a
# query parameter or in userinfo (``CredentialTarget`` includes "url_param";
# several curated servers use it), and this string is shown in settings *and*,
# since a dead transport is now reported as itself, returned to the model as a
# tool result. Strip both before it travels.
_URL_IN_TEXT_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>]+", re.IGNORECASE)


def _redact_urls(text: str) -> str:
    def _redact(match: re.Match[str]) -> str:
        url = match.group(0)
        trailing = ""
        # Punctuation the message put after the URL, not part of it.
        while url and url[-1] in ").,;:":
            url, trailing = url[:-1], url[-1] + trailing
        try:
            parts = urlsplit(url)
        except ValueError:
            return match.group(0)
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        if parts.username:
            netloc = f"***@{netloc}"
        query = "***" if parts.query else ""
        return urlunsplit((parts.scheme, netloc, parts.path, query, "")) + trailing

    return _URL_IN_TEXT_RE.sub(_redact, text)


def _needs_authorization(exc: BaseException) -> bool:
    """Whether this failure means "a person has to authorize", not "it is broken".

    Checked against the unwrapped leaves for the same reason the message is: the
    SDK's task group hides the interesting exception one level down.
    """
    from deeptutor.services.mcp.oauth import AuthorizationRequired

    return any(isinstance(leaf, AuthorizationRequired) for leaf in _exception_leaves(exc)) or (
        isinstance(exc, AuthorizationRequired)
    )


def _exception_leaves(exc: BaseException, depth: int = 0) -> list[BaseException]:
    """Flatten an ``ExceptionGroup`` to the exceptions that actually happened."""
    # Depth-bounded: a malformed group cannot be allowed to recurse forever while
    # someone waits on a Test button.
    if depth > 5 or not isinstance(exc, BaseExceptionGroup):
        return [] if isinstance(exc, BaseExceptionGroup) else [exc]
    out: list[BaseException] = []
    for sub in exc.exceptions:
        out.extend(_exception_leaves(sub, depth + 1))
    return out


_manager: MCPConnectionManager | None = None


def get_mcp_manager() -> MCPConnectionManager:
    global _manager
    if _manager is None:
        _manager = MCPConnectionManager()
    return _manager


__all__ = [
    "SHARED_OWNER",
    "MCPConnectionManager",
    "MCPToolAdapter",
    "get_mcp_manager",
    "probe_server",
    "wrapped_tool_name",
]
