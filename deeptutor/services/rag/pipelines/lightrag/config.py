"""Bridge DeepTutor runtime configuration into the LightRAG 1.5 native SDK.

This module is the decoupling seam: it exposes availability + mode helpers and
builds the three adapters LightRAG needs from DeepTutor's already-resolved LLM,
vision, and embedding clients. LightRAG imports remain lazy so every other RAG
provider can import without the optional extra installed.

Decoupling notes:
* ``llm_model_func`` / ``vision_model_func`` wrap DeepTutor's unified model
  callables and DROP LightRAG's internal kwargs (``hashing_kv``,
  ``keyword_extraction``, …) so they never leak into ``factory.complete``.
* ``embedding_func`` reuses DeepTutor's embedding client, wrapped in LightRAG's
  ``EmbeddingFunc`` with the active model's dimension.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import importlib.util
import inspect
import logging
import re
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .worker import OwnerLoopBridge

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# LightRAG's native retrieval modes. ``hybrid`` (KG + vector) is the safest
# general default and matches the shared per-KB ``search_mode`` default.
SUPPORTED_MODES = ("naive", "local", "global", "hybrid", "mix")
DEFAULT_MODE = "hybrid"

# Conservative cap for the embedding wrapper when the model doesn't advertise one.
_DEFAULT_MAX_TOKEN_SIZE = 8192

# Keep retries at the LightRAG adapter boundary so the SDK receives one
# predictable policy for both text and vision calls. Provider retries are disabled
# on every attempt to prevent the two retry layers from multiplying.
_ADAPTER_MAX_ATTEMPTS = 3
_ADAPTER_RETRY_DELAYS_SECONDS = (1.0, 2.0)
_ADAPTER_MAX_RETRY_DELAY_SECONDS = 60.0
_RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504, 529})
_HTTP_STATUS_PATTERN = re.compile(
    r"\b(?:http(?: status)?|status(?: code)?|error code)\s*[:=-]?\s*(\d{3})\b",
    re.I,
)


class LightRagNotAvailableError(RuntimeError):
    """Raised when the optional ``lightrag-hku`` dependency is not installed."""


class LightRagNotConfiguredError(RuntimeError):
    """Raised when DeepTutor's LLM / embedding config can't back LightRAG."""


def _http_status_code(exc: Exception) -> int | None:
    """Return a structured or safely normalized HTTP status for an LLM error."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        return status_code

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int) and not isinstance(response_status, bool):
        return response_status

    # The Codex provider currently returns a safe, normalized ``HTTP NNN``
    # message through LLMAPIError instead of preserving the status attribute.
    is_llm_api_error = any(cls.__name__ == "LLMAPIError" for cls in type(exc).__mro__)
    message = getattr(exc, "message", None)
    if is_llm_api_error and isinstance(message, str):
        match = _HTTP_STATUS_PATTERN.search(message)
        if match is not None:
            return int(match.group(1))
    return None


def _retry_classification(exc: Exception) -> tuple[bool, str]:
    """Classify retryability without inspecting or logging provider payloads."""
    from deeptutor.services.llm.request_compat import is_transient_transport_error

    status_code = _http_status_code(exc)
    if status_code is not None:
        return status_code in _RETRYABLE_HTTP_STATUS_CODES, f"http_{status_code}"
    if is_transient_transport_error(exc):
        return True, "transport"
    return False, "non_retryable"


def _retry_delay_seconds(exc: Exception, scheduled_delay: float) -> float:
    """Honor a safe Retry-After value without allowing unbounded sleeps."""
    from deeptutor.services.llm.error_mapping import retry_after_seconds

    requested_delay = retry_after_seconds(exc)
    if requested_delay is None:
        return scheduled_delay
    return min(requested_delay, _ADAPTER_MAX_RETRY_DELAY_SECONDS)


