"""Single-query rewrite for retrieval.

Rewrites a conversational or anaphoric user query into one self-contained,
keyword-leaning search query before it reaches the KB pipeline. The layer is
fail-open by design: any LLM error, timeout, or empty output falls back to
the original query so retrieval never fails because of a rewrite.

Only the ``standalone`` strategy exists in v1 (one LLM call, one query).
``multi_query`` is reserved for a follow-up PR; the settings schema already
carries the ``strategy`` field so no migration is needed later.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import time
from typing import Any, Optional

#: Rewrite is disabled / was forced off.
STRATEGY_OFF = "off"
#: Single self-contained query produced by one LLM call.
STRATEGY_STANDALONE = "standalone"

#: Strategies ``maybe_rewrite`` accepts (``off`` forces the pass-through).
KNOWN_STRATEGIES = (STRATEGY_OFF, STRATEGY_STANDALONE)

_SYSTEM_PROMPT = (
    "You rewrite a user question into a single self-contained search query "
    "for a document retrieval engine. Keep the original language (never "
    "translate). Resolve pronouns and conversational context into explicit "
    "keywords. Output ONLY the rewritten query, no quotes, no explanation."
)


@dataclass(frozen=True)
class RewriteOutcome:
    """What the rewrite layer did to one query."""

    original: str
    rewritten: str
    strategy: str
    latency_ms: float = 0.0
    error: str = ""

    @property
    def applied(self) -> bool:
        """True when the query sent to the engine differs from the input."""
        return bool(self.rewritten) and self.rewritten != self.original

    def to_dict(self) -> dict[str, Any]:
        """Serializable form attached to search results and eval reports."""
        return {
            "original": self.original,
            "rewritten": self.rewritten,
            "strategy": self.strategy,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }


def _clean_rewritten(raw: str) -> str:
    """Take the first non-empty line of LLM output, minus wrapping quotes."""
    for line in (raw or "").splitlines():
        text = line.strip().strip("\"'“”‘’")
        if text:
            return text
    return ""


async def rewrite_query(
    query: str,
    *,
    settings: dict[str, Any] | None = None,
    complete_fn: Callable[..., Awaitable[str]] | None = None,
) -> RewriteOutcome:
    """Rewrite ``query`` per ``settings``; always fail open to the original."""
    original = query if isinstance(query, str) else ""
    cfg = settings or {}
    strategy = str(cfg.get("strategy") or STRATEGY_STANDALONE)
    if not bool(cfg.get("enabled", False)) or strategy == STRATEGY_OFF:
        return RewriteOutcome(original=original, rewritten=original, strategy=STRATEGY_OFF)

    min_chars = int(cfg.get("min_query_chars") or 0)
    if len(original.strip()) < max(0, min_chars):
        return RewriteOutcome(original=original, rewritten=original, strategy=strategy)

    timeout = float(cfg.get("timeout_seconds") or 5.0)
    model = str(cfg.get("model") or "").strip() or None

    started = time.monotonic()
    try:
        complete = complete_fn
        if complete is None:
            from deeptutor.services.llm import complete as _default_complete

            complete = _default_complete
        if model is not None:
            raw = await asyncio.wait_for(
                complete(query, system_prompt=_SYSTEM_PROMPT, model=model),
                timeout=timeout,
            )
        else:
            raw = await asyncio.wait_for(
                complete(query, system_prompt=_SYSTEM_PROMPT),
                timeout=timeout,
            )
    except Exception as exc:
        return RewriteOutcome(
            original=original,
            rewritten=original,
            strategy=strategy,
            latency_ms=(time.monotonic() - started) * 1000.0,
            error=f"{type(exc).__name__}: {exc}",
        )

    latency_ms = (time.monotonic() - started) * 1000.0
    rewritten = _clean_rewritten(raw)
    if not rewritten:
        return RewriteOutcome(
            original=original,
            rewritten=original,
            strategy=strategy,
            latency_ms=latency_ms,
            error="empty_rewrite",
        )
    return RewriteOutcome(
        original=original,
        rewritten=rewritten,
        strategy=strategy,
        latency_ms=latency_ms,
    )


async def maybe_rewrite(
    query: str,
    *,
    rewrite: bool | None = None,
    settings: dict[str, Any] | None = None,
    complete_fn: Callable[..., Awaitable[str]] | None = None,
) -> tuple[str, Optional[RewriteOutcome]]:
    """Return ``(effective_query, outcome)`` for :meth:`RAGService.search`.

    ``rewrite`` is the per-call override: True forces the rewrite on, False
    forces it off, None follows the runtime settings. Returns ``(query, None)``
    when the layer is off so callers only attach provenance when active.
    """
    cfg = settings
    if cfg is None:
        from deeptutor.services.config import get_runtime_settings_service

        cfg = get_runtime_settings_service().load_query_rewrite()
    cfg = dict(cfg)
    if rewrite is not None:
        cfg["enabled"] = bool(rewrite)

    if not bool(cfg.get("enabled", False)):
        return query, None
    outcome = await rewrite_query(query, settings=cfg, complete_fn=complete_fn)
    return outcome.rewritten, outcome


__all__ = [
    "KNOWN_STRATEGIES",
    "STRATEGY_OFF",
    "STRATEGY_STANDALONE",
    "RewriteOutcome",
    "maybe_rewrite",
    "rewrite_query",
]
