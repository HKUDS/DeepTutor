"""Read-only provider connectivity and model discovery, without a model invocation."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import aiohttp

from deeptutor.services.llm.cloud_provider import _auth_binding, _get_aiohttp_connector
from deeptutor.services.llm.utils import build_auth_headers, collect_model_names


def detect_capabilities(items: list) -> list[dict]:
    """Only explicit metadata establishes support. Model names are not proof."""
    detected = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        methods = item.get(
            "supportedGenerationMethods", item.get("supported_generation_methods", [])
        )
        architecture = item.get("architecture") or {}
        if not isinstance(architecture, dict):
            architecture = {}

        def values(value):
            return value if isinstance(value, list) else []

        input_values = [
            *values(architecture.get("input_modalities")),
            *values(item.get("input_modalities")),
        ]
        output_values = [
            *values(architecture.get("output_modalities")),
            *values(item.get("output_modalities")),
        ]
        inputs = {str(value).lower() for value in input_values}
        outputs = {str(value).lower() for value in output_values}
        if isinstance(methods, list):
            if any(
                method in {"generateContent", "generateMessage", "chat", "completion"}
                for method in methods
            ):
                detected.add("llm")
            if any(
                method in {"embedContent", "batchEmbedContents", "embedText", "embedding"}
                for method in methods
            ):
                detected.add("embedding")
        # Understanding an image/video is not evidence of generating one.
        # Audio input/output is reported separately from visual generation.
        if "audio" in inputs | outputs:
            detected.add("voice")
        if outputs & {"image", "video"}:
            detected.add("generation")
        if "text" in outputs and item.get("type") != "embedding":
            detected.add("llm")
        if item.get("type") == "embedding":
            detected.add("embedding")
    return [{"category": category, "evidence": "metadata"} for category in sorted(detected)]


def test_search_access(
    binding: str, base_url: str, api_key: str | None, *, proxy: str = "", max_results: int = 1
):
    """Test exactly one search adapter, never a fallback or live credentials."""
    from deeptutor.services.config.provider_runtime import (
        search_missing_credential,
        search_provider_spec,
    )
    from deeptutor.services.search.providers import get_provider

    spec = search_provider_spec(binding)
    if not spec or binding == "none":
        raise ValueError("Choose a supported search provider.")
    missing = search_missing_credential(binding, api_key or "", base_url)
    if missing:
        raise ValueError(f"Search provider requires {missing}.")
    kwargs = {"api_key": api_key or "", "base_url": base_url, "max_results": max_results}
    if proxy:
        kwargs["proxy"] = proxy
    response = get_provider(binding, **kwargs).search(
        "DeepTutor configuration health check", **kwargs
    )
    if not (response.answer or response.search_results):
        raise ValueError("Search provider returned no answer or results.")
    return response


async def probe_search_provider(binding: str, base_url: str, api_key: str | None) -> dict:
    from deeptutor.services.config.provider_runtime import search_missing_credential

    if search_missing_credential(binding, api_key or "", base_url):
        return {"status": "auth_error", "models": []}
    try:
        await asyncio.wait_for(
            asyncio.to_thread(test_search_access, binding, base_url, api_key), timeout=25
        )
        return {
            "status": "connected",
            "models": [],
            "capabilities": [{"category": "search", "evidence": "metadata"}],
        }
    except TimeoutError:
        return {"status": "timeout", "models": []}
    except Exception:
        # No upstream exception text: it may contain the submitted key.
        return {"status": "http_error", "models": []}


async def probe_provider(
    binding: str,
    base_url: str,
    api_key: str | None = None,
    api_format: str = "auto",
    extra_headers: dict[str, str] | None = None,
    api_version: str = "",
) -> dict:
    """A successful, recognized listing verifies access to that endpoint only.

    Unsupported discovery never implies valid credentials. Errors are intentionally
    structured: upstream bodies/exception strings can contain credentials or URLs.
    No configuration writes or billable inference calls are made here.
    """
    if binding == "volcengine_speech":
        return {"status": "unavailable", "models": []}
    base_url = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(base_url)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username
        # Accessing .port validates malformed/non-numeric ports as well.
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        return {"status": "invalid_url", "models": []}
    # Other services store the full inference endpoint. Discovery lives beside it.
    for suffix in (
        "/embeddings",
        "/audio/speech",
        "/audio/transcriptions",
        "/images/generations",
        "/videos/generations",
        "/chat/completions",
        "/responses",
        "/messages",
        "/api/embed",
        "/api/embeddings",
    ):
        if base_url.endswith(suffix):
            base_url = base_url.removesuffix(suffix)
            break
    headers = build_auth_headers(api_key, _auth_binding(binding, api_format))
    headers.pop("Content-Type", None)
    headers.update(extra_headers or {})
    url = f"{base_url}/models"
    params = (
        {"api-version": api_version}
        if api_version and binding in {"azure", "azure_openai"}
        else None
    )
    if binding == "ollama":
        url = f"{base_url.removesuffix('/v1')}/api/tags"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            connector=_get_aiohttp_connector(),
            trust_env=True,
        ) as session:
            # Do not forward custom credentials to another host on a redirect.
            async with session.get(
                url, headers=headers, params=params, allow_redirects=False
            ) as response:
                if response.status in {401, 403}:
                    return {"status": "auth_error", "models": [], "http_status": response.status}
                if response.status in {404, 405, 501}:
                    return {"status": "unavailable", "models": [], "http_status": response.status}
                if response.status == 429:
                    return {"status": "rate_limited", "models": [], "http_status": 429}
                if response.status != 200:
                    return {"status": "http_error", "models": [], "http_status": response.status}
                try:
                    payload = await response.json()
                except (ValueError, aiohttp.ContentTypeError):
                    return {"status": "unavailable", "models": []}
                items = (
                    payload
                    if isinstance(payload, list)
                    else (
                        payload.get("data", payload.get("models"))
                        if isinstance(payload, dict)
                        else None
                    )
                )
                if not isinstance(items, list):
                    return {"status": "unavailable", "models": []}
                models = list(dict.fromkeys(collect_model_names(items)))
                if items and not models:
                    return {"status": "unavailable", "models": []}
                result = {"status": "connected", "models": [{"id": model} for model in models]}
                capabilities = detect_capabilities(items)
                if capabilities:
                    result["capabilities"] = capabilities
                return result
    except (asyncio.TimeoutError, TimeoutError):
        return {"status": "timeout", "models": []}
    except (aiohttp.ClientError, ValueError, OSError):
        return {"status": "unreachable", "models": []}
