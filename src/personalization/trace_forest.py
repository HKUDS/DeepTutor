from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from src.services.embedding import get_embedding_client
from src.services.path_service import get_path_service

from .trace_tree import TraceNode, TraceTree

logger = logging.getLogger(__name__)


class TraceForest:
    """Manage persisted trace trees, lean index, and embeddings.

    Public surface is intentionally kept thin — all query operations for
    memory agents are exposed via :class:`TraceToolkit` instead.
    """

    INDEX_FILE = "index.json"
    EMBEDDINGS_FILE = "embeddings.json"

    def __init__(self, memory_dir: Path | None = None) -> None:
        if memory_dir is None:
            memory_dir = get_path_service().get_memory_dir()
        self._traces_dir = memory_dir / "traces"
        self._traces_dir.mkdir(parents=True, exist_ok=True)
        self._memory_dir = memory_dir
        self._index_path = self._traces_dir / self.INDEX_FILE
        self._embeddings_path = self._traces_dir / self.EMBEDDINGS_FILE
        self._tree_cache: dict[str, TraceTree] = {}

    @property
    def traces_dir(self) -> Path:
        return self._traces_dir

    @property
    def memory_dir(self) -> Path:
        return self._memory_dir

    # ------------------------------------------------------------------
    # Registration (write path)
    # ------------------------------------------------------------------

    async def register(self, tree: TraceTree) -> None:
        """Persist one trace tree and update lean index + embeddings."""
        self._save_tree(tree)
        index = self._load_index()

        # Replace old trace metadata (idempotent)
        traces = [t for t in index["traces"] if t.get("trace_id") != tree.trace_id]
        traces.append({
            "trace_id": tree.trace_id,
            "trace_type": tree.trace_type,
            "timestamp": tree.timestamp,
            "root_text": tree.root.text,
            "answer_path": tree.answer_path,
            "tools_used": tree.tools_used,
            "stats": tree.stats,
        })
        index["traces"] = traces

        # Replace old node rows for this trace (lean: snippet instead of full text)
        nodes = [n for n in index["nodes"] if n.get("trace_id") != tree.trace_id]
        for node in tree.nodes.values():
            snippet = node.text[:80] + ("..." if len(node.text) > 80 else "")
            nodes.append({
                "full_id": node.full_id(tree.trace_id),
                "trace_id": tree.trace_id,
                "short_id": node.short_id,
                "level": node.level,
                "node_type": node.node_type,
                "action": node.action,
                "snippet": snippet,
            })
        index["nodes"] = nodes
        self._save_index(index)

        await self._update_embeddings(tree)

    # ------------------------------------------------------------------
    # Internal query helpers (used by TraceToolkit)
    # ------------------------------------------------------------------

    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        level: int | None = None,
        trace_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return top-K matching node rows from the lean index."""
        query = (query or "").strip()
        if not query:
            return []
        index = self._load_index()
        if not index["nodes"]:
            return []

        trace_type_set: set[str] | None = None
        if trace_type:
            trace_type_set = {
                r["trace_id"]
                for r in index["traces"]
                if r.get("trace_type") == trace_type
            }

        embeddings = self._load_embeddings()
        query_vec = await self._embed_query(query)

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in index["nodes"]:
            if level is not None and int(row.get("level", 0)) != level:
                continue
            if trace_type_set is not None and row.get("trace_id") not in trace_type_set:
                continue
            full_id = str(row.get("full_id", ""))
            if not full_id:
                continue

            node_text = str(row.get("snippet", ""))
            node_vec = embeddings.get(full_id)
            score = self._node_score(query, query_vec, node_text, node_vec)
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for _score, row in scored[:top_k]:
            tree = self.load_tree(str(row.get("trace_id", "")))
            short = str(row.get("short_id", ""))
            text = ""
            parent_short = None
            if tree and short in tree.nodes:
                node = tree.nodes[short]
                text = node.text
                parent_short = node.parent
            results.append({
                "trace_id": row.get("trace_id", ""),
                "short_id": short,
                "level": row.get("level", 0),
                "node_type": row.get("node_type", ""),
                "action": row.get("action", ""),
                "text": text or row.get("snippet", ""),
                "parent_short_id": parent_short,
            })
        return results

    def list_recent_traces(
        self,
        n: int = 10,
        trace_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the most recent *n* traces sorted by timestamp desc."""
        index = self._load_index()
        traces = index["traces"]
        if trace_type:
            traces = [t for t in traces if t.get("trace_type") == trace_type]
        traces.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
        return traces[:n]

    # ------------------------------------------------------------------
    # Tree loading
    # ------------------------------------------------------------------

    def load_tree(self, trace_id: str) -> TraceTree | None:
        """Load a trace tree by its ID. Returns None if not found."""
        if trace_id in self._tree_cache:
            return self._tree_cache[trace_id]
        path = self._tree_path(trace_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            tree = TraceTree.from_dict(payload)
            self._tree_cache[trace_id] = tree
            return tree
        except Exception as exc:
            logger.warning("Failed loading trace %s: %s", trace_id, exc)
            return None

    def reload_tree(self, trace_id: str) -> TraceTree | None:
        """Force-reload a trace from disk, bypassing the in-memory cache.

        Used by the standalone personalization terminal after the main CLI
        has updated a trace (e.g. added answer nodes).
        """
        self._tree_cache.pop(trace_id, None)
        return self.load_tree(trace_id)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _tree_path(self, trace_id: str) -> Path:
        return self._traces_dir / f"{trace_id}.json"

    def _save_tree(self, tree: TraceTree) -> None:
        path = self._tree_path(tree.trace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(tree.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._tree_cache[tree.trace_id] = tree

    def _load_index(self) -> dict[str, list[dict[str, Any]]]:
        if not self._index_path.exists():
            return {"traces": [], "nodes": []}
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
            return {
                "traces": list(payload.get("traces", []) or []),
                "nodes": list(payload.get("nodes", []) or []),
            }
        except Exception:
            return {"traces": [], "nodes": []}

    def _save_index(self, index: dict[str, Any]) -> None:
        self._index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_embeddings(self) -> dict[str, list[float]]:
        if not self._embeddings_path.exists():
            return {}
        try:
            payload = json.loads(self._embeddings_path.read_text(encoding="utf-8"))
            return {
                str(k): [float(x) for x in v]
                for k, v in dict(payload).items()
                if isinstance(v, list)
            }
        except Exception:
            return {}

    def _save_embeddings(self, embeddings: dict[str, list[float]]) -> None:
        self._embeddings_path.write_text(
            json.dumps(embeddings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def _update_embeddings(self, tree: TraceTree) -> None:
        existing = self._load_embeddings()
        to_embed_ids: list[str] = []
        to_embed_texts: list[str] = []
        for node in tree.nodes.values():
            full_id = node.full_id(tree.trace_id)
            if full_id in existing:
                continue
            if not node.text.strip():
                continue
            to_embed_ids.append(full_id)
            to_embed_texts.append(node.text)
        if not to_embed_ids:
            return
        try:
            vectors = await get_embedding_client().embed(to_embed_texts)
            for fid, vec in zip(to_embed_ids, vectors):
                existing[fid] = [float(x) for x in vec]
            self._save_embeddings(existing)
        except Exception as exc:
            logger.warning("Embedding update failed: %s", exc)

    async def _embed_query(self, query: str) -> list[float] | None:
        try:
            vectors = await get_embedding_client().embed([query])
            if vectors and vectors[0]:
                return [float(x) for x in vectors[0]]
        except Exception as exc:
            logger.debug("Query embedding failed: %s", exc)
        return None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _node_score(
        self,
        query: str,
        query_vec: list[float] | None,
        node_text: str,
        node_vec: list[float] | None,
    ) -> float:
        if query_vec is not None and node_vec is not None:
            sim = self._cosine(query_vec, node_vec)
            return max(0.0, sim)
        q = query.lower().strip()
        t = node_text.lower().strip()
        if not q or not t:
            return 0.0
        if q in t:
            return min(1.0, len(q) / max(1, len(t)))
        q_tokens = {x for x in q.split() if x}
        t_tokens = {x for x in t.split() if x}
        if not q_tokens or not t_tokens:
            return 0.0
        return len(q_tokens & t_tokens) / len(q_tokens)
