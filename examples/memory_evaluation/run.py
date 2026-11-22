"""Compare supplied L3 artifacts and history, optionally using local Ollama."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import tiktoken

from deeptutor.services.memory.evaluation import (
    Adapter,
    ReaderResult,
    evaluate,
    lexical_top2,
    load_cases,
    memory_snapshot,
    raw_recent,
)

READER_PROMPT = (
    "Answer the question using only the supplied evidence. Prefer the latest explicit correction. "
    "Put only the requested fact in the answer field. Use UNKNOWN when the fact is absent."
)
READER_OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 256, "num_ctx": 4096}
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"  # pragma: allowlist secret
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANKER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"  # pragma: allowlist secret


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=512)
    parser.add_argument(
        "--raw-rag",
        action="store_true",
        help="Opt in to local dense retrieval and reranking models",
    )
    parser.add_argument("--retrieval-candidates", type=int, default=128)
    parser.add_argument("--retrieval-top-k", type=int, default=15)
    parser.add_argument("--window-chars", type=int, default=600)
    parser.add_argument("--window-overlap", type=int, default=150)
    parser.add_argument("--retrieval-device", default="cpu")
    parser.add_argument("--embedding-model", default=EMBEDDING_MODEL)
    parser.add_argument("--embedding-revision")
    parser.add_argument("--reranker-model", default=RERANKER_MODEL)
    parser.add_argument("--reranker-revision")
    parser.add_argument(
        "--model", help="Optional installed local Ollama model; omission makes no reader calls"
    )
    args = parser.parse_args()
    if args.budget < 1:
        parser.error("budget must be positive")
    try:
        cases = load_cases(args.cases)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    metadata = {}
    reader = None
    if args.model:
        try:
            response = httpx.get(
                "http://127.0.0.1:11434/api/tags",
                timeout=5,
                trust_env=False,
                follow_redirects=False,
            )
            response.raise_for_status()
            models = response.json()["models"]
            model = next((item for item in models if item["name"] == args.model), None)
            if model is None:
                parser.error(f"Local model {args.model!r} is not installed; pull it first")
            metadata = {
                "model": args.model,
                "model_digest": model["digest"],
                "seed": 42,
                "temperature": 0,
                "reader_prompt": READER_PROMPT,
                "provider": "local Ollama",
                "reader_options": READER_OPTIONS,
            }
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            parser.error(f"Local Ollama is unavailable: {exc}")

        async def local_reader(context: str, query: str) -> ReaderResult:
            def request_answer() -> ReaderResult:
                payload = {
                    "model": args.model,
                    "stream": False,
                    "format": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                    "options": READER_OPTIONS,
                    "messages": [
                        {"role": "system", "content": READER_PROMPT},
                        {"role": "user", "content": f"EVIDENCE:\n{context}\nQUESTION:\n{query}"},
                    ],
                }
                response = httpx.post(
                    "http://127.0.0.1:11434/api/chat",
                    json=payload,
                    timeout=180,
                    trust_env=False,
                    follow_redirects=False,
                )
                response.raise_for_status()
                result = response.json()
                return ReaderResult(
                    json.loads(result["message"]["content"])["answer"],
                    {
                        "input_tokens": result.get("prompt_eval_count"),
                        "output_tokens": result.get("eval_count"),
                    },
                )

            return await asyncio.to_thread(request_answer)

        reader = local_reader
    encoding = tiktoken.get_encoding("cl100k_base")
    adapters: dict[str, Adapter] | None = None
    if args.raw_rag:
        from deeptutor.services.memory.evaluation_rag import (
            RetrievalConfig,
            local_sentence_transformer_adapters,
        )

        embedding_revision = args.embedding_revision or (
            EMBEDDING_REVISION if args.embedding_model == EMBEDDING_MODEL else None
        )
        reranker_revision = args.reranker_revision or (
            RERANKER_REVISION if args.reranker_model == RERANKER_MODEL else None
        )
        if not embedding_revision or not reranker_revision:
            parser.error("Custom retrieval models require explicit full commit revisions")
        try:
            config = RetrievalConfig(
                args.window_chars,
                args.window_overlap,
                args.retrieval_candidates,
                args.retrieval_top_k,
            )
            retrieval_adapters, model_info = local_sentence_transformer_adapters(
                config,
                embedding_model=args.embedding_model,
                embedding_revision=embedding_revision,
                reranker_model=args.reranker_model,
                reranker_revision=reranker_revision,
                device=args.retrieval_device,
            )
        except ImportError as exc:
            parser.error(
                "Raw-RAG needs optional rag-rerank dependencies and "
                f"sentence-transformers>=5.1.2,<6: {exc}"
            )
        except (OSError, ValueError) as exc:
            parser.error(f"Raw-RAG model/configuration setup failed: {exc}")
        metadata["retrieval_models"] = model_info
        adapters = {
            "raw_recent": raw_recent,
            "lexical_top2": lexical_top2,
            "native_l3_snapshot": memory_snapshot,
            **retrieval_adapters,
        }
    report = asyncio.run(
        evaluate(
            cases,
            count_tokens=lambda text: len(encoding.encode(text, disallowed_special=())),
            tokenizer="cl100k_base",
            budget=args.budget,
            reader=reader,
            adapters=adapters,
        )
    )
    report.update(metadata)
    report.update(
        cases_sha256=hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        cases_filename=args.cases.name,
        limitations=[
            "Development fixtures, not an independent benchmark",
            "Hand-authored snapshots; no production consolidation measured",
            "Lexical top-two is an ablation; dense baselines require explicit --raw-rag",
            "Dense retrieval uses character windows; this is not a paper reproduction",
            "Chunk source-ID coverage is not fact/span recall or answer accuracy",
            "Normalized exact match and lexical F1 are not semantic judgments",
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"]))
    if any(row["error"] for row in report["rows"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