async def _run_adapter_with_retry(
    request: Callable[[], Awaitable[_T]],
    *,
    io_bridge: OwnerLoopBridge | None,
) -> _T:
    """Run one adapter request with bounded, non-multiplying retries."""
    for attempt in range(1, _ADAPTER_MAX_ATTEMPTS + 1):
        try:
            if io_bridge is not None:
                return await io_bridge.run(request)
            return await request()
        except Exception as exc:
            should_retry, status = _retry_classification(exc)
            if not should_retry or attempt == _ADAPTER_MAX_ATTEMPTS:
                raise
            logger.warning(
                "LightRAG adapter retry attempt=%d exception=%s status=%s",
                attempt,
                type(exc).__name__,
                status,
            )
            delay = _retry_delay_seconds(exc, _ADAPTER_RETRY_DELAYS_SECONDS[attempt - 1])
            await asyncio.sleep(delay)

    raise AssertionError("unreachable")


def is_lightrag_available() -> bool:
    """True when the native LightRAG SDK can be imported.

    Opt-in extra: ``pip install 'deeptutor[rag-lightrag]'``. Until installed the
    provider is hidden / blocked in the UI.
    """
    return importlib.util.find_spec("lightrag") is not None


def normalize_mode(mode: str | None) -> str:
    """Coerce a stored ``search_mode`` to a valid LightRAG query mode.

    The per-KB ``search_mode`` field is shared across engines; anything that
    isn't a LightRAG mode falls back to :data:`DEFAULT_MODE`.
    """
    candidate = (mode or "").strip().lower()
    return candidate if candidate in SUPPORTED_MODES else DEFAULT_MODE


def query_kwargs_from_settings() -> dict:
    """``QueryParam`` values from runtime settings."""
    try:
        from deeptutor.services.config import load_lightrag_settings

        settings = load_lightrag_settings()
        return {
            "top_k": int(settings.get("top_k", 60)),
            "response_type": str(settings.get("response_type") or "Multiple Paragraphs"),
        }
    except Exception:
        return {}


def indexing_kwargs_from_settings() -> dict:
    """Native parser-pool knobs from runtime settings."""
    try:
        from deeptutor.services.config import load_lightrag_settings

        settings = load_lightrag_settings()
        return {"max_parallel_parse_native": int(settings.get("max_concurrent_files", 1))}
    except Exception:
        return {}


def constructor_kwargs_from_settings() -> dict:
    """Direct LightRAG constructor knobs from runtime settings."""
    try:
        from deeptutor.services.config import load_lightrag_settings

        settings = load_lightrag_settings()
        return {
            "llm_model_max_async": int(settings.get("llm_model_max_async", 4)),
            "entity_extract_max_gleaning": int(settings.get("entity_extract_max_gleaning", 1)),
        }
    except Exception:
        return {}


def lightrag_llm_selection_from_settings() -> dict[str, str] | None:
    """Return a complete dedicated catalog reference, or use the active LLM."""
    try:
        from deeptutor.services.config import load_lightrag_settings

        settings = load_lightrag_settings()
        profile_id = str(settings.get("llm_profile_id") or "").strip()
        model_id = str(settings.get("llm_model_id") or "").strip()
        if not profile_id and not model_id:
            return None
        if not profile_id or not model_id:
            logger.warning("Ignoring incomplete LightRAG LLM selection; using the active model")
            return None
        return {"profile_id": profile_id, "model_id": model_id}
    except Exception:
        logger.warning(
            "Could not read LightRAG LLM selection; using the active model",
            exc_info=True,
        )
        return None


def _resolve_override_llm_config(selection: dict[str, str] | None):
    if selection is None:
        return None
    try:
        from deeptutor.services.model_selection.runtime import (
            resolve_llm_config_for_selection,
        )

        return resolve_llm_config_for_selection(selection)
    except ValueError:
        logger.warning(
            "LightRAG LLM selection %s no longer exists in the catalog; using the active model",
            selection,
        )
        return None


def build_llm_model_func(
    *,
    io_bridge: OwnerLoopBridge | None = None,
    llm_selection: dict[str, str] | None = None,
):
    """Wrap DeepTutor's unified LLM callable for LightRAG.

    Drops LightRAG's internal kwargs while preserving explicit ``messages``.
    """
    override = _resolve_override_llm_config(llm_selection)
    if override is None:
        from deeptutor.services.llm import get_llm_client

        base = get_llm_client().get_model_func()
    else:
        from deeptutor.services.llm.client import LLMClient

        base = LLMClient(config=override, configure_env=False).get_model_func()

    async def llm_model_func(
        prompt="",
        system_prompt=None,
        history_messages=None,
        messages=None,
        **_ignored,
    ):
        async def request():
            return await base(
                prompt or "",
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                messages=messages,
                max_retries=0,
                allow_image_fallback=False,
            )

        return await _run_adapter_with_retry(request, io_bridge=io_bridge)

    return llm_model_func


