"""Read-only provider connectivity and model discovery, without a model invocation."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import requests

from deeptutor.services.llm.cloud_provider import _auth_binding, _get_aiohttp_connector
from deeptutor.services.llm.utils import build_auth_headers, collect_model_names


def model_services(item: dict) -> list[str]:
    """Classify explicit metadata, never a model name or a vision input alone.

    Sources: OpenRouter /models architecture; Aliyun /api/v1/models capabilities.
    This describes model types, not protocol compatibility or account access.
    """
    detected = set()

    def values(value):
        return value if isinstance(value, list) else []

    architecture = item.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    metadata = item.get("inference_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    outputs = {
        str(value).lower()
        for value in [
            *values(architecture.get("output_modalities")),
            *values(item.get("output_modalities")),
            *values(metadata.get("response_modality")),
        ]
    }
    methods = values(
        item.get("supportedGenerationMethods", item.get("supported_generation_methods"))
    )
    kinds = set(str(value) for value in values(item.get("capabilities")))
    if any(
        isinstance(method, str)
        and method in {"generateContent", "generateMessage", "chat", "completion"}
        for method in methods
    ) or kinds & {"TG", "Reasoning"}:
        detected.add("llm")
    if (
        any(
            isinstance(method, str)
            and method in {"embedContent", "batchEmbedContents", "embedText", "embedding"}
            for method in methods
        )
        or item.get("type") == "embedding"
        or "embeddings" in outputs
        or kinds & {"ME", "TR"}
    ):
        detected.add("embedding")
    if "text" in outputs and "embedding" not in detected and not kinds & {"ASR", "Realtime-ASR"}:
        detected.add("llm")
    if "audio" in outputs or kinds & {"TTS", "Realtime-Text-to-Speech"}:
        detected.add("tts")
    # Audio understanding does not establish a transcription endpoint.
    if kinds & {"ASR", "Realtime-ASR"} or item.get("type") in ("transcription", "speech-to-text"):
        detected.add("stt")
    if "image" in outputs or "IG" in kinds:
        detected.add("imagegen")
    if "video" in outputs or "VG" in kinds:
        detected.add("videogen")
    return sorted(detected)


def detect_capabilities(items: list) -> list[dict]:
    detected = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        services = model_services(item)
        detected.update(services)
        if {"tts", "stt"} & set(services):
            detected.add("voice")
        if {"imagegen", "videogen"} & set(services):
            detected.add("generation")
    return [{"category": category, "evidence": "metadata"} for category in sorted(detected)]


def discovery_request(binding: str, base_url: str, api_version: str = "") -> tuple[str, dict]:
    """Use vendor metadata on the configured host only; never infer another region."""
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    params: dict[str, str | int] = (
        {"api-version": api_version} if api_version and binding in {"azure", "azure_openai"} else {}
    )
    if binding == "ollama":
        path = path.removesuffix("/v1") + "/api/tags"
    elif binding == "dashscope" and (parsed.hostname or "").endswith(".aliyuncs.com"):
        # The official native catalog includes capability metadata and pagination.
        path = path.replace("/compatible-mode/v1", "/api/v1")
        if "/services/" in path:
            path = path.split("/services/", 1)[0]
        path += "/models"
        params = {"page_no": 1, "page_size": 100}
    else:
        path += "/models"
        if binding == "openrouter":
            params["output_modalities"] = "all"
    return urlunsplit(parsed._replace(path=path, query="", fragment="")), params


def test_search_access(
    binding: str,
    base_url: str,
    api_key: str | None,
    *,
    proxy: str = "",
    max_results: int = 1,
    require_results: bool = True,
    query: str = "DeepTutor configuration health check",
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
    response = get_provider(binding, **kwargs).search(query, **kwargs)
    if require_results and not (response.answer or response.search_results):
        raise ValueError("Search provider returned no answer or results.")
    return response


async def probe_search_provider(
    binding: str, base_url: str, api_key: str | None, *, proxy: str = ""
) -> dict:
    from deeptutor.services.config.provider_runtime import search_missing_credential
    from deeptutor.services.search.providers.searxng import SearxngResponseError

    missing = search_missing_credential(binding, api_key or "", base_url)
    if missing:
        return {"status": "invalid_url" if missing == "base_url" else "auth_error", "models": []}
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                test_search_access, binding, base_url, api_key, proxy=proxy, require_results=False
            ),
            timeout=25,
        )
        result = {
            "status": "connected",
            "models": [],
            "capabilities": [{"category": "search", "evidence": "metadata"}],
        }
        if not (response.answer or response.search_results):
            result["warning"] = "empty_results"
        return result
    except (TimeoutError, requests.Timeout):
        return {"status": "timeout", "models": []}
    except requests.ConnectionError:
        return {"status": "unreachable", "models": []}
    except (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema):
        return {"status": "invalid_url", "models": []}
    except SearxngResponseError:
        return {"status": "invalid_response", "models": []}
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        category = (
            "json_forbidden"
            if binding == "searxng" and status == 403
            else "auth_error"
            if status in {401, 403}
            else "rate_limited"
            if status == 429
            else "http_error"
        )
        return {"status": category, "models": [], "http_status": status}
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
    url, params = discovery_request(binding, base_url, api_version)
    try:
        async with (
            asyncio.timeout(30),
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20),
                connector=_get_aiohttp_connector(),
                trust_env=True,
            ) as session,
        ):
            all_items = []
            seen = set()
            warning = None
            for _page in range(30):
                async with session.get(
                    url, headers=headers, params=dict(params) or None, allow_redirects=False
                ) as response:
                    if response.status in {401, 403}:
                        return {
                            "status": "auth_error",
                            "models": [],
                            "http_status": response.status,
                        }
                    if response.status in {404, 405, 501}:
                        return {
                            "status": "unavailable",
                            "models": [],
                            "http_status": response.status,
                        }
                    if response.status == 429:
                        return {"status": "rate_limited", "models": [], "http_status": 429}
                    if response.status != 200:
                        return {
                            "status": "http_error",
                            "models": [],
                            "http_status": response.status,
                        }
                    try:
                        payload = await response.json()
                    except (ValueError, aiohttp.ContentTypeError):
                        return {"status": "unavailable", "models": []}
                    output = payload.get("output") if isinstance(payload, dict) else None
                    native = isinstance(output, dict) and isinstance(output.get("models"), list)
                    items = (
                        output["models"]
                        if native
                        else (
                            payload
                            if isinstance(payload, list)
                            else payload.get("data", payload.get("models"))
                            if isinstance(payload, dict)
                            else None
                        )
                    )
                    if not isinstance(items, list) or (
                        isinstance(payload, dict) and payload.get("success") is False
                    ):
                        return {"status": "unavailable", "models": []}
                    normalized = [
                        {**item, "id": item.get("id") or item.get("model")}
                        if isinstance(item, dict)
                        else item
                        for item in items
                    ]
                    names = list(dict.fromkeys(collect_model_names(normalized)))
                    if items and not names:
                        return {"status": "unavailable", "models": []}
                    if items and all(name in seen for name in names):
                        warning = "partial_models"
                        break
                    all_items.extend(normalized)
                    seen.update(names)
                    if native:
                        total = output.get("total")
                        if not isinstance(total, (int, float)) or len(seen) >= total or not items:
                            break
                        params["page_no"] = (
                            int(output.get("page_no") or params.get("page_no", 1)) + 1
                        )
                    elif isinstance(payload, dict) and payload.get("has_more"):
                        cursor = payload.get("last_id")
                        if (
                            not isinstance(cursor, str)
                            or not cursor
                            or params.get("after_id") == cursor
                        ):
                            warning = "partial_models"
                            break
                        params["after_id"] = cursor
                    else:
                        break
            else:
                warning = "partial_models"
            models = {}
            for item in all_items:
                names = collect_model_names([item])
                for name in names:
                    entry: dict[str, Any] = {"id": name}
                    kinds = model_services(item) if isinstance(item, dict) else []
                    if kinds:
                        entry["services"] = kinds
                    models[name] = entry
            result = {"status": "connected", "models": list(models.values())}
            capabilities = detect_capabilities(all_items)
            if capabilities:
                result["capabilities"] = capabilities
            if warning:
                result["warning"] = warning
            return result
    except (asyncio.TimeoutError, TimeoutError):
        return {"status": "timeout", "models": []}
    except (aiohttp.ClientError, ValueError, OSError):
        return {"status": "unreachable", "models": []}
