"""
SpineSynthesizer
================

Stage 2 of the BookEngine pipeline (replaces the legacy ``SpineAgent``).

Implements a multi-round **Draft → Critique → Revise** reasoning loop driven
by an ``ExplorationReport`` produced by ``SourceExplorer``. The synthesiser
emits *both* a chapter ``Spine`` AND a directed ``ConceptGraph`` in a single
shot so the two stay in sync.

Pipeline (default ``max_rounds=2``):

1. **Draft** — one LLM call that produces ``{concept_graph, chapters}``.
2. **Critique** — second LLM call that checks coverage / ordering / cycles
   and returns ``{issues, verdict}``.
3. **Revise** — third LLM call that incorporates the critique.

If any LLM call fails, the synthesiser returns the last valid draft (or a
minimal fallback) so the pipeline never blocks.

After the LLM rounds, deterministic post-processing applies:

- **Topological sort** of chapters by ``covers`` + concept-graph dependencies.
- **Cycle removal** in the concept graph (drops the lowest-rationale edge).
- **Coverage padding** — concepts with no covering chapter are attached to
  the most relevant existing chapter (Jaccard over labels).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
import logging
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.utils.json_parser import parse_json_response

from ..models import (
    BookProposal,
    Chapter,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    ContentType,
    ExplorationReport,
    SourceAnchor,
    Spine,
)

logger = logging.getLogger(__name__)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _slug(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in (text or "").strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")[:48] or "concept"


_FALLBACK_SYSTEM = (
    "Design BOTH a concept_graph and a chapter spine. "
    'Output JSON with keys {"concept_graph": {"nodes":[...], "edges":[...]}, '
    '"chapters": [...]}.'
)
_FALLBACK_USER = "Proposal:\n{proposal_block}\n\nExploration:\n{exploration_summary}"


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class SpineSynthesizer(BaseAgent):
    """Draft → Critique → Revise spine designer with concept-graph output."""

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
        max_rounds: int = 2,
    ) -> None:
        super().__init__(
            module_name="book",
            agent_name="spine_synthesizer",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            binding=binding,
        )
        self.max_rounds = max(1, max_rounds)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def process(self, *args: Any, **kwargs: Any) -> Spine:
        """``BaseAgent.process`` adapter — forwards to :meth:`synthesize`."""
        return await self.synthesize(*args, **kwargs)

    async def synthesize(
        self,
        *,
        book_id: str,
        proposal: BookProposal,
        exploration: ExplorationReport | None,
        on_round: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> Spine:
        proposal_block = self._render_proposal(proposal)
        exploration_summary = (exploration.summary if exploration else "") or "(none)"
        candidate_concepts_text = (
            ", ".join(exploration.candidate_concepts)
            if exploration and exploration.candidate_concepts
            else "(none)"
        )
        chunks_block = self._render_chunks(exploration)

        # ── Round 1: Draft ─────────────────────────────────────────────
        draft = await self._draft(
            proposal_block=proposal_block,
            exploration_summary=exploration_summary,
            candidate_concepts_text=candidate_concepts_text,
            chunks_block=chunks_block,
        )
        if on_round:
            await _maybe_await(on_round("draft", draft))

        current = draft

        # ── Round 2+: Critique → Revise ───────────────────────────────
        for round_idx in range(1, self.max_rounds):
            critique = await self._critique(
                proposal_block=proposal_block,
                exploration_summary=exploration_summary,
                draft=current,
            )
            if on_round:
                await _maybe_await(on_round(f"critique_{round_idx}", critique))

            verdict = str(critique.get("verdict") or "").lower()
            issues = critique.get("issues") or []
            if verdict == "ok" or not issues:
                break

            revised = await self._revise(
                proposal_block=proposal_block,
                draft=current,
                critique=critique,
            )
            if revised:
                current = revised
                if on_round:
                    await _maybe_await(on_round(f"revise_{round_idx}", current))

        spine = self._materialise(
            book_id=book_id,
            proposal=proposal,
            payload=current,
            exploration=exploration,
        )
        return spine

    # ------------------------------------------------------------------ #
    # Round helpers
    # ------------------------------------------------------------------ #

    async def _draft(
        self,
        *,
        proposal_block: str,
        exploration_summary: str,
        candidate_concepts_text: str,
        chunks_block: str,
    ) -> dict[str, Any]:
        system_prompt = self.get_prompt("draft_system") or _FALLBACK_SYSTEM
        user_template = self.get_prompt("draft_user") or _FALLBACK_USER
        user_prompt = user_template.format(
            proposal_block=proposal_block,
            exploration_summary=exploration_summary,
            candidate_concepts=candidate_concepts_text,
            chunks_block=chunks_block,
        )
        return await self._call_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stage="spine_draft",
        )

    async def _critique(
        self,
        *,
        proposal_block: str,
        exploration_summary: str,
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = self.get_prompt("critique_system")
        user_template = self.get_prompt("critique_user")
        if not system_prompt or not user_template:
            return {"issues": [], "verdict": "ok"}
        user_prompt = user_template.format(
            proposal_block=proposal_block,
            exploration_summary=exploration_summary,
            draft_block=_clip(_safe_json(draft), 4500),
        )
        result = await self._call_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stage="spine_critique",
        )
        if not isinstance(result, dict):
            result = {"issues": [], "verdict": "ok"}
        return result

    async def _revise(
        self,
        *,
        proposal_block: str,
        draft: dict[str, Any],
        critique: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = self.get_prompt("revise_system")
        user_template = self.get_prompt("revise_user")
        if not system_prompt or not user_template:
            return {}
        user_prompt = user_template.format(
            proposal_block=proposal_block,
            critique_block=_clip(_safe_json(critique), 2400),
            draft_block=_clip(_safe_json(draft), 4500),
        )
        return await self._call_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stage="spine_revise",
        )

    async def _call_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        stage: str,
    ) -> dict[str, Any]:
        from ..blocks._language import language_directive

        system_prompt = system_prompt.rstrip() + language_directive(self.language)
        try:
            # Blocking rather than streamed: nothing consumes the partial JSON,
            # and a reasoning model's <think> prelude never reaches the parser
            # this way, so a truncated spine cannot collapse to one placeholder
            # chapter (#707).
            raw = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                stage=stage,
            )
        except Exception as exc:
            logger.warning(f"SpineSynthesizer LLM call ({stage}) failed: {exc}")
            return {}
        payload = parse_json_response(raw, logger_instance=self.logger, fallback={})
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------------------ #
    # Materialise: payload → Spine + ConceptGraph (with validation)
    # ------------------------------------------------------------------ #

    def _materialise(
        self,
        *,
        book_id: str,
        proposal: BookProposal,
        payload: dict[str, Any],
        exploration: ExplorationReport | None,
    ) -> Spine:
        raw_graph = self._coerce_graph(payload.get("concept_graph"))
        chapters_raw = payload.get("chapters")
        chapters = self._coerce_chapters(chapters_raw, raw_graph)

        if not chapters:
            chapters = [
                Chapter(
                    title=f"{proposal.title} – Overview",
                    learning_objectives=[
                        "Understand the scope of this book",
                        "Identify the key topics it will cover",
                    ],
                    content_type=ContentType.THEORY,
                    summary=proposal.description or "Overview chapter.",
                    order=0,
                )
            ]

        # ── Validation passes (uses the raw LLM concept graph) ────────
        raw_graph = _remove_cycles(raw_graph)
        chapters = _topological_sort(chapters, raw_graph)
        raw_graph = _ensure_full_coverage(chapters, raw_graph)

        for idx, chapter in enumerate(chapters):
            chapter.order = idx

        # ── Build a chapter-level mind map for the Overview page ──────
        # The raw concept graph served its purpose (topological ordering).
        # The user-facing graph should map 1-to-1 with chapters so the
        # Overview concept map reads like a mind map of the book.
        chapter_map = _build_chapter_map(
            chapters,
            raw_graph,
            book_title=proposal.title,
        )

        return Spine(
            book_id=book_id,
            chapters=chapters,
            concept_graph=chapter_map,
            exploration_summary=(exploration.summary if exploration else ""),
        )

    # ------------------------------------------------------------------ #
    # Coercers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _coerce_graph(raw: Any) -> ConceptGraph:
        if not isinstance(raw, dict):
            return ConceptGraph()
        nodes_raw = raw.get("nodes") or []
        edges_raw = raw.get("edges") or []

        nodes: list[ConceptNode] = []
        seen_ids: set[str] = set()
        for item in nodes_raw if isinstance(nodes_raw, list) else []:
            if not isinstance(item, dict):
                continue
            label = _clip(str(item.get("label") or ""), 80)
            if not label:
                continue
            nid = _slug(str(item.get("id") or label))
            if not nid or nid in seen_ids:
                continue
            seen_ids.add(nid)
            try:
                weight = float(item.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            nodes.append(
                ConceptNode(
                    id=nid,
                    label=label,
                    description=_clip(str(item.get("description") or ""), 240),
                    weight=max(0.05, min(1.0, weight)),
                )
            )

        edges: list[ConceptEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for item in edges_raw if isinstance(edges_raw, list) else []:
            if not isinstance(item, dict):
                continue
            src = _slug(str(item.get("src") or ""))
            dst = _slug(str(item.get("dst") or ""))
            if not src or not dst or src == dst:
                continue
            if src not in seen_ids or dst not in seen_ids:
                continue
            relation = str(item.get("relation") or "depends_on").strip().lower()
            if relation not in {"depends_on", "extends", "related"}:
                relation = "depends_on"
            key = (src, dst, relation)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append(
                ConceptEdge(
                    src=src,
                    dst=dst,
                    relation=relation,
                    rationale=_clip(str(item.get("rationale") or ""), 240),
                )
            )

        return ConceptGraph(nodes=nodes, edges=edges)

    @staticmethod
    def _coerce_chapters(raw: Any, graph: ConceptGraph) -> list[Chapter]:
        if not isinstance(raw, list):
            return []
        node_ids = {n.id for n in graph.nodes}
        chapters: list[Chapter] = []
        seen_titles: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = _clip(str(item.get("title") or ""), 160)
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())

            objectives_raw = item.get("learning_objectives") or []
            if not isinstance(objectives_raw, list):
                objectives_raw = []
            objectives = [_clip(str(o), 200) for o in objectives_raw if str(o or "").strip()][:6]

            anchors_raw = item.get("source_anchors") or []
            anchors: list[SourceAnchor] = []
            if isinstance(anchors_raw, list):
                for anchor_item in anchors_raw[:6]:
                    if not isinstance(anchor_item, dict):
                        continue
                    anchors.append(
                        SourceAnchor(
                            kind=_clip(str(anchor_item.get("kind") or "manual"), 32),
                            ref=_clip(str(anchor_item.get("ref") or ""), 200),
                            snippet=_clip(str(anchor_item.get("snippet") or ""), 300),
                        )
                    )

            content_type = ContentType.THEORY
            try:
                content_type = ContentType(
                    str(item.get("content_type") or "theory").strip().lower()
                )
            except ValueError:
                content_type = ContentType.THEORY
            if content_type == ContentType.OVERVIEW:
                # Overview is reserved for engine-injected first chapter.
                content_type = ContentType.THEORY

            prereq_raw = item.get("prerequisites") or []
            prerequisites = (
                [_clip(str(p), 160) for p in prereq_raw if str(p or "").strip()][:4]
                if isinstance(prereq_raw, list)
                else []
            )

            covers_raw = item.get("covers") or []
            covers = []
            if isinstance(covers_raw, list):
                for c in covers_raw:
                    cid = _slug(str(c or ""))
                    if cid and cid in node_ids and cid not in covers:
                        covers.append(cid)

            chapter = Chapter(
                title=title,
                learning_objectives=objectives,
                content_type=content_type,
                source_anchors=anchors,
                prerequisites=prerequisites,
                summary=_clip(str(item.get("summary") or ""), 400),
            )
            # Stash covered concept ids on the chapter (extra="allow" enabled).
            chapter.__pydantic_extra__ = chapter.__pydantic_extra__ or {}
            chapter.__pydantic_extra__["covers"] = covers
            chapters.append(chapter)
        return chapters

    # ------------------------------------------------------------------ #
    # Renderers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _render_proposal(proposal: BookProposal) -> str:
        return (
            f"title: {proposal.title}\n"
            f"description: {proposal.description}\n"
            f"scope: {proposal.scope}\n"
            f"target_level: {proposal.target_level}\n"
            f"estimated_chapters: {proposal.estimated_chapters}\n"
            f"rationale: {proposal.rationale}"
        )

    @staticmethod
    def _render_chunks(exploration: ExplorationReport | None) -> str:
        if not exploration or not exploration.chunks:
            return "(no exploration evidence)"
        slice_chunks = sorted(exploration.chunks, key=lambda c: -c.score)[:18]
        lines = []
        for ch in slice_chunks:
            tag = ch.kb_name or ch.source
            lines.append(f"- [{tag}] {_clip(ch.text, 280)}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_chapter_map(
    chapters: list[Chapter],
    raw_graph: ConceptGraph,
    *,
    book_title: str = "",
) -> ConceptGraph:
    """Derive a chapter-level mind map where each node IS a chapter.

    Edges come from two sources (merged, deduplicated):
    1. Concept-graph ``depends_on`` edges — lifted to chapter level via the
       ``covers`` mapping (chapter A covers prerequisite concept, chapter B
       covers dependent concept → edge A→B).
    2. Explicit ``prerequisites`` on each chapter (matched by title).

    If multiple root chapters exist (no incoming edges) and a *book_title* is
    given, a virtual root node is added to form a connected tree, giving the
    rendered Mermaid diagram a clear mind-map shape.
    """

    # ── Node per chapter ──────────────────────────────────────────────
    slug_of: dict[str, str] = {}  # chapter.id → slug
    title_to_slug: dict[str, str] = {}  # chapter.title.lower() → slug
    concept_to_slug: dict[str, str] = {}  # concept_id → owning chapter slug
    nodes: list[ConceptNode] = []

    for idx, ch in enumerate(chapters):
        slug = _slug(ch.title) or f"ch_{idx}"
        # Ensure uniqueness
        base = slug
        counter = 2
        while slug in {n.id for n in nodes}:
            slug = f"{base}_{counter}"
            counter += 1

        slug_of[ch.id] = slug
        title_to_slug[ch.title.strip().lower()] = slug
        for cid in (ch.__pydantic_extra__ or {}).get("covers") or []:
            concept_to_slug.setdefault(cid, slug)

        nodes.append(
            ConceptNode(
                id=slug,
                label=ch.title,
                description=ch.summary or "",
                weight=1.0,
                chapter_id=ch.id,
            )
        )

    # ── Edges: concept-graph dependencies lifted to chapter level ─────
    seen_edges: set[tuple[str, str]] = set()
    edges: list[ConceptEdge] = []

    for edge in raw_graph.edges:
        if edge.relation != "depends_on":
            continue
        src_slug = concept_to_slug.get(edge.src)
        dst_slug = concept_to_slug.get(edge.dst)
        if not src_slug or not dst_slug or src_slug == dst_slug:
            continue
        pair = (src_slug, dst_slug)
        if pair in seen_edges:
            continue
        seen_edges.add(pair)
        edges.append(
            ConceptEdge(src=src_slug, dst=dst_slug, relation="depends_on", rationale=edge.rationale)
        )

    # ── Edges: explicit prerequisite titles ───────────────────────────
    for ch in chapters:
        dst_slug = slug_of.get(ch.id)
        if not dst_slug:
            continue
        for prereq_title in ch.prerequisites:
            src_slug = title_to_slug.get(prereq_title.strip().lower())
            if not src_slug or src_slug == dst_slug:
                continue
            pair = (src_slug, dst_slug)
            if pair in seen_edges:
                continue
            seen_edges.add(pair)
            edges.append(
                ConceptEdge(src=src_slug, dst=dst_slug, relation="depends_on", rationale="")
            )

    # ── Virtual root for disconnected graphs ──────────────────────────
    incoming = {e.dst for e in edges}
    roots = [n for n in nodes if n.id not in incoming]
    if len(roots) > 1 and book_title:
        root_slug = _slug(book_title) or "book"
        if root_slug in {n.id for n in nodes}:
            root_slug = f"{root_slug}_root"
        root_node = ConceptNode(
            id=root_slug,
            label=book_title,
            description="",
            weight=1.0,
        )
        nodes.insert(0, root_node)
        for rn in roots:
            edges.append(ConceptEdge(src=root_slug, dst=rn.id, relation="related", rationale=""))

    return ConceptGraph(nodes=nodes, edges=edges)


def _remove_cycles(graph: ConceptGraph) -> ConceptGraph:
    """Drop the weakest ``depends_on`` edge in any detected cycle."""
    if not graph.edges:
        return graph

    edges = [e for e in graph.edges]
    node_ids = {n.id for n in graph.nodes}

    def _find_cycle(active_edges: list[ConceptEdge]) -> list[str] | None:
        adj: dict[str, list[str]] = defaultdict(list)
        for e in active_edges:
            if e.relation == "depends_on":
                adj[e.src].append(e.dst)
        color: dict[str, int] = {n: 0 for n in node_ids}
        stack: list[str] = []

        def dfs(node: str) -> list[str] | None:
            color[node] = 1
            stack.append(node)
            for nxt in adj.get(node, []):
                if color.get(nxt) == 1:
                    idx = stack.index(nxt)
                    return stack[idx:] + [nxt]
                if color.get(nxt) == 0:
                    cyc = dfs(nxt)
                    if cyc:
                        return cyc
            stack.pop()
            color[node] = 2
            return None

        for n in list(node_ids):
            if color.get(n) == 0:
                cyc = dfs(n)
                if cyc:
                    return cyc
        return None

    safety = 0
    while safety < 20:
        cycle = _find_cycle(edges)
        if cycle is None:
            break
        cycle_pairs = set(zip(cycle, cycle[1:]))
        candidates = [e for e in edges if (e.src, e.dst) in cycle_pairs]
        if not candidates:
            break
        # Drop the edge with the least rationale (proxy for confidence).
        weakest = min(candidates, key=lambda e: len(e.rationale or ""))
        edges.remove(weakest)
        logger.debug(f"SpineSynthesizer dropped cycle edge {weakest.src}→{weakest.dst}")
        safety += 1

    return ConceptGraph(nodes=graph.nodes, edges=edges)


def _topological_sort(chapters: list[Chapter], graph: ConceptGraph) -> list[Chapter]:
    """Re-order chapters so that ``covers`` follow concept-graph dependencies.

    Falls back to original order on any inconsistency.
    """
    if not chapters or not graph.nodes:
        return chapters

    # Map each concept id → first chapter index that covers it.
    chapter_of: dict[str, int] = {}
    for idx, chapter in enumerate(chapters):
        covers = (chapter.__pydantic_extra__ or {}).get("covers") or []
        for nid in covers:
            chapter_of.setdefault(nid, idx)

    # Build chapter-level dependency graph.
    n = len(chapters)
    chapter_adj: dict[int, set[int]] = defaultdict(set)
    indeg: dict[int, int] = {i: 0 for i in range(n)}
    for edge in graph.edges:
        if edge.relation != "depends_on":
            continue
        src_idx = chapter_of.get(edge.src)
        dst_idx = chapter_of.get(edge.dst)
        if src_idx is None or dst_idx is None or src_idx == dst_idx:
            continue
        if dst_idx in chapter_adj[src_idx]:
            continue
        chapter_adj[src_idx].add(dst_idx)
        indeg[dst_idx] += 1

    # Kahn — break ties by original order to keep author intent.
    ready = sorted([i for i in range(n) if indeg[i] == 0])
    ordered: list[int] = []
    while ready:
        i = ready.pop(0)
        ordered.append(i)
        for j in sorted(chapter_adj[i]):
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
                ready.sort()

    if len(ordered) != n:
        # Cycle in chapter graph → bail out, keep original order.
        return chapters
    return [chapters[i] for i in ordered]


def _ensure_full_coverage(chapters: list[Chapter], graph: ConceptGraph) -> ConceptGraph:
    """Attach uncovered concept nodes to the most relevant chapter (Jaccard)."""
    if not graph.nodes or not chapters:
        return graph

    covered: set[str] = set()
    for ch in chapters:
        for nid in (ch.__pydantic_extra__ or {}).get("covers") or []:
            covered.add(nid)

    def _tokenize(text: str) -> set[str]:
        return {t for t in (text or "").lower().replace("_", " ").split() if len(t) > 1}

    chapter_tokens = [
        _tokenize(f"{ch.title} {ch.summary} {' '.join(ch.learning_objectives)}") for ch in chapters
    ]

    for node in graph.nodes:
        if node.id in covered:
            continue
        node_tokens = _tokenize(f"{node.label} {node.description}")
        if not node_tokens:
            target_idx = 0
        else:
            best_idx = 0
            best_score = -1.0
            for idx, ctoks in enumerate(chapter_tokens):
                if not ctoks:
                    score = 0.0
                else:
                    inter = len(node_tokens & ctoks)
                    union = len(node_tokens | ctoks)
                    score = inter / union if union else 0.0
                if score > best_score:
                    best_idx = idx
                    best_score = score
            target_idx = best_idx

        target = chapters[target_idx]
        target.__pydantic_extra__ = target.__pydantic_extra__ or {}
        covers = list(target.__pydantic_extra__.get("covers") or [])
        if node.id not in covers:
            covers.append(node.id)
        target.__pydantic_extra__["covers"] = covers
        node.chapter_id = target.id
        covered.add(node.id)

    # Fill chapter_id for nodes already covered.
    for ch in chapters:
        for nid in (ch.__pydantic_extra__ or {}).get("covers") or []:
            node = graph.node_by_id(nid)
            if node and not node.chapter_id:
                node.chapter_id = ch.id

    return graph


# ─────────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────────


def _safe_json(payload: Any) -> str:
    import json

    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return str(payload)


async def _maybe_await(value: Any) -> None:
    import inspect

    if inspect.isawaitable(value):
        await value


__all__ = ["SpineSynthesizer"]
