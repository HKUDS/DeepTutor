# Memory snapshot evaluation

This is an evaluation-only starting point for [RFC #2057](https://github.com/HKUDS/DeepTutor/issues/2057). It compares recent raw history, a lexical top-two ablation, and supplied L3 snapshots. The snapshot adapter creates a temporary workspace, writes only the supplied artifacts through `MemoryStore.overwrite_doc`, and reads them through the same `read_l3_concat` facade used by memory tools. Each case gets new storage, and the memory-path override is restored even on failure.

Snapshots in the sample are explicitly hand-authored synthetic development data. They test the evaluation contract, **not** the quality of L1 → L2 → L3 consolidation. No production settings, active user memory, or model configuration is changed. The lexical adapter remains an ablation; optional dense retrieval and cross-encoder baselines are described below.

## Install and run

From a source checkout with Python 3.11+ in an activated virtual environment:

```bash
python -m pip install -e . pytest pytest-asyncio
python -m pytest tests/services/memory/test_evaluation.py -q
python examples/memory_evaluation/run.py --cases tests/fixtures/memory_evaluation/cases.jsonl --output /path/to/preflight.json
```

The default run prepares evidence without calling a reader. Its answer metrics are null, not zero or perfect accuracy. `tiktoken` is an existing base dependency; its first `cl100k_base` initialization may download tokenizer data. No language-model request is made by the preflight.

To exercise the reader boundary, start a local Ollama server and explicitly install a suitable model, then add `--model MODEL_NAME`. The script checks the local model catalog and calls only `127.0.0.1:11434`; it does not discover cloud credentials or use DeepTutor's configured provider. A catalog entry can still be broken or incompatible; per-case failures remain visible in the report. Use a capable reader for an actual quality comparison.

## Case format

Each JSONL record contains:

- `case_id`, `category`, `query`: nonempty strings.
- `history`: chronological `{id, timestamp, text}` records with unique IDs and timezone-aware ISO timestamps.
- `question_time`: history after this time is excluded.
- `memory_as_of`: asserted snapshot timestamp, no later than the question. Dataset authors must independently verify the snapshot's contents/provenance; this field cannot prove that its text contains no future information.
- `l3_snapshot`: mapping of `recent`, `profile`, `scope`, or `preferences` to Markdown. Omitted slots are absent, not inherited from another case.
- `answerable`, `expected_answer`, optional `answer_aliases`, and `evidence_ids`: gold labels. Gold evidence must refer to visible history. Unanswerable cases have an empty expected answer, no aliases/evidence, and expect `UNKNOWN` from the reader.

Adapters receive a frozen `CaseInput` without gold labels. The reader receives only the packed evidence and query. Declare aliases and the scoring policy before a measured run; do not add aliases after inspecting test outputs to improve scores.

## Budgets and metrics

All adapters share one greedy whole-span packing policy and named tokenizer. The default budget is 512 `cl100k_base` **reference-tokenizer** tokens including evidence labels. It excludes the question, system instructions, and generated output. This reference tokenizer is not necessarily an Ollama model's tokenizer; provider-reported usage is recorded separately, never presented as the reference count. Match the counter to the reader tokenizer for provider-specific budget claims.

An oversized span is skipped, not cut mid-record. Raw/lexical spans are individual timestamped history events; a native L3 span is the complete `read_l3_concat` tool response. This granularity difference is explicit: if a native response exceeds the budget, it is omitted, not silently replaced with a custom memory read policy. Inspect `offered_ids`, `omitted_ids`, `selected_ids`, and `evidence_context` before interpreting quality.

The report includes normalized exact match over predeclared aliases and bag-of-word token F1. F1 measures lexical overlap, not semantic truth. Common mathematical operators are retained, so a minus sign or equality sign is not silently discarded during normalization. In particular, an answer negating the gold string can have high F1 and still fail exact match. Missing/empty answers are failures, not correct abstentions.

`source_id_recall` measures retained original history IDs for history adapters. Chunked adapters map selected windows back to unique events via `AdapterResult.source_ids`; `selected_source_ids` records that projection after budget packing. Retaining any chunk of an event counts as retaining its ID: this is **event-ID coverage, not fact/span recall**. It is null for snapshots: a footnote/reference inside a memory document does not prove that the necessary fact or relationship survived. Unanswerable cases have no source-recall score.

Failures retain their evidence and error. Summaries give scored and failed counts, scored-only exact match, and an all-case exact-match rate that counts failed calls in the denominator. When no answers were scored, rates are null. The CLI exits 2 if any case fails. Evidence preparation and reader latency are recorded separately; snapshot restoration time is not LLM consolidation cost.

## Extending to a research comparison

Pass custom asynchronous adapters/readers to `deeptutor.services.memory.evaluation.evaluate`. Keep the `CaseInput`/`AdapterResult` and `ReaderResult` boundaries; reuse the same reader, token counter, and budget across adapters. Record adapter configuration and versions alongside the report.

A full comparison still needs generated artifacts from actual consolidation, independently reviewed held-out cases, a shared reader, and ingestion/storage/query costs. The optional adapters below supply a dense/reranking baseline, not a completed comparison or reproduction of a published RAG configuration. Run those components in isolated evaluation workspaces and respect source-access/deletion rules. This example does not authorize indexing live learner histories or changing production defaults.

The tests live in `tests/services/memory/` and are collected by the normal test workflow. Sample data is shipped in `tests/fixtures/memory_evaluation/`; no personal workspace files or models are required.

## Optional raw-history dense retrieval and reranking

With Python 3.11–3.13, explicitly install the existing `rag-rerank` extra:

```bash
python -m pip install -e '.[rag-rerank]' 'sentence-transformers>=5.1.2,<6'
python -m pytest tests/services/memory/test_evaluation.py tests/services/memory/test_evaluation_rag.py -q
python examples/memory_evaluation/run.py --cases tests/fixtures/memory_evaluation/cases.jsonl --output /path/to/raw-rag.json --raw-rag
```

The flag adds `raw_dense` and `raw_dense_reranked` alongside the existing adapters. Default preflight and unit tests do not import model SDKs or download weights. The opt-in first run downloads two public models; it defaults to CPU, never invokes a generation provider, and sets `token=False`, `trust_remote_code=False`, and safetensors-only weight loading. It uses these immutable revisions:

| Role | Model | Revision |
| --- | --- | --- |
| Embedder | `sentence-transformers/all-MiniLM-L6-v2` | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| Cross-encoder | `cross-encoder/ms-marco-MiniLM-L6-v2` | `233902d25c440f23af6f7d6e94d2946bac0bee0a` |

The defaults are small English similarity/ranking models for an accessible baseline, not a claim of optimal models. Override model IDs with `--embedding-model` / `--reranker-model` and supply full immutable commit SHAs with the corresponding `--embedding-revision` / `--reranker-revision`. Record the report's library versions; installing an optional extra alone does not lock the complete environment. After downloading weights, `HF_HUB_OFFLINE=1` can enforce cached-only model loading. GPU use is explicit via `--retrieval-device cuda` and requires a compatible PyTorch install.

For each case and adapter, only the loader's visible pre-question history is windowed in memory. Defaults are 600 characters with 150-character overlap (`--window-chars`, `--window-overlap`), preserving timestamps and offsets. Empty history needs no embeddings. Normalized cosine similarity retrieves up to 128 candidates (`--retrieval-candidates`); the cross-encoder optionally reorders those candidates, then offers the top 15 (`--retrieval-top-k`) to the shared whole-span token packer. Dense ties prefer later chronological windows; reranking ties retain dense order. Chunk IDs encode history index/start/end, and source mapping preserves event provenance. Overlong embedding or paired reranker inputs fail the case with a reduce-window/query message, rather than silently truncating evidence.

The report records candidate scores, reranker scores in candidate order, configuration, pinned model revisions, versions, and separate corpus embedding/query embedding/rerank timings. Each adapter rebuilds its own index for isolation; corpus embedding is rebuild cost, not steady-state query latency or production ingestion cost. Model load time is recorded separately and can include downloads. No persistent vector database or cross-case cache is used.

Use `--model` only when deliberately running the same installed Ollama reader across all adapters. Omitting it leaves answer metrics null even with real retrieval models. The supplied eleven synthetic cases are development checks: source coverage and successful execution cannot establish that dense retrieval, reranking, or layered memory improves answers. A held-out study should predeclare cases, reader, model versions, budgets, granularity differences, and outcome metrics before drawing conclusions.
