"""CodeBuddy Agent SDK provider."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
import re
import shutil
import subprocess
from types import ModuleType
from typing import Any

from deeptutor.services.llm.provider_core.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)

DEFAULT_CODEBUDDY_MODEL = "codebuddy/hy3"
_CODEBUDDY_API_KEY_ENV = "CODEBUDDY_API_KEY"
_API_KEY_ENV_LOCK = asyncio.Lock()
_SESSION_POOL_MAXSIZE = 4
_MCP_SERVER_NAME = "deeptutor"
_MCP_TOOL_PREFIX = f"mcp__{_MCP_SERVER_NAME}__"


@dataclass
class _SessionTurn:
    prompt: str
    on_content_delta: Callable[[str], Awaitable[None]] | None
    future: asyncio.Future[LLMResponse]


@dataclass
class _CodeBuddySession:
    """Stateful CodeBuddy CLI session with task-bound SDK ownership.

    The CodeBuddy Agent SDK enters anyio cancel scopes / TaskGroups during
    ``connect()`` and must exit them from the same task. DeepTutor chat turns
    run in fresh ``_ProviderOpenAIStream`` tasks, so this session keeps a
    dedicated owner task for connect / query / receive / disconnect.
    """

    signature: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_response: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    client: Any = None
    _ops: asyncio.Queue[_SessionTurn | None] = field(default_factory=asyncio.Queue)
    _owner: asyncio.Task[None] | None = None

    @classmethod
    async def start(
        cls,
        *,
        sdk: ModuleType,
        signature: str,
        options: Any,
        env_api_key: str | None,
    ) -> "_CodeBuddySession":
        session = cls(signature=signature)
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[None] = loop.create_future()
        session._owner = asyncio.create_task(
            session._owner_loop(sdk, options, env_api_key, ready),
            name="codebuddy-session-owner",
        )
        await ready
        return session

    async def _owner_loop(
        self,
        sdk: ModuleType,
        options: Any,
        env_api_key: str | None,
        ready: asyncio.Future[None],
    ) -> None:
        client = sdk.CodeBuddySDKClient(options=options)
        try:
            async with _temporary_codebuddy_api_key(env_api_key):
                await client.connect()
            self.client = client
            if not ready.done():
                ready.set_result(None)
            while True:
                turn = await self._ops.get()
                if turn is None:
                    break
                try:
                    await client.query(turn.prompt)
                    response = await _consume_messages(
                        client.receive_response(),
                        on_content_delta=turn.on_content_delta,
                        interrupt=client.interrupt,
                    )
                    if not turn.future.done():
                        turn.future.set_result(response)
                except BaseException as exc:
                    if not turn.future.done():
                        turn.future.set_exception(exc)
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise
        finally:
            self.client = client
            try:
                await client.disconnect()
            except BaseException:
                pass

    async def run_turn(
        self,
        prompt: str,
        on_content_delta: Callable[[str], Awaitable[None]] | None,
    ) -> LLMResponse:
        if self._owner is None or self._owner.done():
            raise RuntimeError("CodeBuddy session owner is not running")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[LLMResponse] = loop.create_future()
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
            try:
                await self._ops.put(None)
            except Exception:
                owner.cancel()
        try:
            await owner
        except Exception:
            pass


class CodeBuddyProvider(LLMProvider):
    """Provider backed by the CodeBuddy Agent SDK.

    CodeBuddy is exposed as an agent SDK instead of an OpenAI-compatible chat
    endpoint. This adapter keeps one stateful CLI process per DeepTutor session
    and exposes DeepTutor's tool schemas through an in-process SDK MCP server.
    Tool execution remains owned by DeepTutor's existing dispatcher.
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = DEFAULT_CODEBUDDY_MODEL,
    ):
        normalized_api_key = None if api_key in {None, "", "sk-no-key-required"} else api_key
        super().__init__(api_key=normalized_api_key, api_base=None)
        self.default_model = default_model or DEFAULT_CODEBUDDY_MODEL
        self._sessions: OrderedDict[str, _CodeBuddySession] = OrderedDict()
        self._sessions_lock = asyncio.Lock()

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
        del temperature, tool_choice, kwargs
        return await self._run_codebuddy(
            messages,
            tools,
            model,
            max_tokens,
            reasoning_effort=reasoning_effort,
            session_id=session_id,
        )

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
        del temperature, tool_choice, on_reasoning_delta, kwargs
        return await self._run_codebuddy(
            messages,
            tools,
            model,
            max_tokens,
            reasoning_effort=reasoning_effort,
            on_content_delta=on_content_delta,
            session_id=session_id,
        )

    async def _run_codebuddy(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        reasoning_effort: str | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        session_id: str = "",
    ) -> LLMResponse:
        try:
            sdk = _load_sdk()
            if session_id and hasattr(sdk, "CodeBuddySDKClient"):
                return await self._run_session(
                    sdk,
                    session_id,
                    messages,
                    tools,
                    model or self.default_model,
                    max_tokens,
                    reasoning_effort,
                    on_content_delta,
                )
            return await self._run_one_shot(
                sdk,
                messages,
                tools,
                model or self.default_model,
                max_tokens,
                reasoning_effort,
                on_content_delta,
            )
        except Exception as exc:
            return LLMResponse(content=_friendly_error(exc), finish_reason="error")

    async def _run_one_shot(
        self,
        sdk: ModuleType,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        reasoning_effort: str | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None,
    ) -> LLMResponse:
        options = _build_options(sdk, model, max_tokens, self.api_key, reasoning_effort, tools)
        env_api_key = None if _options_has_api_key_env(options) else self.api_key
        stream: Any | None = None
        async with _temporary_codebuddy_api_key(env_api_key):
            kwargs: dict[str, Any] = {"prompt": _messages_to_prompt(messages)}
            if options is not None:
                kwargs["options"] = options
            stream = sdk.query(**kwargs)
            try:
                return await _consume_messages(stream, on_content_delta=on_content_delta)
            finally:
                close = getattr(stream, "aclose", None)
                if callable(close):
                    await close()

    async def _run_session(
        self,
        sdk: ModuleType,
        session_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        reasoning_effort: str | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None,
    ) -> LLMResponse:
        signature = _session_signature(model, reasoning_effort, tools)
        session = await self._get_session(
            sdk, session_id, signature, model, max_tokens, reasoning_effort, tools
        )
        try:
            async with session.lock:
                prompt = _incremental_prompt(session, messages)
                session.messages = deepcopy(messages)
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
        max_tokens: int,
        reasoning_effort: str | None,
        tools: list[dict[str, Any]] | None,
    ) -> _CodeBuddySession:
        to_close: list[_CodeBuddySession] = []
        try:
            async with self._sessions_lock:
                existing = self._sessions.get(session_id)
                if (
                    existing
                    and existing.signature == signature
                    and existing._owner is not None
                    and not existing._owner.done()
                ):
                    self._sessions.move_to_end(session_id)
                    return existing
                if existing:
                    self._sessions.pop(session_id, None)
                    to_close.append(existing)

                options = _build_options(
                    sdk, model, max_tokens, self.api_key, reasoning_effort, tools
                )
                env_api_key = None if _options_has_api_key_env(options) else self.api_key
                session = await _CodeBuddySession.start(
                    sdk=sdk,
                    signature=signature,
                    options=options,
                    env_api_key=env_api_key,
                )
                self._sessions[session_id] = session
                while len(self._sessions) > _SESSION_POOL_MAXSIZE:
                    _, evicted = self._sessions.popitem(last=False)
                    to_close.append(evicted)
                return session
        finally:
            for stale in to_close:
                await stale.close()

    async def _drop_session(self, session_id: str, session: _CodeBuddySession) -> None:
        async with self._sessions_lock:
            if self._sessions.get(session_id) is session:
                self._sessions.pop(session_id, None)
        await session.close()

    async def aclose(self) -> None:
        async with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                await session.close()
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None:
                    task.uncancel()
            except Exception:
                pass

    def get_default_model(self) -> str:
        return self.default_model


