"""Isolated CrossEncoder worker for the LlamaIndex reranking pipeline.

macOS wheels for ``faiss-cpu`` and ``torch`` each bundle an LLVM ``libomp.dylib``
runtime. Loading both in one process aborts with ``OMP: Error #15`` (and setting
``KMP_DUPLICATE_LIB_OK=TRUE`` can deadlock CPU reductions). Running
``sentence_transformers`` in this ``python -m`` worker keeps PyTorch out of the
FAISS host process while preserving an in-worker LRU model cache across queries.
"""

from __future__ import annotations

from collections import OrderedDict
import json
import math
import os
import sys
from typing import Any

_MODEL_CACHE: OrderedDict[str, Any] = OrderedDict()
_MODEL_CACHE_MAXSIZE = 2


def _identity_logits(scores: Any) -> Any:
    """Request raw cross-encoder logits from SentenceTransformers."""
    return scores


def _get_model(model_name: str) -> tuple[Any | None, dict[str, Any] | None]:
    cached = _MODEL_CACHE.get(model_name)
    if cached is not None:
        _MODEL_CACHE.move_to_end(model_name)
        return cached, None

    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        return None, {"ok": False, "kind": "import_error", "error": str(exc)}

    try:
        model = CrossEncoder(model_name)
    except Exception as exc:
        return None, {"ok": False, "kind": "load_error", "error": str(exc)}

    _MODEL_CACHE[model_name] = model
    _MODEL_CACHE.move_to_end(model_name)
    while len(_MODEL_CACHE) > _MODEL_CACHE_MAXSIZE:
        _MODEL_CACHE.popitem(last=False)
    return model, None


def _handle_request(request: dict[str, Any]) -> dict[str, Any]:
    model_name = str(request.get("model_name") or "")
    raw_pairs = request.get("pairs") or []
    pairs = [(str(item[0]), str(item[1])) for item in raw_pairs]

    model, error = _get_model(model_name)
    if error is not None or model is None:
        return error or {"ok": False, "kind": "load_error", "error": "model unavailable"}

    try:
        raw_scores = model.predict(pairs, activation_fct=_identity_logits)
        scores = [float(value) if math.isfinite(float(value)) else None for value in raw_scores]
    except Exception as exc:
        return {"ok": False, "kind": "score_error", "error": str(exc)}

    return {"ok": True, "scores": scores}


def main() -> int:
    ipc_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError as exc:
                response: dict[str, Any] = {
                    "ok": False,
                    "kind": "protocol_error",
                    "error": str(exc),
                }
            else:
                response = _handle_request(request)
            ipc_out.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
            ipc_out.flush()
    finally:
        ipc_out.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(main())
