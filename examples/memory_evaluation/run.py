"""Compare supplied L3 artifacts and history, optionally using local Ollama."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import tiktoken

from deeptutor.services.memory.evaluation import ReaderResult, evaluate, load_cases

READER_PROMPT = (
    "Answer the question using only the supplied evidence. Prefer the latest explicit correction. "
    "Put only the requested fact in the answer field. Use UNKNOWN when the fact is absent."
)
READER_OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 256, "num_ctx": 4096}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=512)
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
    report = asyncio.run(
        evaluate(
            cases,
            count_tokens=lambda text: len(encoding.encode(text, disallowed_special=())),
            tokenizer="cl100k_base",
            budget=args.budget,
            reader=reader,
        )
    )
    report.update(metadata)
    report.update(
        cases_sha256=hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        cases_filename=args.cases.name,
        limitations=[
            "Development fixtures, not an independent benchmark",
            "Hand-authored snapshots; no production consolidation measured",
            "Lexical retrieval is not dense retrieval plus reranking",
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
