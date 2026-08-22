"""
Optional RAG lookup helper for block generators.

If the block context has a primary KB and ``rag_enabled``, run a single
``rag_search`` call and return both the synthesised text and a list of
``SourceAnchor`` objects. Failures are swallowed silently – RAG is treated as
"nice to have" by every generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from ..models import SourceAnchor

logger = logging.getLogger(__name__)


@dataclass
class RagLookup:
    text: str = ""
    anchors: list[SourceAnchor] = field(default_factory=list)
    used: bool = False


def _coerce_anchors(sources: list[dict] | None) -> list[SourceAnchor]:
    if not sources:
        return []
    anchors: list[SourceAnchor] = []
    for src in sources[:6]:
        if not isinstance(src, dict):
            continue
        ref = src.get("id") or src.get("doc_id") or src.get("path") or src.get("source") or ""
        snippet = src.get("text") or src.get("snippet") or src.get("content") or ""
        anchors.append(
            SourceAnchor(
                kind="kb",
                kb_name=str(src.get("kb_name") or src.get("kb") or "")[:120],
                ref=str(ref)[:200],
                snippet=str(snippet)[:300],
            )
        )
    return anchors


async def optional_rag_lookup(*, query: str, ctx) -> RagLookup:
    """Cheap, best-effort retrieval helper for block generators.

    Lookup order (BookEngine v2):

    1. Local exploration chunks attached to ``ctx`` (free, deterministic).
    2. Live ``rag_search`` against ``ctx.primary_kb`` (network round-trip).

    Returns an empty ``RagLookup`` if neither path produced anything; failures
    are swallowed silently because every generator treats RAG as optional.
    """
    if not query.strip():
        return RagLookup()

    # ── Step 1: try the cached exploration sweep first ───────────────
    local_chunks = []
    try:
        local_chunks = ctx.relevant_chunks(query, limit=4)
    except AttributeError:
        local_chunks = []
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"relevant_chunks failed: {exc}")
        local_chunks = []

    if local_chunks:
        text = "\n\n".join(
            f"- {(c.text or '').strip()}" for c in local_chunks if (c.text or "").strip()
        )
        anchors = [
            SourceAnchor(
                kind=c.source or "kb",
                kb_name=str(c.kb_name or ctx.primary_kb or "")[:120],
                ref=str(c.ref or c.chunk_id or "")[:200],
                snippet=str(c.text or "")[:300],
            )
            for c in local_chunks
            if (c.text or "").strip()
        ]
        if text or anchors:
            return RagLookup(text=text, anchors=anchors, used=True)

    # ── Step 2: fall back to a live RAG call ─────────────────────────
    if not ctx.rag_enabled or not ctx.primary_kb:
        return RagLookup()

    try:
        from deeptutor.multi_user.knowledge_access import resolve_kb
        from deeptutor.services.rag.factory import PAGEINDEX_OSS_PROVIDER, PAGEINDEX_PROVIDER
        from deeptutor.services.rag.provider_binding import resolve_bound_provider

        resource = resolve_kb(ctx.primary_kb, require_write=False)
        provider = resolve_bound_provider(str(resource.base_dir), resource.name)
        if provider in {PAGEINDEX_PROVIDER, PAGEINDEX_OSS_PROVIDER}:
            # PageIndex evidence is gathered once by SourceExplorer's own agent
            # loop and reused through relevant_chunks; never fall back to search().
            return RagLookup()
    except Exception:
        pass

    try:
        from deeptutor.tools.rag_tool import rag_search

        result = await rag_search(query=query, kb_name=ctx.primary_kb)
    except Exception as exc:
        logger.debug(f"RAG lookup skipped ({ctx.primary_kb}): {exc}")
        return RagLookup()

    if not isinstance(result, dict):
        return RagLookup()

    # RAGService reports failure in-band: it fills `answer` with an error
    # message ("RAG search failed.", "needs re-index", …) and flags it with
    # `error_type` / `needs_reindex`. Reading `answer` unconditionally fed that
    # message into the generator as if it were retrieved evidence, so a broken
    # index quietly became source material in the finished book.
    if result.get("error_type") or result.get("needs_reindex"):
        logger.debug(
            f"RAG lookup unusable ({ctx.primary_kb}): "
            f"error_type={result.get('error_type')!r} "
            f"needs_reindex={bool(result.get('needs_reindex'))}"
        )
        return RagLookup()

    answer = str(result.get("answer") or result.get("content") or "").strip()
    sources = result.get("sources")
    anchors = _coerce_anchors(sources if isinstance(sources, list) else None)
    for anchor in anchors:
        anchor.kb_name = anchor.kb_name or str(ctx.primary_kb or "")[:120]
    return RagLookup(
        text=answer,
        anchors=anchors,
        used=bool(answer or sources),
    )


__all__ = ["RagLookup", "optional_rag_lookup"]
