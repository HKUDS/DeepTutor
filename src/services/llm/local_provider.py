# -*- coding: utf-8 -*-
"""
Local LLM Provider
==================

Handles all local/self-hosted LLM calls (LM Studio, Ollama, vLLM, llama.cpp, etc.)
Uses aiohttp instead of httpx for better compatibility with local servers.

Key features:
- Uses aiohttp (httpx has known 502 issues with some local servers like LM Studio)
- Handles thinking tags (<think>) from reasoning models like Qwen
- Extended timeouts for potentially slower local inference
"""

import json
from typing import AsyncGenerator, Dict, List, Optional

import aiohttp

from .exceptions import LLMAPIError, LLMConfigError
from .utils import (
    build_auth_headers,
    build_chat_url,
    clean_thinking_tags,
    extract_response_content,
    sanitize_url,
)

# Extended timeout for local servers (may be slower than cloud)
DEFAULT_TIMEOUT = 300  # 5 minutes


async def complete(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    **kwargs,
) -> str:
    """
    Complete a prompt using local LLM server.

    Uses aiohttp for better compatibility with local servers.

    Args:
        prompt: The user prompt (ignored if messages provided)
        system_prompt: System prompt for context
        model: Model name
        api_key: API key (optional for most local servers)
        base_url: Base URL for the local server
        messages: Pre-built messages array (optional)
        **kwargs: Additional parameters (temperature, max_tokens, etc.)

    Returns:
        str: The LLM response
    """
    if not base_url:
        raise LLMConfigError("base_url is required for local LLM provider")

    # Sanitize URL and build chat endpoint
    base_url = sanitize_url(base_url, model or "")
    url = build_chat_url(base_url)

    # Build headers using unified utility
    headers = build_auth_headers(api_key)

    # Build messages
    if messages:
        msg_list = messages
    else:
        msg_list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

    # Build request data
    data = {
        "model": model or "default",
        "messages": msg_list,
        "temperature": kwargs.get("temperature", 0.7),
        "stream": False,
    }

    # Add optional parameters
    if kwargs.get("max_tokens"):
        data["max_tokens"] = kwargs["max_tokens"]

    timeout = aiohttp.ClientTimeout(total=kwargs.get("timeout", DEFAULT_TIMEOUT))

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=data, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise LLMAPIError(
                    f"Local LLM error: {error_text}",
                    status_code=response.status,
                    provider="local",
                )

            result = await response.json()

            if "choices" in result and result["choices"]:
                msg = result["choices"][0].get("message", {})
                # Use unified response extraction
                content = extract_response_content(msg)
                # Clean thinking tags using unified utility
                content = clean_thinking_tags(content)
                return content

            return ""


