"""Optional cross-encoder reranking for the LlamaIndex pipeline."""

from __future__ import annotations

import atexit
from collections import OrderedDict, deque
from contextlib import suppress
from dataclasses import dataclass
import importlib.util
import json
import logging
import math
import os
import subprocess  # nosec B404 - fixed interpreter/module argv, no shell
import sys
from threading import Lock, Thread, Timer
from time import monotonic
from typing import Any, Callable

from llama_index.core.schema import MetadataMode, NodeWithScore

logger = logging.getLogger(__name__)

_RERANKER_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_RERANKER_CACHE_LOCK = Lock()
_RERANKER_CACHE_MAXSIZE = 2

_WORKER_MODULE = "deeptutor.services.rag.pipelines.llamaindex.rerank_worker"
_WORKER_IDLE_TIMEOUT_SECONDS = 300.0
_ERROR_TAIL_LINES = 20
_WORKER_LOCK = Lock()


@dataclass
class _WorkerHandle:
    process: subprocess.Popen[str]
    stderr_tail: deque[str]
    stderr_thread: Thread


_WORKER: _WorkerHandle | None = None
_WORKER_IDLE_TIMER: Timer | None = None
_WORKER_LAST_USED = 0.0


def _cancel_idle_timer_locked() -> None:
    global _WORKER_IDLE_TIMER
    if _WORKER_IDLE_TIMER is not None:
        _WORKER_IDLE_TIMER.cancel()
        _WORKER_IDLE_TIMER = None


def _stop_worker_locked() -> None:
    global _WORKER
    _cancel_idle_timer_locked()
    handle = _WORKER
    _WORKER = None
    if handle is None:
        return

    process = handle.process
    if process.stdin is not None:
        with suppress(OSError):
            process.stdin.close()
    if process.poll() is None:
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    handle.stderr_thread.join(timeout=0.2)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            with suppress(OSError):
                stream.close()


def _stop_worker_if_idle() -> None:
    with _WORKER_LOCK:
        if _WORKER is None:
            return
        if monotonic() - _WORKER_LAST_USED >= _WORKER_IDLE_TIMEOUT_SECONDS:
            _stop_worker_locked()


def _schedule_idle_stop_locked() -> None:
    global _WORKER_IDLE_TIMER, _WORKER_LAST_USED
    _cancel_idle_timer_locked()
    _WORKER_LAST_USED = monotonic()
    timer = Timer(_WORKER_IDLE_TIMEOUT_SECONDS, _stop_worker_if_idle)
    timer.daemon = True
    timer.start()
    _WORKER_IDLE_TIMER = timer


def _drain_stderr(stream: Any, tail: deque[str]) -> None:
    with suppress(OSError, ValueError):
        for raw_line in stream:
            line = raw_line.strip()
            if line:
                tail.append(line)


