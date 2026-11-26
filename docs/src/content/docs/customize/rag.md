---
title: RAG Integration
description: Choose how DeepTutor retrieves from local indexes, agentic document trees, remote knowledge services, and live study libraries.
quadrant: how-to
---

DeepTutor treats retrieval as an ecosystem boundary rather than one hard-coded vector store. A Knowledge Base in the [Knowledge Center](/learning-workspace/knowledge/) is the user-facing container; its **RAG integration** decides how material is indexed, queried, cited, and kept in sync.

## Available integrations

![Knowledge Center](/screenshots/dev/knowledge.png)

| Integration | Retrieval model | Best fit |
|---|---|---|
| **LlamaIndex** | Local vectors, with BM25 hybrid retrieval when available | Default local RAG that works out of the box |
| **PageIndex OSS** | Local agentic, vectorless traversal of a document tree | Private reasoning retrieval with page-level citations |
| **GraphRAG** | Local knowledge graph with global/local/drift/basic modes | Cross-document relationships and corpus-level questions |
| **LightRAG** | Local graph + vector retrieval in naive/local/global/hybrid/mix modes | Lightweight graph-aware retrieval |
| **LightRAG Server** | HTTP queries against an existing standalone server | Reuse remote LightRAG infrastructure without a local index |
| **WeKnora** | HTTP retrieval from an existing self-hosted knowledge base | Reuse WeKnora without copying documents or building a local index |
| **PageIndex Cloud** | Hosted upload plus MCP-backed document traversal | Managed agentic retrieval without a local build |
| **Tencent IMA** | OpenAPI access to an existing IMA library | Reuse a cloud knowledge library and write notes or URLs back |
| **MarginNote 4** | Paired-device sync of notes, excerpts, cards, and mind maps | Retrieve from an existing study workflow |
| **Obsidian** | Live navigation and note writing inside a vault | Work directly in a local knowledge graph with no upload or index |

The UI groups LlamaIndex, PageIndex OSS, GraphRAG, and LightRAG under **Local**; LightRAG Server under **Server**; PageIndex Cloud, Tencent IMA, and WeKnora under **Cloud**; and Obsidian plus MarginNote 4 under **External knowledge sources**. Cards show **Ready**, **Needs key**, **Needs setup**, or **Not installed**, so dependencies stay visible before you create a KB.

## Three integration contracts

Most integrations answer the ordinary `rag` tool. Three intentionally use a different contract:

- **PageIndex OSS** is agentic: a local reading loop inspects document structure, then opens only the pages it needs. PageIndex Cloud applies the same traversal shape through hosted storage and MCP tools.
- **Obsidian** has no retrieval index; its capability navigates and writes the live vault in place.
- **MarginNote 4** exposes its synced study graph through dedicated navigation tools.

Everything else in the table, including LightRAG Server and Tencent IMA, can answer ordinary RAG queries after a KB is connected.

## Installation and configuration

LlamaIndex is the default. Optional local engines are installed deliberately:

```bash
python scripts/install_extras.py graphrag
python scripts/install_extras.py rag-lightrag
```

LightRAG's extra installs the supported LightRAG SDK only; document parsing remains an independent choice under **Settings → Document Parsing**. Remote and live-library integrations are configured from their Knowledge Center cards or from the connected KB.

## Choose by ownership

- Choose a **local index** when the deployment should own both documents and retrieval state.
- Choose an **agentic tree** when page-level structure matters more than nearest-neighbor chunks.
- Choose a **remote service** when an existing RAG deployment should stay authoritative.
- Choose a **live library** when DeepTutor should work in the learner's existing knowledge system rather than copy it.

## See also

- [Knowledge Center](/learning-workspace/knowledge/) — create, version, sync, and use Knowledge Bases
- [Immersive Reading](/learning-workspace/reading/) — read one collection directly instead of indexing a corpus
- [Settings](/self-hosting/settings/) — configure embedding providers and document parsing
