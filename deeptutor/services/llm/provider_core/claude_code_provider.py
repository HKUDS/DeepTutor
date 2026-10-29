"""Claude Agent SDK provider.

Runs turns through the locally installed Claude Code CLI via
``claude-agent-sdk``, so requests authenticate with whatever account the
operator signed into with ``claude /login`` (including a Pro/Max or team
subscription) instead of an Anthropic API key.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
import json
import logging
import re
import tempfile
from types import ModuleType
from typing import Any

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse
from deeptutor.services.llm.provider_core.sdk_bridge import (
    _MCP_SERVER_NAME,
    _MCP_TOOL_PREFIX,
    _consume_messages,
    _content_part_text,
    _content_text,
    _messages_to_prompt,
    _reasoning_options,
)

DEFAULT_CLAUDE_CODE_MODEL = "claude-code/default"
CLAUDE_CODE_MODELS = ("default", "sonnet", "opus", "haiku")
_SESSION_POOL_MAXSIZE = 4
_LABEL = "Claude Code"

logger = logging.getLogger(__name__)


# A prompt is plain text, or Anthropic content blocks when it carries images.
_Prompt = str | list[dict[str, Any]]


@dataclass
class _SessionTurn:
    prompt: _Prompt
    on_content_delta: Callable[[str], Awaitable[None]] | None
    future: asyncio.Future[LLMResponse]


@dataclass
class _ClaudeCodeSession:
    """One long-lived Claude Code CLI process per DeepTutor session.

    ``ClaudeSDKClient`` enters anyio task groups in ``connect()`` and must
    leave them from the same task, so a dedicated owner task runs connect /
    query / receive / disconnect while callers hand it turns over a queue.
    ``messages`` and ``last_response`` hold the non-system history already sent,
    which lets ``_incremental_prompt`` send only the new tail each turn.
    """

    signature: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_response: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _ops: asyncio.Queue[_SessionTurn | None] = field(default_factory=asyncio.Queue)
    _owner: asyncio.Task[None] | None = None

    @classmethod
    async def start(cls, *, sdk: ModuleType, signature: str, options: Any) -> "_ClaudeCodeSession":
        session = cls(signature=signature)
        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        session._owner = asyncio.create_task(
            session._owner_loop(sdk, options, ready),
            name="claude-code-session-owner",
        )
        try:
            async with asyncio.timeout(15):
                await ready
        except BaseException:
            await session.close()
            raise
        return session

    @property
    def alive(self) -> bool:
        return self._owner is not None and not self._owner.done()

    async def _owner_loop(self, sdk: ModuleType, options: Any, ready: asyncio.Future[None]) -> None:
        client = sdk.ClaudeSDKClient(options=options)
        try:
            await client.connect()
            if not ready.done():
                ready.set_result(None)
            while True:
                turn = await self._ops.get()
                if turn is None:
                    break
                try:
                    await client.query(_sdk_prompt(turn.prompt))
                    # No real interrupt on a tool call: ``max_turns=1`` already
                    # ends the turn right after the placeholder tool result, and
                    # an interrupt would leave "[Request interrupted]" in the
                    # transcript. The no-op still makes the helper drain the
                    # turn's result so it cannot leak into the next one.
                    response = await _consume_messages(
                        client.receive_response(),
                        on_content_delta=turn.on_content_delta,
                        interrupt=_no_interrupt,
                        label=_LABEL,
                    )
                    if not turn.future.done():
                        turn.future.set_result(response)
                except BaseException as exc:
                    if not turn.future.done():
                        turn.future.set_exception(exc)
                    raise
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise
        finally:
            while not self._ops.empty():
                pending = self._ops.get_nowait()
                if pending is not None and not pending.future.done():
                    pending.future.cancel()
            with suppress(Exception):
                async with asyncio.timeout(5):
                    await client.disconnect()

    async def run_turn(
        self,
        prompt: _Prompt,
        on_content_delta: Callable[[str], Awaitable[None]] | None,
    ) -> LLMResponse:
        if not self.alive:
            raise RuntimeError("Claude Code session owner is not running")
        future: asyncio.Future[LLMResponse] = asyncio.get_running_loop().create_future()
        await self._ops.put(
            _SessionTurn(prompt=prompt, on_content_delta=on_content_delta, future=future)
        )
        return await future

    async def close(self) -> None:
        owner = self._owner
        if owner is None:
            return
        self._owner = None
        if not owner.done():
            owner.cancel()
        # Cancellation reaches receive_response immediately; disconnect still
        # runs in the task that entered the SDK's anyio scopes.
        with suppress(asyncio.CancelledError, Exception):
            await owner


async def _no_interrupt() -> None:
    return None


class ClaudeCodeProvider(LLMProvider):
    """Provider backed by the Claude Agent SDK (local Claude Code login).

    Claude Code's own tools are disabled and the operator's Claude Code
    settings, CLAUDE.md files and hooks are not loaded; DeepTutor's tool
    schemas are exposed through an in-process SDK MCP server instead. When
    Claude calls one, the turn is interrupted and the call is returned as a
    regular ``tool_calls`` response so DeepTutor's dispatcher executes it.
    """

    def __init__(self, default_model: str | None = DEFAULT_CLAUDE_CODE_MODEL):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model or DEFAULT_CLAUDE_CODE_MODEL
        self._sessions: OrderedDict[str, _ClaudeCodeSession] = OrderedDict()
        self._sessions_lock = asyncio.Lock()
        self._workspace = tempfile.TemporaryDirectory(prefix="dt-claude-provider-")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        session_id = str(kwargs.pop("deeptutor_session_id", "") or "").strip()
        return await self._run(messages, tools, model, reasoning_effort, None, session_id)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        session_id = str(kwargs.pop("deeptutor_session_id", "") or "").strip()
        return await self._run(
            messages, tools, model, reasoning_effort, on_content_delta, session_id
        )

    async def _run(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        reasoning_effort: str | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None,
        session_id: str,
    ) -> LLMResponse:
        try:
            sdk = _load_sdk()
            system_prompt, conversation = _split_system(messages)
            model = model or self.default_model
            if session_id:
                return await self._run_session(
                    sdk,
                    session_id,
                    system_prompt,
                    conversation,
                    tools,
                    model,
                    reasoning_effort,
                    on_content_delta,
                )
            options = _build_options(
                sdk, model, system_prompt, reasoning_effort, tools, cwd=self._workspace.name
            )
            stream = sdk.query(prompt=_sdk_prompt(_prompt_input(conversation)), options=options)
            try:
                return await _consume_messages(
                    stream, on_content_delta=on_content_delta, label=_LABEL
                )
            finally:
                close = getattr(stream, "aclose", None)
                if callable(close):
                    await close()
        except Exception as exc:
            return LLMResponse(content=_friendly_error(exc), finish_reason="error")

    async def _run_session(
        self,
        sdk: ModuleType,
        session_id: str,
        system_prompt: str,
        conversation: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        reasoning_effort: str | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None,
    ) -> LLMResponse:
        signature = _session_signature(model, system_prompt, reasoning_effort, tools)
        session = await self._get_session(
            sdk, session_id, signature, model, system_prompt, reasoning_effort, tools
        )
        try:
            async with session.lock:
                if session.messages and (
                    len(conversation) <= len(session.messages)
                    or conversation[: len(session.messages)] != session.messages
                ):
                    # Edited/regenerated history must never append to the old
                    # CLI transcript. Retire it before replaying the new branch.
                    await self._drop_session(session_id, session)
                    return await self._run_session(
                        sdk,
                        session_id,
                        system_prompt,
                        conversation,
                        tools,
                        model,
                        reasoning_effort,
                        on_content_delta,
                    )
                prompt = _prompt_input(_incremental_messages(session, conversation))
                session.messages = deepcopy(conversation)
                response = await session.run_turn(prompt, on_content_delta)
                session.last_response = response.content or ""
                return response
        except BaseException:
            await self._drop_session(session_id, session)
            raise

    async def _get_session(
        self,
        sdk: ModuleType,
        session_id: str,
        signature: str,
        model: str,
        system_prompt: str,
        reasoning_effort: str | None,
        tools: list[dict[str, Any]] | None,
    ) -> _ClaudeCodeSession:
        to_close: list[_ClaudeCodeSession] = []
        try:
            async with self._sessions_lock:
                existing = self._sessions.get(session_id)
                if existing and existing.signature == signature and existing.alive:
                    self._sessions.move_to_end(session_id)
                    return existing
                if existing:
                    self._sessions.pop(session_id, None)
                    to_close.append(existing)

                options = _build_options(
                    sdk, model, system_prompt, reasoning_effort, tools, cwd=self._workspace.name
                )
                session = await _ClaudeCodeSession.start(
                    sdk=sdk, signature=signature, options=options
                )
                self._sessions[session_id] = session
                while len(self._sessions) > _SESSION_POOL_MAXSIZE:
                    idle_key = next(
                        (
                            key
                            for key, item in self._sessions.items()
                            if key != session_id and not item.lock.locked()
                        ),
                        None,
                    )
                    if idle_key is None:
                        break
                    to_close.append(self._sessions.pop(idle_key))
                return session
        finally:
            for stale in to_close:
                await stale.close()

    async def _drop_session(self, session_id: str, session: _ClaudeCodeSession) -> None:
        async with self._sessions_lock:
            if self._sessions.get(session_id) is session:
                self._sessions.pop(session_id, None)
        await session.close()

    async def aclose(self) -> None:
        async with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.close()
        self._workspace.cleanup()

    def get_default_model(self) -> str:
        return self.default_model


def _load_sdk() -> ModuleType:
    try:
        import claude_agent_sdk
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "claude-agent-sdk is not installed. Install it with "
            "`python scripts/install_extras.py claude-code` in a source checkout, "
            'or `python -m pip install "deeptutor[claude-code]"` for a wheel installation.'
        ) from exc
    return claude_agent_sdk


def _strip_model_prefix(model: str | None) -> str | None:
    if not model:
        return None
    if "/" in model:
        prefix, value = model.split("/", 1)
        if prefix.lower().replace("-", "_") == "claude_code":
            model = value
    return None if model == "default" else model


def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Lift system messages into Claude's real system prompt."""
    system_parts: list[str] = []
    conversation: list[dict[str, Any]] = []
    for message in messages:
        if str(message.get("role") or "") == "system":
            text = _content_text(message.get("content"))
            if text:
                system_parts.append(text)
        else:
            conversation.append(message)
    return "\n\n".join(system_parts), conversation


