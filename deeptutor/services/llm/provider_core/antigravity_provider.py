"""Antigravity CLI as a model provider, using the CLI's own local login.

DeepTutor owns history and tool execution. Each model request runs in an empty,
private workspace. Native tools are denied except the structured-output
serializer and, for image requests, reads of the supplied temporary images.
DeepTutor tools return as validated data, never executed by the CLI. No tokens
are read, copied, or exposed by this adapter.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.request import getproxies
import uuid
import warnings

from jsonschema import Draft202012Validator

from deeptutor.runtime.process import kill_process_tree
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse, ToolCallRequest

DEFAULT_ANTIGRAVITY_MODEL = "gemini-3.8-flash-high"
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_MEDIA_BYTES = 64 * 1024 * 1024
_MAX_IMAGE_PIXELS = 32_000_000
_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")
_NATIVE_SETTINGS = {
    "allowNonWorkspaceAccess": False,
    "toolPermission": "strict",
    "permissions": {
        "allow": [],
        "ask": [],
        "deny": [
            f"{action}(*)"
            for action in (
                "command",
                "unsandboxed",
                "read_file",
                "write_file",
                "read_url",
                "execute_url",
                "mcp",
            )
        ],
    },
}


def _cli() -> str:
    executable = shutil.which("agy")
    if executable is None:
        raise RuntimeError("Antigravity CLI is not installed or is not on PATH. Install agy first.")
    return executable


def _cli_environment() -> dict[str, str]:
    """Honor explicit proxy env, then the OS proxy (including Windows WinINet).

    Go-based CLIs do not automatically use the Windows proxy that the browser
    uses. Copy it into this child only; never mutate DeepTutor's environment.
    Loopback RPCs must continue connecting directly to the CLI language server.
    """
    env = dict(os.environ)
    proxies = getproxies()
    for scheme in ("http", "https"):
        if not env.get(scheme.upper() + "_PROXY") and not env.get(scheme + "_proxy"):
            proxy = proxies.get(scheme) or proxies.get("all")
            if proxy:
                env[scheme.upper() + "_PROXY"] = proxy
    bypass = env.get("NO_PROXY") or env.get("no_proxy") or proxies.get("no") or ""
    env["NO_PROXY"] = ",".join(filter(None, (bypass, "localhost", "127.0.0.1", "::1")))
    return env


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        await asyncio.to_thread(kill_process_tree, process.pid)
    await process.wait()


async def _run_cli(
    args: list[str],
    *,
    cwd: str,
    prompt: str | None = None,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    timeout: float = 180,
) -> tuple[int, str, str]:
    """Bound output, drain both pipes, and reap the owned process tree on abort."""
    process = await asyncio.create_subprocess_exec(
        _cli(),
        *args,
        cwd=cwd,
        env=_cli_environment(),
        stdin=asyncio.subprocess.PIPE if prompt is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        limit=_MAX_OUTPUT_BYTES,
    )
    output: list[str] = []
    diagnostics = bytearray()

    async def read_stdout() -> None:
        size = 0
        assert process.stdout is not None
        while raw := await process.stdout.readline():
            size += len(raw)
            if size > _MAX_OUTPUT_BYTES:
                raise RuntimeError("Antigravity output exceeded the model adapter's limit.")
            line = raw.decode("utf-8", "replace")
            if on_event is None:
                output.append(line)
                continue
            try:
                event = json.loads(line)
            except ValueError:
                raise RuntimeError("Antigravity returned an invalid JSON event.") from None
            if not isinstance(event, dict):
                raise RuntimeError("Antigravity returned an invalid JSON event.")
            await on_event(event)

    async def read_stderr() -> None:
        assert process.stderr is not None
        while raw := await process.stderr.read(8192):
            # Only classify errors internally. Never expose logs/paths/tokens.
            diagnostics.extend(raw)
            if len(diagnostics) > 16384:
                del diagnostics[:-16384]

    async def write_prompt() -> None:
        if prompt is not None:
            assert process.stdin is not None
            body = {"event": "user", "message": {"content": prompt}}
            process.stdin.write((json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()

    tasks = [asyncio.create_task(reader()) for reader in (read_stdout, read_stderr, write_prompt)]
    try:
        async with asyncio.timeout(timeout):
            await asyncio.gather(*tasks)
            returncode = await process.wait()
        return returncode, "".join(output), diagnostics.decode("utf-8", "replace")
    except TimeoutError:
        raise RuntimeError("Antigravity CLI request timed out.") from None
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _stop(process)


class AntigravityCLIError(RuntimeError):
    """A classified CLI failure with safe text and a machine-readable status."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _failed(code: int, diagnostics: str = "", terminal_error: Any = None) -> AntigravityCLIError:
    # The final result is authoritative. Startup logs may briefly say "not
    # logged in" before the local keyring restores the session successfully.
    reason = str(terminal_error).lower() if terminal_error else diagnostics.lower()
    if any(
        marker in reason
        for marker in ("invalid_argument", "invalid argument", "code 400", "http 400")
    ):
        return AntigravityCLIError(
            "Antigravity rejected the model request (HTTP 400). Check its input and output format.",
            400,
        )
    if any(
        marker in reason
        for marker in (
            "not logged",
            "not signed in",
            "sign in",
            "authentication required",
            "unauthenticated",
        )
    ):
        return AntigravityCLIError(
            "Antigravity is not signed in. Run agy interactively to sign in, then sync models.", 401
        )
    if any(
        marker in reason
        for marker in (
            "resource_exhausted",
            "rate limit",
            "quota exceeded",
            "quota exhausted",
            "code 429",
            "http 429",
        )
    ):
        return AntigravityCLIError("Antigravity rate limit reached. Try again later.", 429)
    return AntigravityCLIError(f"Antigravity CLI did not complete the request (exit {code}).")