def _ensure_worker_locked() -> _WorkerHandle:
    global _WORKER
    if _WORKER is not None and _WORKER.process.poll() is None:
        return _WORKER
    _stop_worker_locked()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(  # noqa: S603 - fixed module argv and shell=False
        [sys.executable, "-m", _WORKER_MODULE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    tail: deque[str] = deque(maxlen=_ERROR_TAIL_LINES)
    reader = Thread(
        target=_drain_stderr,
        args=(process.stderr, tail),
        name="deeptutor-rerank-stderr",
        daemon=True,
    )
    reader.start()
    _WORKER = _WorkerHandle(process=process, stderr_tail=tail, stderr_thread=reader)
    return _WORKER


def _log_worker_failure(
    kind: str,
    model_name: str,
    candidate_count: int,
    detail: str,
) -> None:
    if kind == "import_error":
        logger.warning(
            "Reranker model %r is configured, but sentence-transformers is not installed; "
            "using embedding retrieval unchanged.",
            model_name,
        )
    elif kind == "load_error":
        logger.warning(
            "Failed to load reranker model %r; using embedding retrieval unchanged: %s",
            model_name,
            detail,
        )
    else:
        logger.warning(
            "Reranker model %r failed while scoring %d candidates; "
            "using embedding retrieval unchanged: %s",
            model_name,
            candidate_count,
            detail,
        )


def _score_in_worker(
    model_name: str,
    pairs: list[tuple[str, str]],
) -> list[float | None] | None:
    with _WORKER_LOCK:
        _cancel_idle_timer_locked()
        try:
            handle = _ensure_worker_locked()
            assert handle.process.stdin is not None
            assert handle.process.stdout is not None
            payload = json.dumps(
                {"model_name": model_name, "pairs": pairs},
                ensure_ascii=False,
            )
            handle.process.stdin.write(payload + "\n")
            handle.process.stdin.flush()
            raw_line = handle.process.stdout.readline()
        except OSError as exc:
            _stop_worker_locked()
            logger.warning(
                "Could not run isolated reranker worker for model %r; "
                "using embedding retrieval unchanged: %s",
                model_name,
                exc,
            )
            return None

        if not raw_line:
            tail = list(handle.stderr_tail)
            _stop_worker_locked()
            detail = "\n".join(tail or list(handle.stderr_tail)) or "worker exited without output"
            logger.warning(
                "Reranker worker exited unexpectedly for model %r; "
                "using embedding retrieval unchanged: %s",
                model_name,
                detail,
            )
            return None

        try:
            response = json.loads(raw_line)
        except ValueError as exc:
            _stop_worker_locked()
            logger.warning(
                "Reranker worker returned invalid output for model %r; "
                "using embedding retrieval unchanged: %s",
                model_name,
                exc,
            )
            return None

        _schedule_idle_stop_locked()

    if not isinstance(response, dict) or not response.get("ok"):
        kind = str(response.get("kind") or "") if isinstance(response, dict) else ""
        detail = str(response.get("error") or "unknown error") if isinstance(response, dict) else ""
        _log_worker_failure(kind, model_name, len(pairs), detail)
        return None

    scores = response.get("scores")
    return scores if isinstance(scores, list) else None


def clear_reranker_cache() -> None:
    """Drop cached reranker models (used by tests and settings changes)."""
    with _RERANKER_CACHE_LOCK:
        _RERANKER_CACHE.clear()
    with _WORKER_LOCK:
        _stop_worker_locked()


def _cross_encoder(
    model_name: str,
    loader: Callable[[str], Any],
) -> Any | None:
    with _RERANKER_CACHE_LOCK:
        cached = _RERANKER_CACHE.get(model_name)
        if cached is not None:
            _RERANKER_CACHE.move_to_end(model_name)
            return cached

    try:
        model = loader(model_name)
    except ImportError:
        logger.warning(
            "Reranker model %r is configured, but sentence-transformers is not installed; "
            "using embedding retrieval unchanged.",
            model_name,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Failed to load reranker model %r; using embedding retrieval unchanged: %s",
            model_name,
            exc,
        )
        return None

    with _RERANKER_CACHE_LOCK:
        _RERANKER_CACHE[model_name] = model
        _RERANKER_CACHE.move_to_end(model_name)
        while len(_RERANKER_CACHE) > _RERANKER_CACHE_MAXSIZE:
            _RERANKER_CACHE.popitem(last=False)
    return model


def _sigmoid(value: float) -> float:
    """Convert cross-encoder logits to a stable 0..1 source score."""
    try:
        if value >= 0:
            return 1.0 / (1.0 + math.exp(-value))
        exp_value = math.exp(value)
        return exp_value / (1.0 + exp_value)
    except (OverflowError, ValueError):
        return 1.0 if value > 0 else 0.0


def _identity_logits(scores: Any) -> Any:
    """Request raw cross-encoder logits from SentenceTransformers."""
    return scores


def rerank_nodes(
    query: str,
    nodes: list[Any],
    *,
    top_k: int,
    model_name: str,
    loader: Callable[[str], Any] | None = None,
) -> list[Any]:
    """Rerank LlamaIndex results and return at most ``top_k`` nodes.

    Missing optional dependencies and model-load failures are non-fatal: the
    first-stage ordering is returned so saved knowledge remains searchable.
    """
    requested = max(1, int(top_k))
    if not query or not nodes or not model_name:
        return nodes[:requested]

    pairs = [(query, result.node.get_content(metadata_mode=MetadataMode.LLM)) for result in nodes]
    if loader is None:
        if importlib.util.find_spec("sentence_transformers") is None:
            logger.warning(
                "Reranker model %r is configured, but sentence-transformers is not installed; "
                "using embedding retrieval unchanged.",
                model_name,
            )
            return nodes[:requested]
        raw_scores = _score_in_worker(model_name, pairs)
        if raw_scores is None:
            return nodes[:requested]
    else:
        model = _cross_encoder(model_name, loader)
        if model is None:
            return nodes[:requested]
        try:
            raw_scores = model.predict(pairs, activation_fct=_identity_logits)
        except Exception as exc:
            logger.warning(
                "Reranker model %r failed while scoring %d candidates; "
                "using embedding retrieval unchanged: %s",
                model_name,
                len(nodes),
                exc,
            )
            return nodes[:requested]

    ranked = sorted(
        (
            (index, float(score))
            for index, score in enumerate(raw_scores)
            if score is not None and math.isfinite(float(score))
        ),
        key=lambda item: item[1],
        reverse=True,
    )[:requested]

    return [NodeWithScore(node=nodes[index].node, score=_sigmoid(score)) for index, score in ranked]


atexit.register(clear_reranker_cache)

__all__ = ["clear_reranker_cache", "rerank_nodes"]