def _incremental_messages(
    session: _ClaudeCodeSession,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The tail of *messages* the session's CLI has not seen yet.

    Mirrors ``codebuddy_provider._incremental_prompt`` but keeps the messages
    themselves, so image parts survive into ``_prompt_input``.
    """
    previous = session.messages
    if previous and len(messages) >= len(previous) and messages[: len(previous)] == previous:
        delta = list(messages[len(previous) :])
        if delta and session.last_response and delta[0].get("role") == "assistant":
            if _content_text(delta[0].get("content")) == session.last_response:
                delta.pop(0)
        if _messages_to_prompt(delta) or any(_image_parts(m) for m in delta):
            return delta
    return messages


def _image_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [p for p in content if isinstance(p, dict) and p.get("type") == "image_url"]


def _prompt_input(messages: list[dict[str, Any]]) -> _Prompt:
    """Flatten *messages* for the CLI, keeping images as Anthropic image blocks.

    Text-only turns stay a plain string. A turn carrying images (for example a
    retrieved source figure) becomes content blocks in the original order, with
    the same role headings ``_messages_to_prompt`` writes.
    """
    if not any(_image_parts(m) for m in messages):
        return _messages_to_prompt(messages)

    blocks: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user").strip() or "user"
        if role == "assistant":
            heading = "Assistant"
        elif role == "tool":
            heading = (
                f"Tool result ({message.get('name') or message.get('tool_call_id') or 'tool'})"
            )
        else:
            heading = "User"
        content = message.get("content")
        parts = content if isinstance(content, list) else [content]
        texts: list[str] = []
        message_blocks: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "image_url":
                if texts:
                    message_blocks.append({"type": "text", "text": "\n".join(texts)})
                    texts = []
                image = _image_block(part)
                if image:
                    message_blocks.append(image)
                continue
            text = _content_part_text(part) if part is not None else ""
            if text:
                texts.append(text)
        if texts:
            message_blocks.append({"type": "text", "text": "\n".join(texts)})
        if not message_blocks:
            continue
        if message_blocks[0]["type"] == "text":
            message_blocks[0]["text"] = f"{heading}:\n{message_blocks[0]['text']}"
        else:
            message_blocks.insert(0, {"type": "text", "text": f"{heading}:"})
        blocks.extend(message_blocks)
    return blocks


def _image_block(part: dict[str, Any]) -> dict[str, Any] | None:
    url = str((part.get("image_url") or {}).get("url") or "")
    if not url:
        return None
    match = re.match(r"data:(image/[\w.+-]+);base64,(.+)", url, re.DOTALL)
    if match:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": match.group(1), "data": match.group(2)},
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _sdk_prompt(prompt: _Prompt) -> str | AsyncIterator[dict[str, Any]]:
    """Plain text goes as-is; content blocks go as one streamed user message."""
    if isinstance(prompt, str):
        return prompt

    async def stream() -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
        }

    return stream()


def _build_options(
    sdk: ModuleType,
    model: str | None,
    system_prompt: str,
    reasoning_effort: str | None,
    tools: list[dict[str, Any]] | None,
    *,
    cwd: str,
) -> Any:
    stripped_model = _strip_model_prefix(model)
    return sdk.ClaudeAgentOptions(
        **({"model": stripped_model} if stripped_model else {}),
        system_prompt=system_prompt,
        # No built-in Claude Code tools and none of the operator's settings,
        # CLAUDE.md files, hooks or plugins: this is a plain model endpoint.
        cwd=cwd,
        permission_mode="dontAsk",
        extra_args={"strict-mcp-config": None},
        tools=[],
        setting_sources=[],
        max_turns=1,
        **_reasoning_options(reasoning_effort),
        **_build_tool_options(sdk, tools),
    )


def _build_tool_options(sdk: ModuleType, tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    sdk_tools: list[Any] = []
    allowed: list[str] = []
    for schema in tools or []:
        function = schema.get("function") if isinstance(schema, dict) else None
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        description = str(function.get("description") or name)
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}

        async def pending_result(_args: dict[str, Any]) -> dict[str, Any]:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Pending: DeepTutor runs this tool and sends its output in the next message.",
                    }
                ]
            }

        sdk_tools.append(sdk.tool(name, description, parameters)(pending_result))
        allowed.append(f"{_MCP_TOOL_PREFIX}{name}")

    if not sdk_tools:
        return {}
    return {
        "allowed_tools": allowed,
        "mcp_servers": {
            _MCP_SERVER_NAME: sdk.create_sdk_mcp_server(_MCP_SERVER_NAME, tools=sdk_tools)
        },
    }


def _session_signature(
    model: str,
    system_prompt: str,
    reasoning_effort: str | None,
    tools: list[dict[str, Any]] | None,
) -> str:
    payload = {
        "model": _strip_model_prefix(model),
        "system": system_prompt,
        "reasoning_effort": reasoning_effort or "",
        "tools": tools or [],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered and "claude" in lowered and "cli" in lowered:
        return (
            "Error calling Claude Code: the Claude Code CLI was not found. "
            "Reinstall claude-agent-sdk or install Claude Code."
        )
    if "login" in lowered or "authenticat" in lowered or "401" in message:
        return (
            "Error calling Claude Code: not signed in. Run `claude` and enter `/login`, then retry."
        )
    return f"Error calling Claude Code: {message}"


async def fetch_claude_code_catalog() -> list[dict[str, str]]:
    """Models the signed-in Claude Code account offers, with display names.

    Read from the CLI's ``initialize`` handshake, so no model request is made.
    The ``default`` entry is labelled generically: the CLI describes its own
    default, but managed or user settings may pin a different model at run time.
    Falls back to the bare aliases when the CLI cannot be started.
    """
    from deeptutor.services.llm.claude_sdk import discover_models

    try:
        models = await discover_models()
    except Exception as exc:
        logger.warning("Claude Code model catalog unavailable (%s)", type(exc).__name__)
        models = []
    if not models:
        models = [
            {"slug": name, "display_name": name} for name in CLAUDE_CODE_MODELS if name != "default"
        ]
    return [
        {"id": "claude-code/default", "name": "Default (account setting)"},
        *[{"id": f"claude-code/{row['slug']}", "name": row["display_name"]} for row in models],
    ]


async def fetch_claude_code_models() -> list[str]:
    """Model ids the signed-in Claude Code account offers."""
    return [model["id"] for model in await fetch_claude_code_catalog()]


__all__ = [
    "CLAUDE_CODE_MODELS",
    "ClaudeCodeProvider",
    "DEFAULT_CLAUDE_CODE_MODEL",
    "fetch_claude_code_catalog",
    "fetch_claude_code_models",
]