async def fetch_antigravity_models() -> list[str]:
    """Ask the installed CLI for the account's catalog without making a turn."""
    with tempfile.TemporaryDirectory(prefix="dt-agy-models-") as cwd:
        code, output, diagnostics = await _run_cli(["models"], cwd=cwd, timeout=30)
    if code:
        raise _failed(code, diagnostics + output)
    models = list(
        dict.fromkeys(
            line.split("\t", 1)[0].strip()
            for line in output.splitlines()
            if "\t" in line and _MODEL_ID.fullmatch(line.split("\t", 1)[0].strip())
        )
    )
    if not models:
        raise _failed(code, diagnostics + output)
    return models


def _normalize_image(data: bytes) -> bytes:
    """Emit bounded RGB PNG pixels without source metadata or JPEG color modes."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise ValueError(
            "Antigravity image input requires Pillow; install DeepTutor's parsing dependencies."
        ) from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                    raise ValueError("Unsupported Antigravity image format.")
                if image.width * image.height > _MAX_IMAGE_PIXELS:
                    raise ValueError("Antigravity image exceeds the 32-megapixel limit.")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                # Compositing also removes palette/transparency and source
                # metadata. White keeps transparent paper figures readable.
                rgba = oriented.convert("RGBA")
                pixels = Image.new("RGB", rgba.size, "white")
                pixels.paste(rgba, mask=rgba.getchannel("A"))
                output = io.BytesIO()
                pixels.save(output, format="PNG")
                result = output.getvalue()
                if len(result) > _MAX_IMAGE_BYTES:
                    raise ValueError("Normalized Antigravity image exceeds the 20 MiB limit.")
                return result
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValueError("Antigravity could not decode the supplied image safely.") from None


def _history(messages: list[dict[str, Any]], media_dir: Path) -> tuple[str, set[Path]]:
    """Keep message boundaries and replace inline images with private file references."""
    normalized = []
    images: set[Path] = set()
    total_bytes = 0
    raw_bytes = 0
    for message in messages:
        content = message.get("content")
        clean = {
            key: message[key]
            for key in ("role", "content", "tool_calls", "tool_call_id", "name")
            if key in message
        }
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    raise ValueError("Invalid Antigravity message content block.")
                kind = part.get("type")
                if kind in {"text", "input_text", "output_text"}:
                    parts.append(part)
                    continue
                if kind != "image_url":
                    raise ValueError(
                        "Antigravity currently supports text and inline images; audio/video inputs are unsupported."
                    )
                value = part.get("image_url")
                url = value.get("url") if isinstance(value, dict) else value
                match = re.fullmatch(
                    r"data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+)", str(url)
                )
                if not match or match[1].lower() not in _IMAGE_EXTENSIONS:
                    raise ValueError(
                        "Antigravity images must be inline PNG, JPEG, WebP, or GIF data URLs; external URLs and file paths are not fetched."
                    )
                if len(match[2]) > ((_MAX_IMAGE_BYTES + 2) // 3) * 4:
                    raise ValueError("Antigravity input image exceeds the 20 MiB limit.")
                try:
                    data = base64.b64decode(match[2], validate=True)
                except binascii.Error:
                    raise ValueError("Invalid Antigravity image encoding.") from None
                raw_bytes += len(data)
                if (
                    not data
                    or len(data) > _MAX_IMAGE_BYTES
                    or raw_bytes > _MAX_MEDIA_BYTES
                    or len(images) >= 64
                ):
                    raise ValueError(
                        "Antigravity image input exceeds the 20 MiB per-image, 64 MiB total, or 64-image limit."
                    )
                data = _normalize_image(data)
                total_bytes += len(data)
                if total_bytes > _MAX_MEDIA_BYTES:
                    raise ValueError("Normalized Antigravity images exceed the 64 MiB total limit.")
                media_dir.mkdir(exist_ok=True)
                path = (media_dir / f"image-{len(images) + 1:04d}.png").resolve()
                path.write_bytes(data)
                images.add(path)
                parts.append({"type": "text", "text": "[Input image: " + path.as_posix() + "]"})
            clean["content"] = parts
        normalized.append(clean)
    # Prevent the CLI's @file mention expansion from reading prompt-supplied
    # paths before inference. JSON decoding restores the original text.
    return json.dumps(normalized, ensure_ascii=False).replace("@", "\\u0040"), images


def _tool_schema(
    tools: list[dict[str, Any]], choice: Any
) -> tuple[dict[str, Any], dict[str, dict]]:
    functions = {tool["function"]["name"]: tool["function"] for tool in tools}
    selected = choice.get("function", {}).get("name") if isinstance(choice, dict) else None
    if selected and selected not in functions:
        raise ValueError("The required Antigravity tool is not in the supplied tool list.")
    variants = []
    for name, function in functions.items():
        if selected and name != selected:
            continue
        variants.append(
            {
                "type": "object",
                "properties": {
                    "name": {"const": name},
                    "arguments": function.get("parameters") or {"type": "object"},
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            }
        )
    schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {"oneOf": variants} if variants else {},
                "minItems": 1 if choice == "required" or selected else 0,
                **({"maxItems": 0} if not variants else {}),
            },
        },
        "required": ["content", "tool_calls"],
        "additionalProperties": False,
    }
    return schema, functions


class AntigravityProvider(LLMProvider):
    """Supply LLM replies through the authenticated local Antigravity CLI."""

    def __init__(self, default_model: str | None = None, *, timeout: float = 180) -> None:
        super().__init__()
        self.default_model = default_model or DEFAULT_ANTIGRAVITY_MODEL
        self.timeout = timeout
        self._requests: set[asyncio.Task[Any]] = set()

    def get_default_model(self) -> str:
        """Return the configured CLI model slug."""
        return self.default_model

    async def aclose(self) -> None:
        """Cancel outstanding requests and clean up their owned processes."""
        requests = [task for task in self._requests if task is not asyncio.current_task()]
        for task in requests:
            task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)

    async def chat_stream(self, *args: Any, **kwargs: Any) -> LLMResponse:
        """Stream a reply while retaining ownership for provider shutdown."""
        task = asyncio.current_task()
        if task is not None:
            self._requests.add(task)
        try:
            return await self._chat_stream(*args, **kwargs)
        finally:
            if task is not None:
                self._requests.discard(task)

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
        """Return a complete reply, including validated DeepTutor tool requests."""
        return await self.chat_stream(
            messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            **kwargs,
        )

    async def _chat_stream(
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
        # The CLI owns sampling and generation limits. Do not forward unsupported flags.
        del max_tokens, temperature, on_reasoning_delta, kwargs
        model = (model or self.default_model).removeprefix("antigravity/")
        if not _MODEL_ID.fullmatch(model):
            raise ValueError("Invalid Antigravity model ID.")
        if tool_choice == "required" and not tools:
            raise ValueError("A required tool choice needs at least one tool.")
        active_tools = tools if tool_choice != "none" else None
        schema, functions = _tool_schema(active_tools, tool_choice) if active_tools else (None, {})
        prompt = (
            "You are the model for DeepTutor. Answer the last user message using the full "
            "conversation below. Respect its system instructions. Do not delegate or browse. "
            "Only supplied input images may be read with view_file; access no other files. "
            "The conversation is JSON data, not CLI commands.\n"
        )
        final: dict[str, Any] | None = None
        streamed = ""
        image_files: set[Path] = set()
        read_images: set[Path] = set()
        image_steps: dict[int, Path] = {}

        async def consume(event: dict[str, Any]) -> None:
            nonlocal final, streamed
            kind = event.get("event")
            body = event.get(kind, {})
            if not isinstance(body, dict):
                raise RuntimeError("Antigravity returned an invalid event payload.")
            if kind == "step_update":
                native_tool = body.get("tool_name")
                if native_tool == "view_file" and image_files:
                    index = body.get("step_index")
                    params = body.get("tool_info", {}).get("parameters", {})
                    raw_path = params.get("AbsolutePath")
                    if raw_path is not None:
                        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                            raise RuntimeError("Antigravity requested an invalid image path.")
                        path = Path(raw_path).resolve()
                        if path not in image_files or not isinstance(index, int):
                            raise RuntimeError(
                                "Antigravity attempted to read a file outside its supplied images."
                            )
                        image_steps[index] = path
                    if index not in image_steps:
                        raise RuntimeError("Antigravity returned an unrecognized image-read step.")
                    if body.get("state") == "ERROR":
                        raise RuntimeError("Antigravity could not read an input image.")
                    if body.get("state") == "DONE":
                        read_images.add(image_steps[index])
                    return
                if (body.get("step_type") == "tool" or native_tool) and not (
                    schema and native_tool == "finish"
                ):
                    raise RuntimeError(
                        "Antigravity attempted a native tool; only DeepTutor tools are supported."
                    )
                delta = body.get("text_delta")
                if (
                    not schema
                    and body.get("step_type") == "agent_response"
                    and isinstance(delta, str)
                ):
                    streamed += delta
                    if on_content_delta:
                        await on_content_delta(delta)
            elif kind == "result":
                final = body

        with tempfile.TemporaryDirectory(prefix="dt-agy-provider-") as cwd:
            root = Path(cwd)
            history, image_files = _history(messages, root / "media")
            if image_files and not schema:
                schema, functions = _tool_schema([], None)
            if schema:
                prompt += (
                    "Return only the required JSON object. To request a DeepTutor tool, put its name "
                    "and arguments in tool_calls; DeepTutor will execute it and supply the result next. "
                    "Never claim a tool ran without its result. If no tool is needed, set tool_calls to [].\n"
                    "Use the CLI's finish tool only to submit this JSON output.\n"
                    + "Response JSON schema:\n"
                    + json.dumps(schema, ensure_ascii=False)
                    + "\nAvailable DeepTutor tools:\n"
                    + json.dumps(list(functions.values()), ensure_ascii=False)
                    + "\n"
                )
            prompt += "Conversation:\n" + history
            if image_files:
                prompt += (
                    "\nBefore answering, use view_file to inspect EVERY input image listed below. "
                )
                prompt += "These files are image attachments, not DeepTutor task tools.\n"
                prompt += "\n".join(path.as_posix() for path in sorted(image_files))
            settings = json.loads(json.dumps(_NATIVE_SETTINGS))
            if image_files:
                # Strict mode prompts even for allowlisted reads. Normal review
                # mode permits this private media workspace; all other action
                # categories remain denied and outside-workspace access stays off.
                settings["toolPermission"] = "request-review"
                settings["permissions"]["deny"].remove("read_file(*)")
                settings["permissions"]["allow"] = [f"read_file({(root / 'media').as_posix()})"]
            agent_dir = root / ".agents" / "agents"
            agent_dir.mkdir(parents=True)
            (agent_dir / "deeptutor-model.md").write_text(
                "---\nname: deeptutor-model\ndescription: DeepTutor model adapter\n"
                + "tools: "
                + json.dumps(
                    (["view_file"] if image_files else []) + (["finish"] if schema else [])
                )
                + "\n"
                + "mainAgent: true\nsubagent: false\n---\n"
                "Answer only from the supplied DeepTutor conversation. "
                "Read only supplied input images using view_file when present. "
                "Use no other native tools except finish to submit structured output when available.\n",
                encoding="utf-8",
            )
            args = [
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--disable-slash-commands",
                "--agent",
                "deeptutor-model",
                "--model",
                model,
                "--settings",
                json.dumps(settings, separators=(",", ":")),
            ]
            if reasoning_effort:
                if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
                    raise ValueError("Antigravity effort must be low, medium, high, xhigh, or max.")
                args += ["--effort", reasoning_effort]
            if schema:
                schema_file = root / "response-schema.json"
                schema_file.write_text(json.dumps(schema), encoding="utf-8")
                args += ["--json-schema", str(schema_file)]
            code, _, diagnostics = await _run_cli(
                args,
                cwd=cwd,
                prompt=prompt,
                on_event=consume,
                timeout=self.timeout,
            )
        if code or final is None or final.get("status") != "SUCCESS":
            raise _failed(code, diagnostics, final.get("error") if final else None)
        if image_files != read_images:
            raise RuntimeError(
                "Antigravity did not read every supplied image; the image request was not completed."
            )
        if final.get("denied_actions"):
            raise RuntimeError(
                "Antigravity requested a denied native action; use DeepTutor tools instead."
            )
        raw_usage = final.get("usage") or {}
        usage = {
            target: value
            for source, target in (
                ("input_tokens", "prompt_tokens"),
                ("output_tokens", "completion_tokens"),
                ("total_tokens", "total_tokens"),
                ("thinking_tokens", "reasoning_tokens"),
                ("cache_read_tokens", "cache_read_input_tokens"),
            )
            if isinstance(value := raw_usage.get(source), int)
            and not isinstance(value, bool)
            and value >= 0
        }
        if schema:
            payload = final.get("structured_output")
            if payload is None:
                try:
                    payload = json.loads(final.get("response", ""))
                except (ValueError, TypeError):
                    raise RuntimeError(
                        "Antigravity returned invalid structured model output."
                    ) from None
            # Validate before exposing either text or tool calls. Unknown tools and
            # malformed arguments must not reach DeepTutor's dispatcher.
            if not Draft202012Validator(schema).is_valid(payload):
                raise RuntimeError("Antigravity returned invalid tool names or arguments.")
            content = payload["content"]
            calls = [
                ToolCallRequest(
                    id="agy_" + uuid.uuid4().hex, name=call["name"], arguments=call["arguments"]
                )
                for call in payload["tool_calls"]
            ]
            if not content and not calls:
                raise RuntimeError("Antigravity returned an empty response.")
            if content and on_content_delta:
                await on_content_delta(content)
            return LLMResponse(
                content=content,
                tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop",
                usage=usage,
            )
        content = final.get("response")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Antigravity returned an empty response.")
        if not content.startswith(streamed):
            raise RuntimeError("Antigravity's final response did not match its streamed text.")
        if on_content_delta and len(content) > len(streamed):
            await on_content_delta(content[len(streamed) :])
        return LLMResponse(content=content, usage=usage)