def _load_sdk() -> ModuleType:
    try:
        import codebuddy_agent_sdk
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "codebuddy-agent-sdk is not installed. Install it with "
            "`python -m pip install codebuddy-agent-sdk` or `pip install -e .[codebuddy]`."
        ) from exc
    if not hasattr(codebuddy_agent_sdk, "query"):
        raise RuntimeError("Installed codebuddy-agent-sdk does not expose query().")
    return codebuddy_agent_sdk


def _strip_model_prefix(model: str | None) -> str | None:
    if not model:
        return None
    if "/" not in model:
        return model
    prefix, value = model.split("/", 1)
    if prefix.lower().replace("-", "_") in {"codebuddy", "codebuddy_code", "workbuddy"}:
        return value
    return model


def _build_options(
    sdk: ModuleType,
    model: str | None,
    max_tokens: int,
    api_key: str | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> Any | None:
    options_cls = getattr(sdk, "CodeBuddyAgentOptions", None)
    if options_cls is None:
        return None

    stripped_model = _strip_model_prefix(model)
    model_kwargs = (
        {} if not stripped_model or stripped_model == "default" else {"model": stripped_model}
    )
    env_kwargs = {"env": {_CODEBUDDY_API_KEY_ENV: api_key}} if api_key else {}
    reasoning_kwargs = _reasoning_options(reasoning_effort)
    tool_kwargs = _build_tool_options(sdk, tools)
    # The turn limit and the permission mode ARE the sandbox — they keep the
    # agent from acting on its own beyond the single turn we asked for. The SDK
    # spells them snake_case or camelCase depending on version, so both are
    # tried; but a build that accepts neither is a build whose restrictions we
    # cannot express, and running unrestricted is not the safe fallback. Every
    # candidate therefore carries them, and exhausting the list raises.
    candidates: list[dict[str, Any]] = []
    for guard in (
        {"max_turns": 1, "permission_mode": "plan"},
        {"maxTurns": 1, "permissionMode": "plan"},
    ):
        restricted = {
            **model_kwargs,
            **env_kwargs,
            **reasoning_kwargs,
            **tool_kwargs,
            **guard,
        }
        if max_tokens > 0:
            candidates.append({**restricted, "max_tokens": max_tokens})
        candidates.append(restricted)

    for kwargs in candidates:
        try:
            return options_cls(**kwargs)
        except TypeError:
            continue
    raise RuntimeError(
        "The installed codebuddy-agent-sdk does not accept the turn limit and "
        "permission mode this provider requires. Install a supported version "
        '(pip install "deeptutor[codebuddy]").'
    )


def _build_tool_options(sdk: ModuleType, tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not tools:
        return {"tools": []}
    decorate = getattr(sdk, "tool", None)
    create_server = getattr(sdk, "create_sdk_mcp_server", None)
    if not callable(decorate) or not callable(create_server):
        return {"tools": []}

    sdk_tools: list[Callable[..., Any]] = []
    allowed: list[str] = []
    for schema in tools:
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
                        "text": (
                            "DeepTutor accepted this tool call and will provide its result next."
                        ),
                    }
                ]
            }

        pending_result.__name__ = f"deeptutor_{name}"
        sdk_tools.append(decorate(name, description, parameters)(pending_result))
        allowed.append(f"{_MCP_TOOL_PREFIX}{name}")

    if not sdk_tools:
        return {"tools": []}
    server = create_server(_MCP_SERVER_NAME, tools=sdk_tools)
    return {
        "tools": allowed,
        "allowed_tools": allowed,
        "mcp_servers": {_MCP_SERVER_NAME: server},
    }


