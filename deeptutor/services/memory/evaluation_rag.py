"""Evaluation-only raw-history dense retrieval and optional cross-encoder ranking.

Models are injected; importing this module never imports a model SDK or creates
an index. No active user memory, settings, credentials, or gold labels are read.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
import time
from typing import Any

from deeptutor.services.memory.evaluation import AdapterResult, CaseInput, Evidence

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]
Reranker = Callable[[str, Sequence[str]], Sequence[float]]


@dataclass(frozen=True)
class RetrievalConfig:
    """Character windows and retrieval depths, independent of evidence packing."""

    window_chars: int = 600
    overlap_chars: int = 150
    candidates: int = 128
    top_k: int = 15

    def __post_init__(self) -> None:
        values = (self.window_chars, self.overlap_chars, self.candidates, self.top_k)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("Retrieval sizes must be integers")
        if self.window_chars < 1 or not 0 <= self.overlap_chars < self.window_chars:
            raise ValueError("Require 0 <= overlap_chars < window_chars")
        if not 1 <= self.top_k <= self.candidates:
            raise ValueError("Require 1 <= top_k <= candidates")


def _vectors(values: Sequence[Sequence[float]], count: int) -> list[list[float]]:
    vectors = [[float(value) for value in vector] for vector in values]
    if len(vectors) != count or not vectors or not vectors[0]:
        raise ValueError("Embedding count/dimensions do not match the inputs")
    width = len(vectors[0])
    normalized = []
    for vector in vectors:
        if len(vector) != width or not all(math.isfinite(value) for value in vector):
            raise ValueError("Embeddings must have equal dimensions and finite values")
        norm = math.hypot(*vector)
        if norm == 0 or not math.isfinite(norm):
            raise ValueError("Embeddings must have finite nonzero norms")
        normalized.append([value / norm for value in vector])
    return normalized


class RawHistoryRAG:
    """Build an isolated per-case dense index, then optionally rerank candidates."""

    def __init__(
        self,
        embed: Embedder,
        rerank: Reranker | None = None,
        *,
        config: RetrievalConfig = RetrievalConfig(),
        model_info: Mapping[str, Any] | None = None,
    ) -> None:
        self.embed = embed
        self.rerank = rerank
        self.config = config
        self.model_info = dict(model_info or {})

    async def __call__(self, context: CaseInput) -> AdapterResult:
        return await asyncio.to_thread(self._retrieve, context)

    def _retrieve(self, context: CaseInput) -> AdapterResult:
        config = self.config
        windows: list[Evidence] = []
        sources: dict[str, str] = {}
        for index, item in enumerate(context.history):
            start = 0
            while start < len(item.text):
                end = min(start + config.window_chars, len(item.text))
                identifier = f"raw:{index}:{start}:{end}"
                windows.append(Evidence(identifier, f"{item.timestamp} {item.text[start:end]}"))
                sources[identifier] = item.identifier
                if end == len(item.text):
                    break
                start = end - config.overlap_chars
        metadata: dict[str, Any] = {
            "window_chars": config.window_chars,
            "overlap_chars": config.overlap_chars,
            "candidate_limit": config.candidates,
            "top_k": config.top_k,
            "window_count": len(windows),
            "reranker_executed": False,
            "model_info": dict(self.model_info),
            "corpus_embedding_seconds": 0.0,
            "query_embedding_seconds": 0.0,
            "rerank_seconds": 0.0,
            "index_scope": "rebuilt from visible history for each case and adapter",
        }
        if not windows:
            return AdapterResult((), True, sources, metadata)
        started = time.perf_counter()
        corpus = self.embed([window.text for window in windows])
        metadata["corpus_embedding_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        query = self.embed([context.query])
        metadata["query_embedding_seconds"] = time.perf_counter() - started
        vectors = _vectors(corpus, len(windows))
        query_vector = _vectors(query, 1)[0]
        if len(query_vector) != len(vectors[0]):
            raise ValueError("Query and corpus embedding dimensions differ")
        scores = [
            sum(a * b for a, b in zip(vector, query_vector, strict=True)) for vector in vectors
        ]
        # Later chronological windows win exact dense-score ties.
        indices = sorted(
            range(len(windows)), key=lambda index: (scores[index], index), reverse=True
        )
        candidates = indices[: config.candidates]
        metadata["dense_candidates"] = [
            {"id": windows[index].identifier, "score": scores[index]} for index in candidates
        ]
        if self.rerank is not None:
            started = time.perf_counter()
            rerank_scores = [
                float(value)
                for value in self.rerank(
                    context.query, [windows[index].text for index in candidates]
                )
            ]
            metadata["rerank_seconds"] = time.perf_counter() - started
            if len(rerank_scores) != len(candidates) or not all(
                math.isfinite(value) for value in rerank_scores
            ):
                raise ValueError("Reranker must return one finite score per candidate")
            metadata["reranker_executed"] = True
            metadata["rerank_scores"] = rerank_scores
            # Stable ties retain dense retrieval order.
            order = sorted(
                range(len(candidates)), key=lambda index: rerank_scores[index], reverse=True
            )
            candidates = [candidates[index] for index in order]
        return AdapterResult(
            tuple(windows[index] for index in candidates[: config.top_k]), True, sources, metadata
        )


def local_sentence_transformer_adapters(
    config: RetrievalConfig,
    *,
    embedding_model: str,
    embedding_revision: str,
    reranker_model: str,
    reranker_revision: str,
    device: str = "cpu",
) -> tuple[dict[str, RawHistoryRAG], dict[str, Any]]:
    """Explicitly load public safetensors models; no generation/provider calls.

    Requires sentence-transformers >=5.1.2,<6 from the optional rag-rerank group.
    Reject overlong model
    inputs rather than silently truncating evidence used for ranking.
    """
    from importlib.metadata import version

    for revision in (embedding_revision, reranker_revision):
        if len(revision) != 40 or any(
            character not in "0123456789abcdef" for character in revision
        ):
            raise ValueError("Retrieval models require full immutable commit revisions")

    from packaging.version import Version
    from sentence_transformers import CrossEncoder, SentenceTransformer

    installed = Version(version("sentence-transformers"))
    if not Version("5.1.2") <= installed < Version("6"):
        raise ImportError("Raw-history model loading requires sentence-transformers>=5.1.2,<6")

    started = time.perf_counter()
    embedder = SentenceTransformer(
        embedding_model,
        revision=embedding_revision,
        device=device,
        token=False,
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True},
    )
    cross = CrossEncoder(
        reranker_model,
        revision=reranker_revision,
        device=device,
        token=False,
        trust_remote_code=False,
        max_length=512,
        model_kwargs={"use_safetensors": True},
    )

    def embed(texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if any(
            len(embedder.tokenizer(text, truncation=False)["input_ids"]) > embedder.max_seq_length
            for text in texts
        ):
            raise ValueError(
                "Embedding input exceeds model limit; reduce window size or query length"
            )
        return embedder.encode(list(texts), convert_to_numpy=True, show_progress_bar=False).tolist()

    def rerank(query: str, texts: Sequence[str]) -> Sequence[float]:
        if any(
            len(cross.tokenizer(query, text, truncation=False)["input_ids"]) > 512 for text in texts
        ):
            raise ValueError(
                "Reranker input exceeds 512 tokens; reduce window size or query length"
            )
        return (
            cross.predict([(query, text) for text in texts], show_progress_bar=False)
            .reshape(-1)
            .tolist()
        )

    model_info = {
        "embedding_model": embedding_model,
        "embedding_revision": embedding_revision,
        "reranker_model": reranker_model,
        "reranker_revision": reranker_revision,
        "device": device,
        "embedding_max_tokens": embedder.max_seq_length,
        "reranker_max_tokens": 512,
        "model_load_seconds": time.perf_counter() - started,
        "library_versions": {
            name: version(name) for name in ("sentence-transformers", "transformers", "torch")
        },
    }
    return {
        "raw_dense": RawHistoryRAG(embed, config=config, model_info=model_info),
        "raw_dense_reranked": RawHistoryRAG(embed, rerank, config=config, model_info=model_info),
    }, model_info
