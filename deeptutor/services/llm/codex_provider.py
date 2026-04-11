"""OpenAI Codex provider — calls the Codex SSE endpoint using OAuth tokens.

This module enables DeepTutor to use Codex models (gpt-5.3-codex, gpt-5-codex-mini,
etc.) by authenticating through the same OAuth flow as the `openai/codex` CLI.

The api_key field is expected to be a JSON-serialised credential:
    {"accessToken": "...", "refreshToken": "...", "expiresAt": 1234567890}

Or a plain bearer token string (dev shortcut).
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
from collections.abc import AsyncGenerator

import aiohttp
import certifi

from .exceptions import LLMAPIError, LLMAuthenticationError, LLMConfigError

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────
CODEX_API_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_MODEL = "gpt-5.3-codex"

MODEL_ALIASES: dict[str, str] = {
    "codex": "gpt-5.3-codex",
    "codex-mini": "gpt-5-codex-mini",
    "codex-mini-latest": "gpt-5-codex-mini",
}


def _session_kwargs(timeout: aiohttp.ClientTimeout) -> dict[str, object]:
    """Build aiohttp session kwargs with a stable SSL configuration."""
    disable_verify = os.getenv("DISABLE_SSL_VERIFY", "").lower() in {"1", "true", "yes"}
    ssl_context: ssl.SSLContext | bool
    if disable_verify:
        ssl_context = False
    else:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    return {"timeout": timeout, "connector": connector}


# ─── Credential parsing ────────────────────────────────────────────────────
class _CodexCredential:
    """Parsed Codex OAuth credential."""

    __slots__ = ("access_token", "refresh_token", "expires_at")

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: float | None = None,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return (time.time() * 1000) + 30_000 >= self.expires_at


def _parse_credential(api_key: str | None) -> _CodexCredential:
    """Parse a JSON-serialised credential or plain bearer token."""
    if not api_key or not api_key.strip():
        raise LLMAuthenticationError(
            "Codex credential is missing. Connect your ChatGPT account in Settings.",
            provider="openai_codex",
        )
    raw = api_key.strip()
    if not raw.startswith("{"):
        return _CodexCredential(access_token=raw)
    try:
        data = json.loads(raw)
        token = data.get("accessToken", "")
        if not token:
            raise LLMAuthenticationError(
                "Codex credential JSON missing accessToken.",
                provider="openai_codex",
            )
        return _CodexCredential(
            access_token=token,
            refresh_token=data.get("refreshToken"),
            expires_at=data.get("expiresAt"),
        )
    except json.JSONDecodeError as exc:
        raise LLMConfigError(
            f"Invalid Codex credential JSON: {exc}"
        ) from exc


def _normalize_model(model: str) -> str:
    stripped = model.replace("openai/", "").strip()
    return MODEL_ALIASES.get(stripped, stripped)


# ─── Token refresh ──────────────────────────────────────────────────────────
async def _refresh_token(refresh_token: str) -> _CodexCredential:
    """Exchange a refresh token for a new access token."""
    body = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(**_session_kwargs(timeout)) as session:
        async with session.post(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise LLMAuthenticationError(
                    f"Codex token refresh failed ({resp.status}): {text}",
                    provider="openai_codex",
                )
            data = await resp.json()
            return _CodexCredential(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", refresh_token),
                expires_at=(
                    time.time() * 1000 + data["expires_in"] * 1000
                    if "expires_in" in data
                    else None
                ),
            )


async def _ensure_valid_credential(cred: _CodexCredential) -> _CodexCredential:
    """Auto-refresh if expired."""
    if cred.is_expired and cred.refresh_token:
        logger.info("Codex token expired, refreshing...")
        return await _refresh_token(cred.refresh_token)
    return cred


# ─── Build request body ────────────────────────────────────────────────────
def _build_codex_body(
    *,
    model: str,
    prompt: str,
    system_prompt: str,
    messages: list[dict[str, object]] | None,
    stream: bool,
    reasoning_effort: str | None,
) -> dict[str, object]:
    """Build the Codex /responses request payload."""
    codex_input: list[dict[str, object]] = []

    if messages:
        for msg in messages:
            role = str(msg.get("role", "user"))
            content_raw = msg.get("content", "")
            content_str = content_raw if isinstance(content_raw, str) else str(content_raw)

            if role == "system":
                # System messages go into `instructions`, handled below
                continue

            # Map to Codex content parts
            part_type = "input_text" if role == "user" else "output_text"
            codex_input.append({
                "role": role if role in ("user", "assistant") else "user",
                "content": [{"type": part_type, "text": content_str}],
            })
    else:
        codex_input.append({
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        })

    body: dict[str, object] = {
        "model": _normalize_model(model),
        "input": codex_input,
        "stream": stream,
        "store": False,
    }

    # Set instructions from system_prompt or first system message
    instructions = system_prompt
    if messages:
        for msg in messages:
            if msg.get("role") == "system":
                raw = msg.get("content", "")
                instructions = raw if isinstance(raw, str) else str(raw)
                break
    if instructions:
        body["instructions"] = instructions

    effort = reasoning_effort or "high"
    body["reasoning"] = {"effort": effort}

    return body


# ─── SSE parsing helper ────────────────────────────────────────────────────
def _parse_sse_line(line: str) -> dict[str, object] | None:
    """Parse a single SSE data line into a JSON event."""
    stripped = line.strip()
    if not stripped.startswith("data: "):
        return None
    payload = stripped[6:]
    if payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _extract_event_text(event: dict[str, object]) -> tuple[str, bool]:
    """Return text carried by a Codex SSE event and whether it is final."""
    event_type = str(event.get("type", ""))

    if event_type == "response.output_text.delta":
        delta = event.get("delta")
        if isinstance(delta, str) and delta:
            return delta, False
        if isinstance(delta, dict):
            return str(delta.get("text", "")), False

    if event_type == "response.output_text.done":
        text = event.get("text")
        if isinstance(text, str) and text:
            return text, True

    if event_type == "response.completed":
        response = event.get("response")
        if isinstance(response, dict):
            output = response.get("output")
        else:
            output = event.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if str(block.get("type", "")) == "output_text":
                        block_text = block.get("text")
                        if isinstance(block_text, str) and block_text:
                            parts.append(block_text)
            if parts:
                return "".join(parts), True

    return "", False


# ─── Public API: complete ───────────────────────────────────────────────────
async def complete(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: str | None = None,
    api_key: str | None = None,
    messages: list[dict[str, object]] | None = None,
    reasoning_effort: str | None = None,
    **kwargs: object,
) -> str:
    """Non-streaming completion via Codex endpoint."""
    cred = _parse_credential(api_key)
    cred = await _ensure_valid_credential(cred)
    effective_model = model or DEFAULT_MODEL

    body = _build_codex_body(
        model=effective_model,
        prompt=prompt,
        system_prompt=system_prompt,
        messages=messages,
        stream=True,  # We always stream and collect — Codex prefers streaming
        reasoning_effort=reasoning_effort,
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cred.access_token}",
        "openai-beta": "responses=v1",
    }

    timeout = aiohttp.ClientTimeout(total=120)
    full_text = ""

    async with aiohttp.ClientSession(**_session_kwargs(timeout)) as session:
        async with session.post(
            CODEX_API_ENDPOINT, headers=headers, json=body
        ) as resp:
            # Handle 401 with auto-refresh
            if resp.status == 401 and cred.refresh_token:
                cred = await _refresh_token(cred.refresh_token)
                headers["Authorization"] = f"Bearer {cred.access_token}"
                # Retry with new token
                async with session.post(
                    CODEX_API_ENDPOINT, headers=headers, json=body
                ) as retry_resp:
                    if retry_resp.status != 200:
                        error_body = await retry_resp.text()
                        raise LLMAPIError(
                            f"Codex API error ({retry_resp.status}): {error_body}",
                            status_code=retry_resp.status,
                            provider="openai_codex",
                        )
                    async for line in retry_resp.content:
                        event = _parse_sse_line(line.decode("utf-8"))
                        if not event:
                            continue
                        text, is_final = _extract_event_text(event)
                        if text:
                            full_text = text if is_final else f"{full_text}{text}"
                    return full_text

            if resp.status != 200:
                error_body = await resp.text()
                raise LLMAPIError(
                    f"Codex API error ({resp.status}): {error_body}",
                    status_code=resp.status,
                    provider="openai_codex",
                )

            async for line in resp.content:
                event = _parse_sse_line(line.decode("utf-8"))
                if not event:
                    continue
                text, is_final = _extract_event_text(event)
                if text:
                    full_text = text if is_final else f"{full_text}{text}"

    return full_text


# ─── Public API: stream ────────────────────────────────────────────────────
async def stream(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: str | None = None,
    api_key: str | None = None,
    messages: list[dict[str, object]] | None = None,
    reasoning_effort: str | None = None,
    **kwargs: object,
) -> AsyncGenerator[str, None]:
    """Streaming completion via Codex SSE endpoint. Yields text deltas."""
    cred = _parse_credential(api_key)
    cred = await _ensure_valid_credential(cred)
    effective_model = model or DEFAULT_MODEL

    body = _build_codex_body(
        model=effective_model,
        prompt=prompt,
        system_prompt=system_prompt,
        messages=messages,
        stream=True,
        reasoning_effort=reasoning_effort,
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cred.access_token}",
        "openai-beta": "responses=v1",
    }

    timeout = aiohttp.ClientTimeout(total=300)

    async with aiohttp.ClientSession(**_session_kwargs(timeout)) as session:
        async with session.post(
            CODEX_API_ENDPOINT, headers=headers, json=body
        ) as resp:
            # Handle 401 with auto-refresh
            if resp.status == 401 and cred.refresh_token:
                cred = await _refresh_token(cred.refresh_token)
                headers["Authorization"] = f"Bearer {cred.access_token}"
                async with session.post(
                    CODEX_API_ENDPOINT, headers=headers, json=body
                ) as retry_resp:
                    if retry_resp.status != 200:
                        error_body = await retry_resp.text()
                        raise LLMAPIError(
                            f"Codex API error ({retry_resp.status}): {error_body}",
                            status_code=retry_resp.status,
                            provider="openai_codex",
                        )
                    async for line in retry_resp.content:
                        event = _parse_sse_line(line.decode("utf-8"))
                        if not event:
                            continue
                        text, is_final = _extract_event_text(event)
                        if text:
                            yield text
                        if is_final:
                            return
                    return

            if resp.status != 200:
                error_body = await resp.text()
                raise LLMAPIError(
                    f"Codex API error ({resp.status}): {error_body}",
                    status_code=resp.status,
                    provider="openai_codex",
                )

            async for line in resp.content:
                event = _parse_sse_line(line.decode("utf-8"))
                if not event:
                    continue
                text, is_final = _extract_event_text(event)
                if text:
                    yield text
                if is_final:
                    return


__all__ = ["complete", "stream", "DEFAULT_MODEL"]
