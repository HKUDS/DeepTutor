---
name: deeptutor-knowledge-bases
description: >-
  Build and use DeepTutor knowledge bases for RAG: configure an embedding
  model, create a KB from documents or a folder, add documents, search it,
  evaluate retrieval quality with a QA set, and use it in chat and
  capabilities like deep_solve and deep_research. Use when a user wants
  DeepTutor to answer from their own materials.
---

# DeepTutor knowledge bases

References: `SKILL.md` (Knowledge Bases), `docs-for-dev/AGENT_SETUP.md`
(embedding setup), `docs-for-dev/KNOWLEDGE_MIGRATION.md`,
`docs-for-dev/INDEXING_RECOVERY.md`.

## Prerequisites

The knowledge and parsing modules must be ready (`deeptutor module list`)
and an embedding model configured:

```json
{
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "api_key_env": "DEEPTUTOR_SETUP_EMBEDDING_KEY",
    "dimension": 1536
  }
}
```

```bash
deeptutor config apply embedding.json --check && deeptutor config apply embedding.json
```

Embedding `base_url`, when needed, is the full endpoint (e.g.
`https://api.openai.com/v1/embeddings`). `doctor --online` only probes the
LLM, so test embedding by ingesting and searching a small, user-approved
document. Changing an existing KB's embedding model or dimension means a
rebuild; plan it with the user.

## Build and maintain

```bash
deeptutor kb create physics --doc ch1.pdf --doc ch2.pdf
deeptutor kb create papers --docs-dir ./papers
deeptutor kb add physics --doc ch3.pdf
deeptutor kb list --format json
deeptutor kb info physics
deeptutor kb set-default physics
deeptutor kb delete physics --force       # irreversible; confirm first
```

## Search and evaluate

```bash
deeptutor kb search physics "Newton's third law" --mode hybrid --format json
deeptutor kb eval physics --dataset qa.jsonl --top-k 5 --mode hybrid --save report.json
```

`qa.jsonl` lines look like `{"query": "...", "gold": ["..."]}`; the report
gives Recall@k, Precision@k, nDCG@k, MRR, MAP and Hit@k per case and
averaged. Use it before and after changing chunking or embedding models.

## Use in chat and capabilities

```bash
deeptutor run chat "Explain Newton's third law" --kb physics
deeptutor chat --kb physics --tool web_search
deeptutor run deep_solve "Solve x^2 = 4" --kb textbook
deeptutor run deep_research "Attention mechanisms" --kb papers --config mode=report --config depth=standard
deeptutor run deep_question "Thermodynamics" --kb physics --config num_questions=5
```

`--kb` is repeatable. In the REPL, `/kb <name>` sets the KB and `/kb none`
clears it.
