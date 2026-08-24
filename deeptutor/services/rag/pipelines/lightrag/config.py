"""Bridge DeepTutor's runtime config into LightRAG / RAG-Anything.

LightRAG (HKUDS/LightRAG) is a text knowledge-graph RAG engine; its multimodal
story is RAG-Anything (HKUDS/RAG-Anything), built on top of LightRAG. The
``lightrag`` provider uses RAG-Anything so multimodal content (the parse layer's
``content_list``) becomes graph entities, while text-only documents fall back to
a plain text insert.

This module is the decoupling seam: it exposes availability + mode helpers and
builds the three adapters LightRAG needs from DeepTutor's already-resolved LLM /
embedding clients. It imports neither RAG-Anything nor LightRAG at module load —
the adapter builders import ``lightrag.utils`` lazily (only the embedding wrapper
needs it), and engine construction lives in ``engine.py``.

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

# Keep retries at the LightRAG adapter boundary so RAG-Anything receives one
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
    """Raised when the optional ``raganything`` dependency is not installed."""


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
    """True when RAG-Anything (which bundles LightRAG) can be imported.

    Opt-in extra: ``pip install 'deeptutor[rag-lightrag]'``. Until installed the
    provider is hidden / blocked in the UI.
    """
    return importlib.util.find_spec("raganything") is not None


def normalize_mode(mode: str | None) -> str:
    """Coerce a stored ``search_mode`` to a valid LightRAG query mode.

    The per-KB ``search_mode`` field is shared across engines; anything that
    isn't a LightRAG mode falls back to :data:`DEFAULT_MODE`.
    """
    candidate = (mode or "").strip().lower()
    return candidate if candidate in SUPPORTED_MODES else DEFAULT_MODE


def query_kwargs_from_settings() -> dict:
    """Extra ``aquery`` kwargs (top_k, response_type) from runtime settings.

    Returned as a dict so the engine can pass them through to LightRAG's
    ``QueryParam`` and gracefully drop them if an older RAG-Anything rejects a
    kwarg. Empty on any read error.
    """
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
    """``RAGAnythingConfig`` batch-processing knobs from runtime settings.

    Only ``max_concurrent_files`` is exposed for now (issue #640); the config
    object accepts several other batch/context knobs we deliberately leave on
    RAG-Anything's own defaults. Empty on any read error, so a bad settings
    file falls back to RAG-Anything's built-in default of 1.
    """
    try:
        from deeptutor.services.config import load_lightrag_settings

        settings = load_lightrag_settings()
        return {"max_concurrent_files": int(settings.get("max_concurrent_files", 1))}
    except Exception:
        return {}


def lightrag_kwargs_from_settings() -> dict:
    """Extra kwargs forwarded to LightRAG's own constructor via RAG-Anything's
    ``lightrag_kwargs`` passthrough.

    ``llm_model_max_async`` bounds how many concurrent LLM calls LightRAG's
    internal priority queue issues (covers both query and entity-extraction
    traffic, since both ride the same wrapped ``llm_model_func``).
    ``entity_extract_max_gleaning`` controls how many extra extraction passes
    LightRAG runs per chunk to recover entities/relations the first pass
    missed. Empty on any read error, so a bad settings file falls back to
    LightRAG's own built-in defaults.
    """
    try:
        from deeptutor.services.config import load_lightrag_settings

        settings = load_lightrag_settings()
        return {
            "llm_model_max_async": int(settings.get("llm_model_max_async", 4)),
            "entity_extract_max_gleaning": int(settings.get("entity_extract_max_gleaning", 1)),
        }
    except Exception:
        return {}


def build_llm_model_func(*, io_bridge: OwnerLoopBridge | None = None):
    """Wrap DeepTutor's unified LLM callable for LightRAG.

    Drops LightRAG's internal kwargs while preserving explicit ``messages``.
    """
    from deeptutor.services.llm import get_llm_client

    base = get_llm_client().get_model_func()

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


def build_vision_model_func(*, io_bridge: OwnerLoopBridge | None = None):
    """Wrap DeepTutor's vision-capable callable for RAG-Anything's image step."""
    from deeptutor.services.llm import get_llm_client

    base = get_llm_client().get_vision_model_func()

    async def vision_model_func(
        prompt="",
        system_prompt=None,
        history_messages=None,
        image_data=None,
        messages=None,
        **_ignored,
    ):
        async def request():
            return await base(
                prompt or "",
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                image_data=image_data,
                messages=messages,
                max_retries=0,
                # Never strip the image and answer anyway. The provider's
                # stage-2 fallback exists to salvage a text answer from a model
                # that turns out not to take images, but here the *whole point*
                # of the call is the image: a description produced without it is
                # invented, and it would be indexed as fact. Fail the image
                # instead, and let the caller log and skip it.
                allow_image_fallback=False,
            )

        return await _run_adapter_with_retry(request, io_bridge=io_bridge)

    return vision_model_func


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

        # No context means no role, which is what the pinned LightRAG always
        # passes — defaulting to "document" would label queries as passages.
        input_type = {
            "query": "search_query",
            "document": "search_document",
        }.get(str(context or "").strip().lower())

        async def request():
            return await client.embed(texts, input_type=input_type)

        vectors = await io_bridge.run(request) if io_bridge is not None else await request()
        return np.asarray(vectors, dtype=np.float32)

    return EmbeddingFunc(
        embedding_dim=dim,
        max_token_size=int(getattr(cfg, "max_tokens", 0) or _DEFAULT_MAX_TOKEN_SIZE),
        func=embedding_func,
    )


__all__ = [
    "SUPPORTED_MODES",
    "DEFAULT_MODE",
    "LightRagNotAvailableError",
    "LightRagNotConfiguredError",
    "is_lightrag_available",
    "normalize_mode",
    "query_kwargs_from_settings",
    "indexing_kwargs_from_settings",
    "lightrag_kwargs_from_settings",
    "build_llm_model_func",
    "build_vision_model_func",
    "build_embedding_func",
]
