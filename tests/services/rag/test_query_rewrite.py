"""Tests for the RAG query rewrite layer (``deeptutor.services.rag.query_rewrite``)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from deeptutor.services.rag.query_rewrite import (
    STRATEGY_OFF,
    STRATEGY_STANDALONE,
    RewriteOutcome,
    maybe_rewrite,
    rewrite_query,
)


def _ok_complete(text: str = "rewritten keywords") -> Callable[..., Awaitable[str]]:
    async def _fn(query: str, system_prompt: str | None = None, model: str | None = None) -> str:
        return text

    return _fn


def _fail_complete() -> Callable[..., Awaitable[str]]:
    async def _fn(query: str, system_prompt: str | None = None, model: str | None = None) -> str:
        raise RuntimeError("LLM down")

    return _fn


def _slow_complete() -> Callable[..., Awaitable[str]]:
    async def _fn(query: str, system_prompt: str | None = None, model: str | None = None) -> str:
        await asyncio.sleep(10)
        return "too late"

    return _fn


def _enabled_settings(**overrides) -> dict:
    base = {
        "enabled": True,
        "strategy": STRATEGY_STANDALONE,
        "min_query_chars": 1,
        "timeout_seconds": 5,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# rewrite_query — the single-strategy core (always returns an outcome)
# --------------------------------------------------------------------------- #


def test_rewrite_query_success_strips_and_records_metadata():
    """A successful rewrite strips quotes/whitespace and records provenance."""
    out = asyncio.run(
        rewrite_query(
            "what is x",
            settings=_enabled_settings(model="gpt-4o-mini"),
            complete_fn=_ok_complete('  "clean query"  '),
        )
    )
    assert isinstance(out, RewriteOutcome)
    assert out.original == "what is x"
    assert out.rewritten == "clean query"
    assert out.strategy == STRATEGY_STANDALONE
    assert out.error == ""
    assert out.latency_ms >= 0
    assert out.applied is True


def test_rewrite_query_disabled_returns_off_outcome():
    """enabled=False short-circuits with an 'off' outcome, no LLM call."""
    called = {"n": 0}

    async def _fn(query, system_prompt=None, model=None):
        called["n"] += 1
        return "x"

    out = asyncio.run(
        rewrite_query(
            "what is x",
            settings=_enabled_settings(enabled=False),
            complete_fn=_fn,
        )
    )
    assert out.strategy == STRATEGY_OFF
    assert out.rewritten == "what is x"
    assert out.applied is False
    assert called["n"] == 0


def test_rewrite_query_strategy_off_skips_llm():
    """strategy='off' behaves like disabled even if enabled=True."""
    out = asyncio.run(
        rewrite_query(
            "what is x",
            settings=_enabled_settings(strategy=STRATEGY_OFF),
            complete_fn=_ok_complete(),
        )
    )
    assert out.strategy == STRATEGY_OFF
    assert out.rewritten == "what is x"


def test_rewrite_query_short_query_skips():
    """Queries under min_query_chars are passed through untouched."""
    out = asyncio.run(
        rewrite_query(
            "hi",
            settings=_enabled_settings(min_query_chars=12),
            complete_fn=_ok_complete(),
        )
    )
    assert out.rewritten == "hi"
    assert out.strategy == STRATEGY_STANDALONE
    assert out.applied is False


def test_rewrite_query_exception_falls_back_with_error():
    """An LLM exception keeps the original query and records the error."""
    out = asyncio.run(
        rewrite_query(
            "what is x",
            settings=_enabled_settings(),
            complete_fn=_fail_complete(),
        )
    )
    assert out.rewritten == "what is x"
    assert out.applied is False
    assert out.error != ""


def test_rewrite_query_timeout_falls_back():
    """A slow LLM is cut off by the timeout and falls back to the original."""
    out = asyncio.run(
        rewrite_query(
            "what is x",
            settings=_enabled_settings(timeout_seconds=0.1),
            complete_fn=_slow_complete(),
        )
    )
    assert out.rewritten == "what is x"
    assert out.error != ""


def test_rewrite_query_empty_output_falls_back():
    """Whitespace-only LLM output is treated as a failure (empty_rewrite)."""
    out = asyncio.run(
        rewrite_query(
            "what is x",
            settings=_enabled_settings(),
            complete_fn=_ok_complete("   \n  "),
        )
    )
    assert out.rewritten == "what is x"
    assert out.error == "empty_rewrite"


def test_rewrite_query_passes_system_prompt_and_model():
    """The LLM is called with the system prompt and configured model."""
    seen = {}

    async def _fn(query, system_prompt=None, model=None):
        seen["query"] = query
        seen["system_prompt"] = system_prompt
        seen["model"] = model
        return "rewritten"

    asyncio.run(
        rewrite_query(
            "what is x",
            settings=_enabled_settings(model="gpt-4o-mini"),
            complete_fn=_fn,
        )
    )
    assert seen["query"] == "what is x"
    assert seen["system_prompt"] and "self-contained" in seen["system_prompt"]
    assert seen["model"] == "gpt-4o-mini"


# --------------------------------------------------------------------------- #
# maybe_rewrite — the settings/call-override gate used by RAGService.search
# --------------------------------------------------------------------------- #


def test_maybe_rewrite_off_returns_original_and_none():
    """rewrite=False is an explicit override: original query, no outcome."""
    q, out = asyncio.run(
        maybe_rewrite(
            "what is x",
            rewrite=False,
            settings=_enabled_settings(),
            complete_fn=_ok_complete(),
        )
    )
    assert q == "what is x"
    assert out is None


def test_maybe_rewrite_none_disabled_settings_skips():
    """rewrite=None with enabled=False follows settings: skipped, outcome None."""
    q, out = asyncio.run(
        maybe_rewrite(
            "what is x",
            rewrite=None,
            settings=_enabled_settings(enabled=False),
            complete_fn=_ok_complete(),
        )
    )
    assert q == "what is x"
    assert out is None


def test_maybe_rewrite_none_enabled_settings_rewrites():
    """rewrite=None with enabled=True follows settings: query is rewritten."""
    q, out = asyncio.run(
        maybe_rewrite(
            "what is x",
            rewrite=None,
            settings=_enabled_settings(),
            complete_fn=_ok_complete(),
        )
    )
    assert q == "rewritten keywords"
    assert out is not None
    assert out.rewritten == "rewritten keywords"
    assert out.applied is True


def test_maybe_rewrite_true_overrides_disabled_settings():
    """rewrite=True forces the rewrite on even when settings say disabled."""
    q, out = asyncio.run(
        maybe_rewrite(
            "what is x",
            rewrite=True,
            settings=_enabled_settings(enabled=False),
            complete_fn=_ok_complete(),
        )
    )
    assert q == "rewritten keywords"
    assert out is not None


def test_maybe_rewrite_false_overrides_enabled_settings():
    """rewrite=False forces the rewrite off even when settings say enabled."""
    q, out = asyncio.run(
        maybe_rewrite(
            "what is x",
            rewrite=False,
            settings=_enabled_settings(enabled=True),
            complete_fn=_ok_complete(),
        )
    )
    assert q == "what is x"
    assert out is None


def test_maybe_rewrite_short_query_skips():
    """Short queries pass through: query unchanged, outcome records no-op.

    When the layer is on but the query is under ``min_query_chars``, the query
    is returned unchanged and a provenance outcome with ``applied=False`` is
    still attached (so callers can see the rewrite was considered).
    """
    q, out = asyncio.run(
        maybe_rewrite(
            "hi",
            rewrite=True,
            settings=_enabled_settings(min_query_chars=12),
            complete_fn=_ok_complete(),
        )
    )
    assert q == "hi"
    assert out is not None
    assert out.rewritten == "hi"
    assert out.applied is False


def test_maybe_rewrite_failure_still_returns_original_with_outcome():
    """On LLM failure the original query is kept but provenance is recorded."""
    q, out = asyncio.run(
        maybe_rewrite(
            "what is x",
            rewrite=True,
            settings=_enabled_settings(),
            complete_fn=_fail_complete(),
        )
    )
    assert q == "what is x"
    assert out is not None
    assert out.rewritten == "what is x"
    assert out.error != ""
    assert out.applied is False


@pytest.mark.asyncio
async def test_per_call_enable_preserves_runtime_rewrite_configuration(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deeptutor.services import config
    from deeptutor.services.rag import query_rewrite

    settings = _enabled_settings(
        enabled=False, model="configured-rewrite-model", min_query_chars=20, timeout_seconds=0.25
    )
    monkeypatch.setattr(
        config,
        "get_runtime_settings_service",
        lambda: SimpleNamespace(load_query_rewrite=lambda: settings),
    )
    complete = AsyncMock(return_value="resolved search terms")
    wait_for = AsyncMock(wraps=asyncio.wait_for)
    monkeypatch.setattr(query_rewrite.asyncio, "wait_for", wait_for)

    query, outcome = await maybe_rewrite("short", rewrite=True, complete_fn=complete)
    assert query == "short" and outcome is not None
    complete.assert_not_awaited()
    query, outcome = await maybe_rewrite(
        "explain the previous chapter's main result", rewrite=True, complete_fn=complete
    )
    assert query == "resolved search terms" and outcome.applied
    assert complete.await_args.kwargs["model"] == "configured-rewrite-model"
    assert wait_for.await_args.kwargs["timeout"] == 0.25
    assert settings["enabled"] is False