async def stream(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """
    Stream a response from local LLM server.

    Uses aiohttp for better compatibility with local servers.
    Falls back to non-streaming if streaming fails.

    Args:
        prompt: The user prompt (ignored if messages provided)
        system_prompt: System prompt for context
        model: Model name
        api_key: API key (optional for most local servers)
        base_url: Base URL for the local server
        messages: Pre-built messages array (optional)
        **kwargs: Additional parameters (temperature, max_tokens, etc.)

    Yields:
        str: Response chunks
    """
    if not base_url:
        raise LLMConfigError("base_url is required for local LLM provider")

    # Sanitize URL and build chat endpoint
    base_url = sanitize_url(base_url, model or "")
    url = build_chat_url(base_url)

    # Build headers using unified utility
    headers = build_auth_headers(api_key)

    # Build messages
    if messages:
        msg_list = messages
    else:
        msg_list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

    # Build request data
    data = {
        "model": model or "default",
        "messages": msg_list,
        "temperature": kwargs.get("temperature", 0.7),
        "stream": True,
    }

    if kwargs.get("max_tokens"):
        data["max_tokens"] = kwargs["max_tokens"]

    timeout = aiohttp.ClientTimeout(total=kwargs.get("timeout", DEFAULT_TIMEOUT))

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise LLMAPIError(
                        f"Local LLM stream error: {error_text}",
                        status_code=response.status,
                        provider="local",
                    )

                # Track if we're inside a thinking block
                in_thinking_block = False
                thinking_buffer = ""

                async for line in response.content:
                    line_str = line.decode("utf-8").strip()

                    # Skip empty lines
                    if not line_str:
                        continue

                    # Handle SSE format
                    if line_str.startswith("data:"):
                        data_str = line_str[5:].strip()

                        if data_str == "[DONE]":
                            break

                        try:
                            chunk_data = json.loads(data_str)
                            if "choices" in chunk_data and chunk_data["choices"]:
                                delta = chunk_data["choices"][0].get("delta", {})
                                content = delta.get("content")

                                if content:
                                    # Handle thinking tags in streaming
                                    if "<think>" in content:
                                        in_thinking_block = True
                                        thinking_buffer = content
                                        continue
                                    elif in_thinking_block:
                                        thinking_buffer += content
                                        if "</think>" in thinking_buffer:
                                            # End of thinking block, clean and yield
                                            cleaned = clean_thinking_tags(thinking_buffer)
                                            if cleaned:
                                                yield cleaned
                                            in_thinking_block = False
                                            thinking_buffer = ""
                                        continue
                                    else:
                                        yield content

                        except json.JSONDecodeError:
                            # Non-JSON response, might be raw text
                            if data_str and not data_str.startswith("{"):
                                yield data_str

                    # Some servers don't use SSE format
                    elif line_str.startswith("{"):
                        try:
                            chunk_data = json.loads(line_str)
                            if "choices" in chunk_data and chunk_data["choices"]:
                                delta = chunk_data["choices"][0].get("delta", {})
                                content = delta.get("content")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            pass

    except LLMAPIError:
        raise  # Re-raise LLM errors as-is
    except Exception as e:
        # Streaming failed, fall back to non-streaming
        print(f"⚠️ Streaming failed ({e}), falling back to non-streaming")

        try:
            content = await complete(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                api_key=api_key,
                base_url=base_url,
                messages=messages,
                **kwargs,
            )
            if content:
                yield content
        except Exception as e2:
            raise LLMAPIError(
                f"Local LLM failed: streaming={e}, non-streaming={e2}",
                provider="local",
            )


async def fetch_models(
    base_url: str,
    api_key: Optional[str] = None,
) -> List[str]:
    """
    Fetch available models from local LLM server.

    Supports:
    - Ollama (/api/tags)
    - OpenAI-compatible (/models)

    Args:
        base_url: Base URL for the local server
        api_key: API key (optional)

    Returns:
        List of available model names
    """
    base_url = base_url.rstrip("/")

    # Build headers using unified utility
    headers = build_auth_headers(api_key)
    # Remove Content-Type for GET request
    headers.pop("Content-Type", None)

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Try Ollama /api/tags first
        is_ollama = ":11434" in base_url or "ollama" in base_url.lower()
        if is_ollama:
            try:
                ollama_url = base_url.replace("/v1", "") + "/api/tags"
                async with session.get(ollama_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "models" in data:
                            return [m["name"] for m in data.get("models", [])]
            except Exception:
                pass

        # Try OpenAI-compatible /models
        try:
            models_url = f"{base_url}/models"
            async with session.get(models_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    # Handle different response formats
                    if "data" in data and isinstance(data["data"], list):
                        return [
                            m.get("id") or m.get("name")
                            for m in data["data"]
                            if m.get("id") or m.get("name")
                        ]
                    elif "models" in data and isinstance(data["models"], list):
                        if data["models"] and isinstance(data["models"][0], dict):
                            return [
                                m.get("id") or m.get("name")
                                for m in data["models"]
                                if m.get("id") or m.get("name")
                            ]
                        return [str(m) for m in data["models"]]
                    elif isinstance(data, list):
                        return [
                            m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
                            for m in data
                        ]
        except Exception as e:
            print(f"Error fetching models from {base_url}: {e}")

        return []


__all__ = [
    "complete",
    "stream",
    "fetch_models",
]
