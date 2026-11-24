---
title: Knowledge Center
description: Create, version, sync, inspect, and reuse the Knowledge Bases that ground Home, Partners, Learning notebook, Books, and other learning surfaces.
quadrant: how-to
---

The Knowledge Center is where you build and manage the document libraries behind **RAG**. A knowledge base (KB) can ground Home turns, Learning notebook edits, Book generation, and Partner conversations. This page focuses on the KB lifecycle; engine architecture and selection live under [RAG Integration](/ecosystem/rag-integration/).

## Where it is

Open **Resources → Knowledge Center** from the left sidebar. Two tabs keep its responsibilities separate: **Knowledge bases** is the lifecycle surface for libraries you built, while **Knowledge engines** shows every retrieval integration available to this deployment.

![Knowledge Center](/screenshots/dev/knowledge.png)

## Choose the RAG integration

Every KB is bound to one retrieval integration. Open **Knowledge engines** to see the catalog grouped as Local, Server, Cloud, and External knowledge sources. Each card reports **Ready**, **Needs key**, **Needs setup**, or **Not installed** before you create a base. Open [RAG Integration](/ecosystem/rag-integration/) for the full comparison, including the distinct PageIndex OSS and PageIndex Cloud contracts.

## Create a knowledge base

Press **New knowledge base** for an indexed library. The first choice is:

- **Create new** — upload documents and build a fresh index.
- **Link existing** — reuse an index you already built elsewhere; DeepTutor reads it in place with no upload and no re-index.

Then name the KB, pick the **index engine**, retrieval mode, and storage workspace (account library or a ready workspace), and add documents. PageIndex Cloud uploads to a hosted service; PageIndex OSS builds locally. For an existing ZIM, use **Knowledge engines → Kiwix / ZIM → Connect archive** with a kiwix-serve URL and one archive; articles stay on the server. A KB can also track **GitHub sources** (repo, branch, path, glob) or bounded **Web sources** (URL, depth, page count). Sync either type to reconcile changed content.

![Create a knowledge base](/screenshots/dev/knowledge-create.png)

## Inside a knowledge base

Open a KB to manage it. The panel pairs a **document viewer** with adaptive navigation:

| Tab | What it does |
| --- | --- |
| **Files** | Source documents, extraction status, previews, and **Source visual coverage** inspection; remove files even from an error-state KB without rebuilding. |
| **Add documents** | Upload more PDFs, Office files, Markdown, text, code, or data. |
| **Linked folders** | Link a local folder, then sync on demand to index new and changed files. |
| **GitHub** | Manage repository sources and sync. |
| **Web** | Manage bounded site crawls, synced on demand or every 1–168 hours. |
| **Index versions** | Flat `version-N` storage directories with engine-specific signatures and build metadata; embedding and LightRAG indexing-model details appear where applicable. |
| **Settings** | Embedding model, chunking, retrieval parameters, engine metadata, default selection, and a reviewed workspace move for eligible owned KBs. |


MarginNote instead shows **Devices** and **Settings** because its paired add-on pushes the data. Kiwix shows **Articles** and **Settings**; search a ZIM article there and open it in Immersive Reading.

**Versioning model.** Re-indexing writes a new `version-N` directory and retains prior versions. LlamaIndex publishes the new index only after verification; completing a processing phase alone does not make it ready.

## Document parsing

**Settings → Knowledge & documents → Document Parsing** selects text extraction and parser-dependent retention of original figures. Retained PDFs also support exact page or region inspection. **Local model downloads are off by default** and require your explicit permission.

![Document parsing settings](/screenshots/dev/settings-parsing.png)

| Engine | Trade-off |
| --- | --- |
| **Text-only** (built in) | Plain text extraction for PDF/Office/text. No package, no download, no layout structure. |
| **MinerU** | Multimodal parsing (layout, tables, formulas). Local CLI downloads models, or use the cloud API, which splits oversized PDFs and reuses completed parts on retry. Accepts PDF; BMP, GIF, JP2, JPEG, JPG, PNG, TIFF, WebP; DOCX, PPTX, XLSX. |
| **Docling** | Structured conversion (layout/tables). Downloads local models on first run, or runs in **remote** mode against a Docling Serve server (no local install or models). PDF/Office/HTML/images. |
| **Tika** | Remote-only: points at the Apache Tika server configured in Settings → Document Parsing, with no local install or models. Broad format support → Markdown. |
| **markitdown** | Lightweight, no downloads, broad format support → Markdown. `pip install deeptutor[parse-markitdown]`. |
| **PyMuPDF4LLM** | Lightweight, no downloads or CUDA. Converts PDF, e-books, XPS, images, text, and Markdown while extracting images. `pip install deeptutor[parse-pymupdf4llm]`. |
| **LiteParse** | Lightweight structured parsing, no local model downloads. `pip install deeptutor[parse-liteparse]`. |

## CLI mirror

```bash
deeptutor kb list
deeptutor kb create physics --doc chapter1.pdf
deeptutor kb create textbooks --docs-dir ./pdfs
deeptutor kb connect-kiwix wiki --server-url http://localhost:8080 --zim-name wikipedia_en
deeptutor kb add physics --doc chapter2.pdf
deeptutor kb add-github-source physics --repo owner/repo --branch main --path docs --glob '*.md'
deeptutor kb add-web-source physics --url https://docs.example.com --max-depth 3 --max-pages 200
deeptutor kb list-sources physics
deeptutor kb sync physics
deeptutor kb search physics "What is angular momentum?"
deeptutor kb eval physics --dataset physics-qa.jsonl --top-k 5 --format json
deeptutor kb set-default physics
```

## Tips

- Configure an embedding provider in **Settings → Embedding models** before building serious KBs.
- If you change embedding models, re-index rather than mixing vector spaces; a native LightRAG index records its embedding and refuses queries until you restore or rebuild.
- Use **Indexing recovery details** after interruption: retries reuse validated parsing and compatible LlamaIndex embedding checkpoints; uncheckpointed work restarts. Cancellation waits for a safe boundary.
- Keep a small test KB for Partner/channel smoke tests.
- For Docker, persist the whole `data/` tree so KB versions survive container restarts.

## Use the base in a workspace

Create the KB in the intended workspace and wait until ready. Untouched Chat conversations inherit ready workspace assignments or the default KB; the knowledge picker overrides them. Test it with a question whose answer you can verify in the source: “Which assumptions does chapter 2 make about stationarity? Cite the source.” Inspect the retrieved passages before expanding the library. A file uploaded to a conversation is not automatically added to a KB.

Assigned resources determine which bases are available to a workspace. Sharing availability is different from moving ownership. Where a base's Settings offers a workspace move, review its preview, assignments and blockers before confirming. A KB can support source-grounded Chat, Books and other eligible activities, while Reading is the better fit when you want to inspect the document itself beside the tutor.

## See also

- [RAG Integration](/ecosystem/rag-integration/) — compare the knowledge engines behind a KB
- [Home](/explore/chat-workspace/) — attach KBs to a turn
- [Immersive Reading](/explore/reading/) — read one document instead of indexing a corpus
- [Books](/explore/book/) — compile learning material from KBs
- [Partners](/explore/partners/) — copy KBs into partner workspaces
- [Settings](/explore/settings/) — embedding providers and parsing engines