def build_vision_model_func(
    *,
    io_bridge: OwnerLoopBridge | None = None,
    llm_selection: dict[str, str] | None = None,
):
    """Map rc2 ``image_inputs`` to DeepTutor's vision callable."""
    override = _resolve_override_llm_config(llm_selection)
    if override is None:
        from deeptutor.services.llm import get_llm_client

        base = get_llm_client().get_vision_model_func()
    else:
        from deeptutor.services.llm.client import LLMClient

        base = LLMClient(config=override, configure_env=False).get_vision_model_func()

    async def vision_model_func(
        prompt="",
        system_prompt=None,
        history_messages=None,
        image_inputs=None,
        messages=None,
        **_ignored,
    ):
        if not isinstance(image_inputs, list) or len(image_inputs) != 1:
            raise ValueError("LightRAG vision requests must contain exactly one image input")
        payload = image_inputs[0]
        if not isinstance(payload, dict):
            raise ValueError("LightRAG vision image input must be an object")
        image_data = payload.get("base64")
        if not isinstance(image_data, str) or not image_data.strip():
            raise ValueError("LightRAG vision image input requires a non-empty base64 value")

        async def request():
            return await base(
                prompt or "",
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                image_data=image_data,
                messages=messages,
                max_retries=0,
                allow_image_fallback=False,
            )

        return await _run_adapter_with_retry(request, io_bridge=io_bridge)

    return vision_model_func


def vision_model_available() -> bool:
    """Return whether the active DeepTutor model is explicitly vision-capable."""
    try:
        from deeptutor.services.llm import get_llm_client

        return bool(get_llm_client().supports_multimodal_images())
    except Exception:
        return False


def build_embedding_func(*, io_bridge: OwnerLoopBridge | None = None):
    """Wrap DeepTutor's embedding client in LightRAG's ``EmbeddingFunc``."""
    from lightrag.utils import EmbeddingFunc

    from deeptutor.services.embedding import get_embedding_client, get_embedding_config

    cfg = get_embedding_config()
    dim = int(getattr(cfg, "dim", 0) or 0)
    if not dim:
        raise LightRagNotConfiguredError(
            "No active embedding model with a known dimension. Configure one under "
            "Settings → Catalog before using a LightRAG knowledge base."
        )

    client = get_embedding_client()

    async def embedding_func(texts, context=None, **_ignored):
        import numpy as np

        # No context means no role. Defaulting to "document" would label
        # queries as passages.
        input_type = {
            "query": "search_query",
            "document": "search_document",
        }.get(str(context or "").strip().lower())

        async def request():
            return await client.embed(texts, input_type=input_type)

        vectors = await io_bridge.run(request) if io_bridge is not None else await request()
        return np.asarray(vectors, dtype=np.float32)

    embedding_kwargs = {
        "embedding_dim": dim,
        "max_token_size": int(getattr(cfg, "max_tokens", 0) or _DEFAULT_MAX_TOKEN_SIZE),
        "func": embedding_func,
    }
    if "supports_asymmetric" in inspect.signature(EmbeddingFunc).parameters:
        embedding_kwargs["supports_asymmetric"] = True
    return EmbeddingFunc(**embedding_kwargs)


__all__ = [
    "SUPPORTED_MODES",
    "DEFAULT_MODE",
    "LightRagNotAvailableError",
    "LightRagNotConfiguredError",
    "is_lightrag_available",
    "normalize_mode",
    "query_kwargs_from_settings",
    "indexing_kwargs_from_settings",
    "constructor_kwargs_from_settings",
    "lightrag_llm_selection_from_settings",
    "build_llm_model_func",
    "build_vision_model_func",
    "vision_model_available",
    "build_embedding_func",
]
