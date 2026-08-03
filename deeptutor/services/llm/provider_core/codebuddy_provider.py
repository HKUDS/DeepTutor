"""CodeBuddy Agent SDK provider."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import os
import re
import shutil
import subprocess
from types import ModuleType
from typing import Any

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse

DEFAULT_CODEBUDDY_MODEL = "codebuddy/default"
_CODEBUDDY_API_KEY_ENV = "CODEBUDDY_API_KEY"
_API_KEY_ENV_LOCK = asyncio.Lock()


class CodeBuddyProvider(LLMProvider):
    """Provider backed by the CodeBuddy Agent SDK.

    CodeBuddy is exposed as an agent SDK instead of an OpenAI-compatible chat
    endpoint, so this adapter flattens chat messages into one prompt and
    returns text deltas only. DeepTutor-native tool calls stay disabled for this
    backend until CodeBuddy tool events are mapped end to end.
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = DEFAULT_CODEBUDDY_MODEL,
    ):
        normalized_api_key = (
            None if api_key in {None, "", "sk-no-key-required"} else api_key
        )
        super().__init__(api_key=normalized_api_key, api_base=None)
        self.default_model = default_model or DEFAULT_CODEBUDDY_MODEL

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
        del temperature, tool_choice, kwargs
        return await self._run_codebuddy(
            messages,
            tools,
            model,
            max_tokens,
            reasoning_effort=reasoning_effort,
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
        del temperature, tool_choice, on_reasoning_delta, kwargs
        return await self._run_codebuddy(
            messages,
            tools,
            model,
            max_tokens,
            reasoning_effort=reasoning_effort,
            on_content_delta=on_content_delta,
        )

    async def _run_codebuddy(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        reasoning_effort: str | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        try:
            sdk = _load_sdk()
            prompt = _messages_to_prompt(messages, tools)
            options = _build_options(
                sdk,
                model or self.default_model,
                max_tokens,
                self.api_key,
                reasoning_effort,
            )
            chunks: list[str] = []
            pending_result_text = ""

            env_api_key = None if _options_has_api_key_env(options) else self.api_key
            async with _temporary_codebuddy_api_key(env_api_key):
                kwargs: dict[str, Any] = {"prompt": prompt}
                if options is not None:
                    kwargs["options"] = options
                async for message in sdk.query(**kwargs):
                    if _is_error_result(message):
                        return LLMResponse(
                            content=f"Error calling CodeBuddy: {_result_text(message)}",
                            finish_reason="error",
                        )
                    if _is_result_message(message):
                        pending_result_text = _result_text(message)
                        continue

                    text = _assistant_text(message)
                    if not text:
                        continue
                    chunks.append(text)
                    if on_content_delta:
                        await on_content_delta(text)

            if not chunks and pending_result_text:
                chunks.append(pending_result_text)
                if on_content_delta:
                    await on_content_delta(pending_result_text)
            return LLMResponse(content="".join(chunks), finish_reason="stop")
        except Exception as exc:
            return LLMResponse(content=_friendly_error(exc), finish_reason="error")

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
) -> Any | None:
    options_cls = getattr(sdk, "CodeBuddyAgentOptions", None)
    if options_cls is None:
        return None

    stripped_model = _strip_model_prefix(model)
    model_kwargs = {} if not stripped_model or stripped_model == "default" else {"model": stripped_model}
    env_kwargs = {"env": {_CODEBUDDY_API_KEY_ENV: api_key}} if api_key else {}
    reasoning_kwargs = _reasoning_options(reasoning_effort)
    text_only_kwargs = {"tools": []}
    candidates = [
        {
            **model_kwargs,
            **env_kwargs,
            **reasoning_kwargs,
            **text_only_kwargs,
            "max_turns": 1,
            "permission_mode": "plan",
        },
        {**model_kwargs, **reasoning_kwargs, **text_only_kwargs, "max_turns": 1},
        {
            **model_kwargs,
            **env_kwargs,
            **reasoning_kwargs,
            **text_only_kwargs,
            "maxTurns": 1,
            "permissionMode": "plan",
        },
        {**model_kwargs, **reasoning_kwargs, **text_only_kwargs, "maxTurns": 1},
        {**model_kwargs, **reasoning_kwargs, **text_only_kwargs},
        {**model_kwargs, **env_kwargs, "max_turns": 1, "permission_mode": "plan"},
        {**model_kwargs, "max_turns": 1},
        {**model_kwargs, **env_kwargs, "maxTurns": 1, "permissionMode": "plan"},
        {**model_kwargs, "maxTurns": 1},
        model_kwargs,
    ]
    if max_tokens > 0:
        candidates.insert(
            0,
            {
                **model_kwargs,
                **env_kwargs,
                **reasoning_kwargs,
                **text_only_kwargs,
                "max_turns": 1,
                "permission_mode": "plan",
                "max_tokens": max_tokens,
            },
        )

    for kwargs in candidates:
        try:
            return options_cls(**kwargs)
        except TypeError:
            continue
    return None


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


def _messages_to_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> str:
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

    if tools:
        sections.append(
            "DeepTutor tool schemas were available for this turn, but the CodeBuddy "
            "provider currently returns text only. Answer directly when possible."
        )
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
        process_kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
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
        raise RuntimeError(
            output.strip() or "CodeBuddy did not return an account model catalog."
        )
    return list(dict.fromkeys(models))


__all__ = [
    "CodeBuddyProvider",
    "DEFAULT_CODEBUDDY_MODEL",
    "fetch_codebuddy_models",
]
