"""Per-engine environment preflight checks.

Powers the "check whether this engine can run right now" affordance on each
engine's detail page. Every check is best-effort and never raises — a failed
import or missing config becomes a failed/optional check, not an exception.

A check is ``{key, label, ok, detail, optional}``. Overall ``ok`` is true when
every *required* (non-optional) check passes.
"""

from __future__ import annotations

from typing import Any

from .factory import (
    DEFAULT_PROVIDER,
    GRAPHRAG_PROVIDER,
    LIGHTRAG_PROVIDER,
    PAGEINDEX_PROVIDER,
    normalize_provider_name,
)


def _check(key: str, label: str, ok: bool, detail: str = "", *, optional: bool = False) -> dict:
    return {"key": key, "label": label, "ok": bool(ok), "detail": detail, "optional": optional}


def _active_chat_model() -> tuple[str | None, str]:
    """Return ``(model, binding)`` for the active chat LLM, or ``(None, "")``."""
    try:
        from deeptutor.services.config import resolve_llm_runtime_config

        cfg = resolve_llm_runtime_config()
        return getattr(cfg, "model", None), str(getattr(cfg, "binding", "") or "")
    except Exception:
        return None, ""


def _active_embedding() -> tuple[str | None, int]:
    """Return ``(model, dim)`` for the active embedding model, or ``(None, 0)``."""
    try:
        from deeptutor.services.embedding import get_embedding_config

        cfg = get_embedding_config()
        return getattr(cfg, "model", None), int(getattr(cfg, "dim", 0) or 0)
    except Exception:
        return None, 0


def _llamaindex_preflight() -> dict:
    emb_model, emb_dim = _active_embedding()
    checks = [
        _check(
            "embedding",
            "Active embedding model",
            bool(emb_model) and emb_dim > 0,
            f"{emb_model} · {emb_dim}d" if emb_model else "Configure one in the model catalog.",
        )
    ]
    try:
        from .pipelines.llamaindex.retrievers import _import_bm25_retriever

        bm25_ok = _import_bm25_retriever() is not None
    except Exception:
        bm25_ok = False
    checks.append(
        _check(
            "bm25",
            "BM25 hybrid retrieval",
            bm25_ok,
            "Installed." if bm25_ok else "Not installed — hybrid falls back to vector-only.",
            optional=True,
        )
    )
    return _finalize(checks)


def _pageindex_preflight() -> dict:
    try:
        from .pipelines.pageindex.config import DEFAULT_API_BASE_URL, get_pageindex_config

        cfg = get_pageindex_config(require_key=False)
        configured = bool(cfg.api_key)
        base = cfg.api_base_url or DEFAULT_API_BASE_URL
    except Exception:
        configured, base = False, ""
    return _finalize(
        [
            _check(
                "api_key",
                "API key configured",
                configured,
                base if configured else "Add a PageIndex API key under Credentials.",
            )
        ]
    )


def _graphrag_preflight() -> dict:
    try:
        from .pipelines.graphrag.config import is_graphrag_available

        installed = is_graphrag_available()
    except Exception:
        installed = False
    emb_model, emb_dim = _active_embedding()
    chat_model, _ = _active_chat_model()
    return _finalize(
        [
            _check(
                "package",
                "GraphRAG package installed",
                installed,
                "Installed." if installed else "pip install 'deeptutor[graphrag]'",
            ),
            _check(
                "chat",
                "Active chat model",
                bool(chat_model),
                chat_model or "Configure one in the model catalog.",
            ),
            _check(
                "embedding",
                "Active embedding model",
                bool(emb_model) and emb_dim > 0,
                f"{emb_model} · {emb_dim}d" if emb_model else "Configure one in the model catalog.",
            ),
        ]
    )


def _lightrag_preflight() -> dict:
    try:
        from .pipelines.lightrag.config import is_lightrag_available

        installed = is_lightrag_available()
    except Exception:
        installed = False
    emb_model, emb_dim = _active_embedding()
    chat_model, binding = _active_chat_model()
    vision_ok = False
    if chat_model:
        try:
            from deeptutor.services.llm.capabilities import supports_vision

            vision_ok = supports_vision(binding, chat_model)
        except Exception:
            vision_ok = False
    return _finalize(
        [
            _check(
                "package",
                "RAG-Anything package installed",
                installed,
                "Installed." if installed else "pip install 'deeptutor[rag-lightrag]'",
            ),
            _check(
                "chat",
                "Active chat model",
                bool(chat_model),
                chat_model or "Configure one in the model catalog.",
            ),
            _check(
                "embedding",
                "Active embedding model",
                bool(emb_model) and emb_dim > 0,
                f"{emb_model} · {emb_dim}d" if emb_model else "Configure one in the model catalog.",
            ),
            _check(
                "vision",
                "Vision model for multimodal",
                vision_ok,
                "Active chat model supports vision."
                if vision_ok
                else "Active chat model has no vision — multimodal documents fall back to text.",
                optional=True,
            ),
        ]
    )


def _finalize(checks: list[dict]) -> dict:
    ok = all(c["ok"] for c in checks if not c["optional"])
    return {"ok": ok, "checks": checks}


_PREFLIGHTS = {
    DEFAULT_PROVIDER: _llamaindex_preflight,
    PAGEINDEX_PROVIDER: _pageindex_preflight,
    GRAPHRAG_PROVIDER: _graphrag_preflight,
    LIGHTRAG_PROVIDER: _lightrag_preflight,
}


def engine_preflight(provider: str) -> dict[str, Any]:
    """Run the requirement checks for ``provider`` and return the report."""
    return _PREFLIGHTS[normalize_provider_name(provider)]()


__all__ = ["engine_preflight"]
