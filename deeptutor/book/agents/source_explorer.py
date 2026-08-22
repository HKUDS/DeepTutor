"""
SourceExplorer
==============

Stage 2 prep of the BookEngine pipeline.

Given the user's confirmed ``BookProposal`` plus the four-source ``BookInputs``
snapshot, ``SourceExplorer`` performs a *parallel multi-query sweep* over the
attached knowledge bases and additional sources (notebook records, recent chat
history, quiz entries) to produce an ``ExplorationReport``.

The report drives every subsequent stage of the pipeline:

- ``SpineSynthesizer`` reads ``summary`` + ``candidate_concepts`` to draft an
  evidence-grounded chapter spine and concept graph.
- ``SectionArchitect`` and individual ``BlockGenerator`` instances read
  ``chunks`` to avoid re-running RAG for the same query in later stages.

Two LLM calls happen here:

1. Query design (``queries_system`` / ``queries_user``) — turns the proposal
   into a small, diverse set of search queries.
2. Synthesis (``summary_system`` / ``summary_user``) — distils the retrieved
   chunks into a short summary, candidate concepts, and notes.

In between, RAG retrievals are executed *in parallel* across queries × KBs
via ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.utils.json_parser import parse_json_response

from ..models import (
    BookInputs,
    BookProposal,
    ExplorationReport,
    SourceChunk,
)

logger = logging.getLogger(__name__)

# The sweep runs one retrieval per (knowledge base x query) pair, and each is a
# vector search plus — on most backends — an LLM synthesis call. Left ungated,
# eight KBs against a dozen queries fired ~100 concurrent provider calls.
RETRIEVAL_CONCURRENCY = 6
MAX_RETRIEVAL_CALLS = 48


def _balanced_slice(chunks: list[SourceChunk], *, limit: int) -> list[SourceChunk]:
    """Pick ``limit`` chunks with every source represented.

    Ranking is only meaningful *within* one engine, so we rank inside each
    source and then take round-robin across them. A global sort by ``score``
    handed the whole slice to whichever backend happened to emit the largest
    numbers, which silently dropped notebooks, chat excerpts and any KB on a
    different scoring scale out of the synthesis input entirely.
    """
    if len(chunks) <= limit:
        return list(chunks)

    by_source: dict[str, list[SourceChunk]] = {}
    for chunk in chunks:
        by_source.setdefault(f"{chunk.source}/{chunk.kb_name or ''}", []).append(chunk)
    for group in by_source.values():
        group.sort(key=lambda c: -c.score)

    picked: list[SourceChunk] = []
    groups = list(by_source.values())
    depth = 0
    while len(picked) < limit and any(depth < len(g) for g in groups):
        for group in groups:
            if depth < len(group):
                picked.append(group[depth])
                if len(picked) == limit:
                    break
        depth += 1
    return picked


# Retrieval queries should follow the *sources*, not the book. Say so explicitly
# rather than leaving the model to guess from the prompt's own language.
_QUERY_LANGUAGE_HINT = (
    "\n\n[Query language] Write each query in the language the source material is "
    "most likely written in — usually the language of the user's intent or the "
    "knowledge base itself. Where a concept has a widely used English term "
    "(model names, algorithms, APIs), include it verbatim. These queries are "
    "matched against documents, never shown to the reader."
)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


# ─────────────────────────────────────────────────────────────────────────────
# Defaults / fallbacks
# ─────────────────────────────────────────────────────────────────────────────


_DEFAULT_QUERIES = [
    "overview and definition",
    "core mechanisms and theory",
    "representative examples and case studies",
    "common pitfalls and edge cases",
    "applications and use cases",
    "comparisons and history",
]


_FALLBACK_QUERIES_SYSTEM = (
    "Design 4-8 short, diverse search queries that, run against the user's "
    "knowledge bases, will surface useful evidence for the proposed book. "
    'Output JSON: {"queries": ["..."]}'
)
_FALLBACK_QUERIES_USER = (
    "Intent:\n{user_intent}\n\nProposal:\n{proposal_block}\n\n"
    "KBs: {kb_list}\n\nExtra context:\n{extra_context}\n\n"
    "Respond with the JSON object only."
)
_FALLBACK_SUMMARY_SYSTEM = (
    "Summarise the retrieved chunks. Output JSON: "
    '{"summary": str, "candidate_concepts": [str], "notes": [str]}.'
)
_FALLBACK_SUMMARY_USER = (
    "Intent:\n{user_intent}\n\nProposal title: {proposal_title}\n\n"
    "Coverage:\n{coverage_block}\n\nChunks:\n{chunks_block}\n\n"
    "Respond with the JSON object only."
)


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class SourceExplorer(BaseAgent):
    """Two-LLM-call agent that produces an ``ExplorationReport``."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        language: str = "en",
        # None, not "openai": BaseAgent falls back to the configured
        # provider only when this is falsy. Hard-coding it forced every
        # user onto the OpenAI wire format. Matches the pattern in
        # deeptutor/agents/research/pipeline.py:403.
        binding: str | None = None,
        *,
        max_queries: int = 8,
        chunks_per_query: int = 4,
    ) -> None:
        super().__init__(
            module_name="book",
            agent_name="source_explorer",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            binding=binding,
        )
        self.max_queries = max_queries
        self.skipped_knowledge_bases: list[str] = []
        self.chunks_per_query = chunks_per_query

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def process(self, *args: Any, **kwargs: Any) -> Any:
        """``BaseAgent.process`` adapter — forwards to :meth:`explore`."""
        return await self.explore(*args, **kwargs)

    async def explore(
        self,
        *,
        book_id: str,
        proposal: BookProposal,
        inputs: BookInputs,
        stream: StreamBus | None = None,
    ) -> ExplorationReport:
        """Run the full design → retrieve → summarise pipeline."""

        intent = (inputs.user_intent or proposal.description or "").strip()
        kb_list = list(inputs.knowledge_bases or [])
        from deeptutor.services.rag.pipelines.pageindex import (
            validate_pageindex_oss_selection,
        )

        validate_pageindex_oss_selection(kb_list)

        queries = await self._design_queries(proposal=proposal, inputs=inputs)
        if not queries:
            queries = list(_DEFAULT_QUERIES)
        queries = queries[: self.max_queries]

        chunks: list[SourceChunk] = []
        if kb_list:
            chunks.extend(await self._retrieve_kb_chunks(queries, kb_list, stream=stream))

        chunks.extend(self._collect_non_kb_chunks(inputs))

        chunks = self._dedupe_and_clip(chunks)

        coverage: dict[str, int] = {}
        for ch in chunks:
            coverage[ch.source] = coverage.get(ch.source, 0) + 1

        summary, concepts, notes = await self._summarise(
            proposal=proposal,
            intent=intent,
            chunks=chunks,
            coverage=coverage,
        )

        # Connected KBs contributed nothing because nothing could read them.
        # Say so in the report rather than letting an empty contribution look
        # like a source with no relevant content.
        if self.skipped_knowledge_bases:
            notes = [
                *notes,
                "Not swept (no local index — these need their own capability): "
                + ", ".join(self.skipped_knowledge_bases),
            ]

        return ExplorationReport(
            book_id=book_id,
            queries=queries,
            chunks=chunks,
            summary=summary,
            coverage=coverage,
            candidate_concepts=concepts,
            notes=notes,
        )

    # ------------------------------------------------------------------ #
    # Step 1 — query design
    # ------------------------------------------------------------------ #

    async def _design_queries(
        self,
        *,
        proposal: BookProposal,
        inputs: BookInputs,
    ) -> list[str]:
        system_prompt = self.get_prompt("queries_system") or _FALLBACK_QUERIES_SYSTEM
        # Deliberately no language directive here. These strings are matched
        # against document text, not shown to anyone: pinning them to the book's
        # language starves retrieval whenever the sources are written in a
        # different one. The summary below *is* reader-facing and does get it.
        system_prompt = system_prompt.rstrip() + _QUERY_LANGUAGE_HINT
        user_template = self.get_prompt("queries_user") or _FALLBACK_QUERIES_USER

        intent = (inputs.user_intent or proposal.description or "").strip() or "(empty)"
        kb_list = ", ".join(inputs.knowledge_bases) or "(none)"
        proposal_block = (
            f"title: {proposal.title}\n"
            f"description: {proposal.description}\n"
            f"scope: {proposal.scope}\n"
            f"target_level: {proposal.target_level}\n"
            f"estimated_chapters: {proposal.estimated_chapters}"
        )
        extra_context_lines: list[str] = []
        if inputs.notebook_refs:
            extra_context_lines.append(
                f"- Notebook records selected: "
                f"{sum(len(r.record_ids) for r in inputs.notebook_refs) or 'all'}"
            )
        if inputs.chat_history:
            recent = inputs.chat_history[-4:]
            extra_context_lines.append(
                "- Recent chat highlights: " + " | ".join(_clip(m.content, 120) for m in recent)
            )
        if inputs.question_categories or inputs.question_entries:
            extra_context_lines.append(
                f"- Quiz items: cats={len(inputs.question_categories)} "
                f"entries={len(inputs.question_entries)}"
            )
        extra_context = "\n".join(extra_context_lines) or "(none)"

        user_prompt = user_template.format(
            user_intent=intent,
            proposal_block=proposal_block,
            kb_list=kb_list,
            extra_context=extra_context,
        )

        try:
            chunks: list[str] = []
            async for piece in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                stage="explore_queries",
            ):
                chunks.append(piece)
            raw = "".join(chunks)
        except Exception as exc:
            logger.warning(f"SourceExplorer query LLM failed: {exc}")
            return []

        payload = parse_json_response(raw, logger_instance=self.logger, fallback={})
        if not isinstance(payload, dict):
            return []
        queries_raw = payload.get("queries")
        if not isinstance(queries_raw, list):
            return []

        seen: set[str] = set()
        result: list[str] = []
        for q in queries_raw:
            text = str(q or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text[:160])
            if len(result) >= self.max_queries:
                break
        return result

    # ------------------------------------------------------------------ #
    # Step 2 — parallel RAG retrieval
    # ------------------------------------------------------------------ #

    @staticmethod
    def partition_knowledge_bases(kb_list: list[str]) -> tuple[list[str], list[str]]:
        """Split *kb_list* into (retrievable, unreachable).

        Only the KBs ``rag_search`` genuinely cannot reach are set aside: an
        Obsidian vault (no index — its capability navigates live files), a
        MarginNote 4 library (same shape: synced objects in their own store,
        reachable only through the MN4 tools) and a connected subagent (not a
        document collection). Sweeping those returned nothing and looked
        identical to a source that simply had no relevant content, so the
        reader never learned their vault contributed zero; reaching them
        properly means driving each capability, which is separate work, and
        naming them is the honest interim.

        Every other pointer KB *is* retrievable and is swept normally — a
        ``linked`` folder mounts an index built elsewhere, and ``lightrag_server``
        / ``ima`` offload retrieval over HTTP. Treating "connected" as
        "unsearchable" silently dropped those sources from every book.
        """
        retrievable: list[str] = []
        unreachable: list[str] = []
        for kb in kb_list:
            try:
                from deeptutor.knowledge.kb_types import supports_rag_retrieval
                from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

                meta = resolve_kb_metadata(kb)
            except Exception:  # noqa: BLE001 - unresolvable → treat as ordinary
                meta = None
            (retrievable if supports_rag_retrieval(meta) else unreachable).append(kb)
        return retrievable, unreachable

    async def _retrieve_kb_chunks(
        self,
        queries: list[str],
        kb_list: list[str],
        *,
        stream: StreamBus | None = None,
    ) -> list[SourceChunk]:
        kb_list, connected = self.partition_knowledge_bases(kb_list)
        if connected:
            self.skipped_knowledge_bases = list(connected)
            logger.info(
                "source exploration skipped %d connected KB(s) with no local index: %s",
                len(connected),
                ", ".join(connected),
            )

        pageindex_kbs: list[str] = []
        traditional_kbs: list[str] = []
        for kb in kb_list:
            try:
                from deeptutor.multi_user.knowledge_access import resolve_kb
                from deeptutor.services.rag.factory import (
                    PAGEINDEX_OSS_PROVIDER,
                    PAGEINDEX_PROVIDER,
                )
                from deeptutor.services.rag.provider_binding import resolve_bound_provider

                resource = resolve_kb(kb, require_write=False)
                provider = resolve_bound_provider(str(resource.base_dir), resource.name)
            except Exception:
                provider = ""
            (
                pageindex_kbs
                if provider in {PAGEINDEX_PROVIDER, PAGEINDEX_OSS_PROVIDER}
                else traditional_kbs
            ).append(kb)

        pageindex_chunks = await self._retrieve_pageindex_chunks(
            queries,
            pageindex_kbs,
            stream=stream,
        )
        if not traditional_kbs:
            return pageindex_chunks

        try:
            from deeptutor.tools.rag_tool import rag_search
        except Exception as exc:  # pragma: no cover - import guard
            logger.warning(f"rag_tool unavailable: {exc}")
            return pageindex_chunks

        async def _one_query(kb: str, query: str) -> list[SourceChunk]:
            try:
                result = await rag_search(query=query, kb_name=kb)
            except Exception as exc:
                logger.debug(f"rag_search({kb}, {query!r}) failed: {exc}")
                return []
            if not isinstance(result, dict):
                return []
            sources = result.get("sources")
            if not isinstance(sources, list):
                return []

            answer = str(result.get("answer") or result.get("content") or "").strip()
            out: list[SourceChunk] = []
            for idx, src in enumerate(sources[: self.chunks_per_query]):
                if not isinstance(src, dict):
                    continue
                ref = (
                    src.get("id")
                    or src.get("doc_id")
                    or src.get("path")
                    or src.get("source")
                    or f"{kb}#{idx}"
                )
                text = src.get("text") or src.get("snippet") or src.get("content") or ""
                score = src.get("score") or src.get("similarity") or 0.0
                try:
                    score_f = float(score)
                except (TypeError, ValueError):
                    score_f = 0.0
                out.append(
                    SourceChunk(
                        chunk_id=str(ref)[:200],
                        kb_name=kb,
                        source="kb",
                        ref=str(ref)[:200],
                        text=_clip(str(text), 1200),
                        score=score_f,
                        query=query,
                    )
                )
            # If RAG returned an answer but no usable sources, surface it as
            # a synthesised chunk so the spine still has something to chew on.
            if not out and answer:
                out.append(
                    SourceChunk(
                        chunk_id=f"{kb}::synth::{abs(hash(query)) % 10_000}",
                        kb_name=kb,
                        source="kb",
                        ref=f"synthesised::{kb}",
                        text=_clip(answer, 1200),
                        score=0.0,
                        query=query,
                        metadata={"synthesised": True},
                    )
                )
            return out

        # Query-major, not KB-major: the pair list gets trimmed below, and
        # trimming a KB-major list would starve the last knowledge bases of
        # every query. Interleaving keeps coverage even when the budget bites.
        pairs = [(kb, q) for q in queries for kb in traditional_kbs]
        if not pairs:
            return []

        dropped = 0
        if len(pairs) > MAX_RETRIEVAL_CALLS:
            dropped = len(pairs) - MAX_RETRIEVAL_CALLS
            pairs = pairs[:MAX_RETRIEVAL_CALLS]
            logger.info(
                f"source exploration capped at {MAX_RETRIEVAL_CALLS} retrievals "
                f"({len(traditional_kbs)} KBs x {len(queries)} queries); {dropped} skipped"
            )

        # Every pair is a retrieval plus, on most backends, an LLM synthesis
        # call. Firing all of them at once trips provider rate limits and
        # spikes memory; a gate keeps the sweep fast without the stampede.
        gate = asyncio.Semaphore(RETRIEVAL_CONCURRENCY)

        async def _guarded(kb: str, query: str) -> list[SourceChunk]:
            async with gate:
                return await _one_query(kb, query)

        gathered = await asyncio.gather(
            *(_guarded(kb, q) for kb, q in pairs), return_exceptions=False
        )
        chunks: list[SourceChunk] = []
        for batch in gathered:
            chunks.extend(batch)
        return [*pageindex_chunks, *chunks]

    async def _retrieve_pageindex_chunks(
        self,
        queries: list[str],
        kb_list: list[str],
        *,
        stream: StreamBus | None,
    ) -> list[SourceChunk]:
        if not kb_list:
            return []
        from deeptutor.services.rag.pipelines.pageindex.reasoning import (
            read_pageindex_with_agent,
        )

        query_block = "\n".join(f"- {query}" for query in queries)

        async def read_one(kb: str) -> SourceChunk | None:
            try:
                result = await read_pageindex_with_agent(
                    kb_name=kb,
                    system_prompt=(
                        "You are the SourceExplorer for a book workflow. Build a dense evidence "
                        "brief that later planning and block-generation stages can reuse. Cover "
                        "the supplied research questions, preserve concrete facts and page "
                        "references, and do not draft the book itself."
                    ),
                    user_prompt=f"Collect source evidence for these questions:\n{query_block}",
                    context=UnifiedContext(
                        user_message=query_block,
                        knowledge_bases=[kb],
                    ),
                    stream=stream,
                    source="book_source_explorer",
                    stage="exploration",
                )
            except Exception as exc:
                logger.warning("PageIndex SourceExplorer failed for %s: %s", kb, exc)
                return None
            if not result.text:
                return None
            return SourceChunk(
                chunk_id=f"pageindex::{kb}",
                kb_name=kb,
                source="kb",
                ref=f"pageindex::{kb}",
                text=_clip(result.text, 8000),
                score=1.0,
                query="; ".join(queries),
                metadata={"provider": result.tool_context.provider, "sources": result.sources},
            )

        rows = await asyncio.gather(*(read_one(kb) for kb in kb_list))
        return [row for row in rows if row is not None]

    # ------------------------------------------------------------------ #
    # Step 3 — non-KB sources (notebooks, chat, questions)
    # ------------------------------------------------------------------ #

    def _collect_non_kb_chunks(self, inputs: BookInputs) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []

        # Notebook records
        try:
            if inputs.notebook_refs:
                from deeptutor.services.notebook import notebook_manager

                records = notebook_manager.get_records_by_references(
                    [r.model_dump() for r in inputs.notebook_refs]
                )
                for rec in records[:24]:
                    text = str(
                        rec.get("summary")
                        or rec.get("output")
                        or rec.get("content")
                        or rec.get("title")
                        or ""
                    ).strip()
                    if not text:
                        continue
                    rid = str(rec.get("id") or rec.get("title") or "notebook")
                    chunks.append(
                        SourceChunk(
                            chunk_id=f"nb::{rid}",
                            source="notebook",
                            ref=rid[:200],
                            text=_clip(text, 1200),
                            metadata={
                                "notebook_name": rec.get("notebook_name") or "",
                                "title": rec.get("title") or "",
                            },
                        )
                    )
        except Exception as exc:
            logger.debug(f"Notebook chunk collection skipped: {exc}")

        # Chat snapshots
        for msg in (inputs.chat_history or [])[-24:]:
            text = (msg.content or "").strip()
            if len(text) < 20:
                continue
            chunks.append(
                SourceChunk(
                    chunk_id=f"chat::{int(msg.created_at) or len(chunks)}",
                    source="chat",
                    ref=msg.role or "chat",
                    text=_clip(text, 1200),
                    metadata={
                        "role": msg.role,
                        "capability": msg.capability or "",
                    },
                )
            )

        return chunks

    # ------------------------------------------------------------------ #
    # Step 4 — dedupe + clip
    # ------------------------------------------------------------------ #

    @staticmethod
    def _dedupe_and_clip(chunks: list[SourceChunk]) -> list[SourceChunk]:
        seen: set[str] = set()
        deduped: list[SourceChunk] = []
        for ch in chunks:
            key = f"{ch.source}::{ch.ref}::{ch.text[:200]}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(ch)
        return deduped[:96]

    # ------------------------------------------------------------------ #
    # Step 5 — synthesis LLM call
    # ------------------------------------------------------------------ #

    async def _summarise(
        self,
        *,
        proposal: BookProposal,
        intent: str,
        chunks: list[SourceChunk],
        coverage: dict[str, int],
    ) -> tuple[str, list[str], list[str]]:
        if not chunks:
            return ("", [], [])

        from ..blocks._language import language_directive

        system_prompt = self.get_prompt("summary_system") or _FALLBACK_SUMMARY_SYSTEM
        system_prompt = system_prompt.rstrip() + language_directive(self.language)
        user_template = self.get_prompt("summary_user") or _FALLBACK_SUMMARY_USER

        # Send only the most informative slice to the synthesiser — but pick it
        # per source, not by a global sort. Scores come from different engines
        # (cosine, BM25, a remote service's own scale) and are not comparable,
        # so ranking them together let one KB's numbers crowd out every other.
        slice_chunks = _balanced_slice(chunks, limit=24)
        chunks_block = "\n".join(
            f"- [{c.source}/{c.kb_name or 'n/a'}] (q={c.query!r}) {_clip(c.text, 320)}"
            for c in slice_chunks
        )
        coverage_block = ", ".join(f"{k}={v}" for k, v in coverage.items()) or "(none)"

        user_prompt = user_template.format(
            user_intent=intent or "(empty)",
            proposal_title=proposal.title,
            proposal_scope=proposal.scope,
            coverage_block=coverage_block,
            chunks_block=chunks_block,
        )

        try:
            buf: list[str] = []
            async for piece in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                stage="explore_summary",
            ):
                buf.append(piece)
            raw = "".join(buf)
        except Exception as exc:
            logger.warning(f"SourceExplorer summary LLM failed: {exc}")
            return ("", [], [])

        payload = parse_json_response(raw, logger_instance=self.logger, fallback={})
        if not isinstance(payload, dict):
            return ("", [], [])

        summary = _clip(str(payload.get("summary") or ""), 2400)
        concepts_raw = payload.get("candidate_concepts")
        notes_raw = payload.get("notes")
        concepts = _coerce_str_list(concepts_raw, max_items=24, max_len=80)
        notes = _coerce_str_list(notes_raw, max_items=8, max_len=240)
        return summary, concepts, notes


def _coerce_str_list(raw: Any, *, max_items: int, max_len: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(_clip(text, max_len))
        if len(out) >= max_items:
            break
    return out


__all__ = ["SourceExplorer"]