def _session_signature(
    model: str,
    reasoning_effort: str | None,
    tools: list[dict[str, Any]] | None,
) -> str:
    payload = {
        "model": _strip_model_prefix(model),
        "reasoning_effort": reasoning_effort or "",
        "tools": tools or [],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _incremental_prompt(
    session: _CodeBuddySession,
    messages: list[dict[str, Any]],
) -> str:
    previous = session.messages
    if previous and len(messages) >= len(previous) and messages[: len(previous)] == previous:
        delta = list(messages[len(previous) :])
        if delta and session.last_response and delta[0].get("role") == "assistant":
            if _content_text(delta[0].get("content")) == session.last_response:
                delta.pop(0)
        prompt = _messages_to_prompt(delta)
        if prompt:
            return prompt
    return _messages_to_prompt(messages)


async def _consume_messages(
    messages: Any,
    *,
    on_content_delta: Callable[[str], Awaitable[None]] | None,
    interrupt: Callable[[], Awaitable[None]] | None = None,
) -> LLMResponse:
    chunks: list[str] = []
    pending_result_text = ""
    async for message in messages:
        if _is_error_result(message):
            return LLMResponse(
                content=f"Error calling CodeBuddy: {_result_text(message)}",
                finish_reason="error",
            )
        if _is_result_message(message):
            pending_result_text = _result_text(message)
            continue

        tool_calls = _assistant_tool_calls(message)
        text = _assistant_text(message)
        if text:
            chunks.append(text)
            if on_content_delta:
                await on_content_delta(text)
        if tool_calls:
            if interrupt is not None:
                try:
                    await interrupt()
                    await _drain_interrupted_response(messages)
                except Exception:
                    pass
            return LLMResponse(
                content="".join(chunks),
                tool_calls=tool_calls,
                finish_reason="tool_calls",
            )

    if not chunks and pending_result_text:
        chunks.append(pending_result_text)
        if on_content_delta:
            await on_content_delta(pending_result_text)
    return LLMResponse(content="".join(chunks), finish_reason="stop")


async def _drain_interrupted_response(messages: Any) -> None:
    """Consume the SDK's interrupt result so it cannot leak into the next turn."""
    try:
        async for message in messages:
            if _is_result_message(message) or type(message).__name__ == "ErrorMessage":
                return
    except Exception:
        return


def _assistant_tool_calls(message: Any) -> list[ToolCallRequest]:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if not isinstance(content, list):
        return []

    calls: list[ToolCallRequest] = []
    for block in content:
        if isinstance(block, dict):
            block_type = str(block.get("type") or "").lower()
            name = str(block.get("name") or "")
            call_id = str(block.get("id") or "")
            arguments = block.get("input")
        else:
            block_type = type(block).__name__.lower()
            name = str(getattr(block, "name", "") or "")
            call_id = str(getattr(block, "id", "") or "")
            arguments = getattr(block, "input", None)
        if block_type not in {"tool_use", "tooluse"} and not block_type.endswith("tooluseblock"):
            continue
        if not name.startswith(_MCP_TOOL_PREFIX):
            continue
        tool_name = name[len(_MCP_TOOL_PREFIX) :]
        if not tool_name:
            continue
        calls.append(
            ToolCallRequest(
                id=call_id or f"codebuddy_tool_{len(calls)}",
                name=tool_name,
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    return calls


def _reasoning_options(reasoning_effort: str | None) -> dict[str, Any]:
    """Map DeepTutor reasoning levels to CodeBuddy SDK thinking controls.

    The SDK enables adaptive thinking when the field is omitted, unlike the
    local CodeBuddy CLI configuration. Defaulting to disabled keeps ordinary
    chat latency aligned with the CLI; an explicit effort turns it back on.
    """
    effort = (reasoning_effort or "").strip().lower()
    if effort in {"low", "medium", "high", "xhigh"}:
        return {"thinking": {"type": "adaptive"}, "effort": effort}
    if effort == "adaptive":
        return {"thinking": {"type": "adaptive"}}
    return {"thinking": {"type": "disabled"}}


def _options_has_api_key_env(options: Any | None) -> bool:
    if options is None:
        return False
    env = getattr(options, "env", None)
    if isinstance(env, dict) and env.get(_CODEBUDDY_API_KEY_ENV):
        return True
    kwargs = getattr(options, "kwargs", None)
    if isinstance(kwargs, dict):
        option_env = kwargs.get("env")
        return isinstance(option_env, dict) and bool(option_env.get(_CODEBUDDY_API_KEY_ENV))
    return False


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").strip() or "user"
        content = _content_text(message.get("content"))
        if not content:
            continue
        if role == "system":
            heading = "System instructions"
        elif role == "assistant":
            heading = "Assistant"
        elif role == "tool":
            name = message.get("name") or message.get("tool_call_id") or "tool"
            heading = f"Tool result ({name})"
        else:
            heading = "User"
        sections.append(f"{heading}:\n{content}")

    return "\n\n".join(sections) if sections else ""


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _content_part_text(content)
    if isinstance(content, list):
        parts = [_content_part_text(part) for part in content]
        return "\n".join(part for part in parts if part)
    return str(content)


def _content_part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return str(part)
    part_type = part.get("type")
    if part_type in {"text", "input_text", "output_text"}:
        return str(part.get("text") or "")
    if "text" in part and isinstance(part.get("text"), str):
        return str(part["text"])
    if part_type in {"image_url", "input_image"}:
        return "[image input omitted]"
    return ""


def _assistant_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        content = [content]

    chunks: list[str] = []
    for block in content:
        text = _block_text(block)
        if text:
            chunks.append(text)
    return "".join(chunks)


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        block_type = block.get("type")
        if block_type in {"text", "assistant_text"} or "text" in block:
            return str(block.get("text") or "")
        return ""
    block_type = type(block).__name__
    if block_type == "TextBlock" or hasattr(block, "text"):
        return str(getattr(block, "text") or "")
    return ""


def _is_result_message(message: Any) -> bool:
    message_type = type(message).__name__
    if message_type == "ResultMessage" or message_type.endswith("ResultMessage"):
        return True
    if hasattr(message, "result") and hasattr(message, "is_error"):
        return True
    return isinstance(message, dict) and str(message.get("type") or "").lower() == "result"


def _is_error_result(message: Any) -> bool:
    if not _is_result_message(message):
        return False
    if isinstance(message, dict):
        return bool(message.get("is_error") or message.get("error"))
    return bool(getattr(message, "is_error", False) or getattr(message, "error", None))


def _result_text(message: Any) -> str:
    if isinstance(message, dict):
        value = message.get("result") or message.get("error") or message.get("content")
    else:
        value = getattr(message, "result", None) or getattr(message, "error", None)
    return "" if value is None else str(value)


def _friendly_error(exc: Exception) -> str:
    message = str(exc)
    if "Authentication required" in message:
        return (
            "Error calling CodeBuddy: authentication required. Run "
            "`deeptutor provider login codebuddy`, run `codebuddy` and enter `/login`, "
            "or set CODEBUDDY_API_KEY."
        )
    if "cancel scope" in message.lower():
        return (
            "Error calling CodeBuddy: the SDK session was closed from a different "
            "async task than it was opened on. Retry the message; if it persists, "
            "restart the backend."
        )
    return f"Error calling CodeBuddy: {message}"


@asynccontextmanager
async def _temporary_codebuddy_api_key(api_key: str | None):
    if not api_key:
        yield
        return
    async with _API_KEY_ENV_LOCK:
        previous = os.environ.get(_CODEBUDDY_API_KEY_ENV)
        os.environ[_CODEBUDDY_API_KEY_ENV] = api_key
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(_CODEBUDDY_API_KEY_ENV, None)
            else:
                os.environ[_CODEBUDDY_API_KEY_ENV] = previous


async def fetch_codebuddy_models(api_key: str | None = None) -> list[str]:
    """Return the model catalog currently available to the logged-in account."""
    _load_sdk()
    cli_path = shutil.which("codebuddy") or shutil.which("cbc")
    if not cli_path:
        raise RuntimeError("CodeBuddy CLI is required to sync account models.")

    cli_args = [
        cli_path,
        "--print",
        ".",
        "--model",
        "__deeptutor_list_models__",
        "--output-format",
        "json",
        "--max-turns",
        "1",
    ]
    process_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        command = ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(cli_args)]
        # Windows-only constants; the stubs omit them off-Windows, and mypy
        # cannot narrow on os.name the way it narrows on sys.platform.
        process_kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        command = cli_args
        process_kwargs["start_new_session"] = True

    env = os.environ.copy()
    if api_key:
        env[_CODEBUDDY_API_KEY_ENV] = api_key
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        **process_kwargs,
    )
    stdout, stderr = await process.communicate()
    output = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    marker = "supported models for your account:"
    catalog = output.lower().split(marker, 1)[-1] if marker in output.lower() else ""
    models = re.findall(r"(?m)^\s*-\s+([A-Za-z0-9][A-Za-z0-9._-]*)\s*$", catalog)
    if not models:
        raise RuntimeError(output.strip() or "CodeBuddy did not return an account model catalog.")
    return list(dict.fromkeys(models))


__all__ = [
    "CodeBuddyProvider",
    "DEFAULT_CODEBUDDY_MODEL",
    "fetch_codebuddy_models",
]
