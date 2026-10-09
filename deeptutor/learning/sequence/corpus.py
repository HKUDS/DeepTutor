"""Turn a RAG search result into the text a solution sequence may quote."""

from __future__ import annotations

from typing import Any

MAX_CORPUS_CHARS = 12_000

# These engines put a model-written synthesis in ``answer``. Grounding has to
# use the retrieved chunks, or a later step can "quote" something the
# retriever invented.
_SYNTHESIS_PROVIDERS = frozenset({"graphrag", "lightrag", "lightrag-server"})


def build_corpus(result: dict[str, Any]) -> str:
    """Return the passage text a generated step is allowed to cite."""
    chunks: list[str] = []
    for source in result.get("sources") or []:
        if not isinstance(source, dict):
            continue
        text = source.get("content")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    joined = "\n\n".join(chunks)
    provider = str(result.get("provider") or "")
    if provider in _SYNTHESIS_PROVIDERS:
        return joined[:MAX_CORPUS_CHARS]
    answer = result.get("content") or result.get("answer") or ""
    if not isinstance(answer, str):
        answer = ""
    answer = answer.strip()
    # LlamaIndex keeps the full node text on the answer and truncates each
    # source snippet. Other non-synthesis engines vary, so keep the longer one.
    body = answer if len(answer) > len(joined) else joined
    return (body or answer or joined)[:MAX_CORPUS_CHARS]


def source_labels(result: dict[str, Any], *, limit: int = 5) -> list[dict[str, str]]:
    """Titles only. Chunk text stays on the server with the answer key."""
    labels: list[dict[str, str]] = []
    for source in result.get("sources") or []:
        if not isinstance(source, dict):
            continue
        raw = source.get("title") or source.get("source") or ""
        if not isinstance(raw, str) or not raw.strip():
            continue
        labels.append({"title": raw.strip()[:180]})
        if len(labels) >= limit:
            break
    return labels
