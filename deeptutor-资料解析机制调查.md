# DeepTutor 资料解析机制：代码级事实调查

调查日期：2026-08-16  
调查范围：仓库真实源码、配置、依赖、调用关系与本机 `data/` 落盘  
原则：以源码为 Source of Truth；不改代码、不做架构优化、不讨论外部产品如何借鉴。

结论先说：**用户导入的原始文件不会变成一份统一的「已解析知识对象」。** 系统先把原文件原样落到 `raw/`，再按知识库绑定的 RAG 引擎走不同路径：本地引擎会经共享 `ParseService` 变成 Markdown（少数引擎还有 `blocks` + 图片），再切分、Embedding、建索引；远端/连接型知识库则几乎不解析、不落本地索引。下游消费的主通道是 `rag` 检索到的片段，不是解析后的原文。

本仓库当前 `frontend/src`（TraeWork 底盘）**没有**知识库上传 UI，`start_turn` 也不传 `knowledge_bases`。导入能力在后端 API、CLI、聊天附件、出题 WebSocket 四条链路上。本机 `data/knowledge_bases/` 有两个已创建 KB，但索引都失败，没有可用的 `version-N`，也没有 `data/parse_cache/`。

---

## 1. 端到端数据流

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 入口（四条互不合并的导入链）                                              │
│                                                                         │
│ A. Web API  POST /api/v1/knowledge/create                               │
│             POST /api/v1/knowledge/{kb}/upload                          │
│             POST /api/v1/knowledge/{kb}/reindex                         │
│             POST /api/v1/knowledge/{kb}/sync-folder/{id}                │
│             POST /api/v1/knowledge/connect-*   （指针，不解析）          │
│                                                                         │
│ B. CLI      deeptutor kb create / add                                   │
│                                                                         │
│ C. 聊天附件  WS 回合 → turn_runtime → document_extractor                │
│             （不进 KB，不经 ParseService）                               │
│                                                                         │
│ D. 出题仿题  WS question mode=upload → ParseService → LLM 抽题          │
│             （不进 KB 索引）                                             │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
                    DocumentValidator 安全校验
                    ZIP → archive_extractor 解压（压成 basename）
                    写入 <kb>/raw/（HTTP 可保留相对子目录）
                                │
                                ▼
              KnowledgeBaseInitializer / DocumentAdder
              FileTypeRouter.collect_supported_files(raw/, recursive)
                                │
                                ▼
                         RAGService
              按 kb_config.json.rag_provider 选 pipeline
                                │
        ┌───────────┬───────────┼───────────┬───────────┬──────────┐
        ▼           ▼           ▼           ▼           ▼          ▼
   LlamaIndex   GraphRAG    LightRAG    PageIndex   LightRAG    IMA
   (默认)                   (本地)      (云端)      Server
        │           │           │           │           │          │
        │      ParseService     │      上传原文件      不解析     不解析
        │      → .txt           │      到云端
        │                       │
        ▼                       ▼
   ParseService.parse()    ParseService.parse()
   markdown + images       markdown 或 blocks
        │                       │
        ▼                       ▼
   SentenceSplitter        GraphRAG build     LightRAG insert_content_list
   + Embedding             (LLM 抽实体/社区)   (LLM + 图 + 向量)
   + FAISS/SimpleStore
        │
        ▼
   <kb>/version-N/         <kb>/version-N/    <kb>/version-N/
   + metadata.json         input/*.txt +      working_dir
   + kb_config.json        graph output
        │
        ▼
   消费：chat KB seed / rag 工具 / kb_files / Book / 出题 / 研究 / 共写
```

补充：

- `deeptutor/api/routers/imports.py` 的 `POST /chat-history` **不是**资料导入，只导入 Claude Code / Codex 会话。
- 知识库 HTTP **没有** search/query 端点。检索只走 `rag_search`（chat 工具、CLI `kb search`、Book / 出题 / 共写）。
- Book 创建时的 `knowledge_bases` 只是名字列表，不读文件。
- Notebook 的 `kb_name` 只是记录字段，不触发解析或检索。

---

## 2. 支持的资料类型

权威白名单是 `FileTypeRouter`（`deeptutor/services/rag/file_routing.py`），不是 `DocumentValidator.ALLOWED_EXTENSIONS`。后者是过时兜底；上传路由会把 `FileTypeRouter.get_supported_extensions()` 传进去覆盖它。

| 分类 | 扩展名 | 后续处理 |
|---|---|---|
| 需解析 | `.pdf` `.docx` `.xlsx` `.pptx` | 走 `ParseService`（LlamaIndex / GraphRAG）；LightRAG 对**所有**文件调 `ParseService` |
| 纯文本直读 | `.txt` `.md` `.json` `.yaml` `.py` `.html` 及大量源码/配置后缀 | `FileTypeRouter.read_text_file()`，编码回退 utf-8 / gbk / latin-1 等 |
| 图片 | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.tiff` `.tif` | LlamaIndex：多模态 `ImageNode`；GraphRAG：**跳过**；LightRAG：交给当前解析引擎 |
| 容器 | `.zip` | 只作上传容器，本身不索引；成员经 `safe_extract_zip` 校验后压成 basename |

额外限制：

- **单文件上限**：`DocumentValidator.MAX_FILE_SIZE` = 200MB
- **PageIndex** 另有更窄集合：`.pdf/.md/.txt/.docx/.doc/.pptx/.ppt/.xlsx/.xls/.csv`（`pageindex/pipeline.py` `SUPPORTED_EXTENSIONS`）
- **各解析引擎自己的格式集更窄**。用户选了 MinerU 后，`.docx` 会在 `ParseService` 被拒并在 LlamaIndex 里被 skip

引擎格式（源码 `supported_formats()`）：

| 引擎 | 格式 | 本地模型 |
|---|---|---|
| `text_only`（默认） | Office + 全部文本后缀；**不含图片** | 否 |
| `mineru` | **仅 `.pdf`** | 是（或云 API） |
| `docling` | pdf/docx/pptx/xlsx/html/md/png/jpg | 是 |
| `markitdown` | pdf/office/html/csv/json/xml/txt/md/epub/常见图片 | 否 |
| `pymupdf4llm` | pdf/epub/xps/mobi/fb2/cbz | 否 |
| `liteparse` | pdf/docx/pptx/xlsx + 常见图片 | 否 |

**分流细节**：LlamaIndex / GraphRAG 进 `ParseService` 之前先被 `FileTypeRouter` 分流。只有 `.pdf/.docx/.xlsx/.pptx` 会解析；`.epub`、`.xls`、引擎能处理的图片在这两条管线里到不了 `ParseService`。`.html/.md` 也是直接读文本。LightRAG 则对传入的每个路径都调用 `parse()`。

本机 `data/user/settings/document_parsing.json` 当前引擎是 **`text_only`**。

---

## 3. 各阶段：输入 → 函数 → 逻辑 → 输出 → 下一步

### 3.1 入口 A：知识库创建 / 增量上传

**输入**：multipart 文件 + `name` + 可选 `rag_provider` + 可选 `rel_paths`

**核心**：

- `deeptutor/api/routers/knowledge.py`
  - `create_knowledge_base()` → `POST /api/v1/knowledge/create`
  - `upload_files()` → `POST /api/v1/knowledge/{kb_name}/upload`
  - `_save_uploaded_files()` / `_save_uploaded_files_off_loop()`
  - `run_initialization_task()` / `run_upload_processing_task()`
  - `reindex_knowledge_base()` / `retry_knowledge_base()` / `sync_folder()`
- `deeptutor/knowledge/initializer.py` `KnowledgeBaseInitializer`
- `deeptutor/knowledge/add_documents.py` `DocumentAdder`
- `deeptutor/utils/document_validator.py` `DocumentValidator.validate_upload_safety()`
- `deeptutor/utils/archive_extractor.py` `safe_extract_zip`

**逻辑**：

1. 校验文件名、扩展名、大小；ZIP 防 Zip Slip / zip bomb，成员压成 basename
2. HTTP 按 `rel_paths` 保留子目录，写入 `<kb>/raw/`
3. CLI `kb create` 的 `copy_documents` **只保留 basename**，不保留目录
4. 立刻在 `kb_config.json` 登记 `status=initializing|processing`
5. 后台任务：`initializer.process_documents()` 或 `adder.process_new_documents()`
6. `DocumentAdder` 用 SHA-256 去重（`metadata.json.file_hashes`）；create 路径**不写** `file_hashes`
7. 上传时若 KB 标记 `needs_reindex`，返回 409

**输出**：磁盘上的原文件 + 后台索引任务 `task_id`

**下一步**：`RAGService.initialize()` / `add_documents()`

PocketBase 附件同步是 best-effort，主路径始终是本地 `raw/`。

### 3.2 入口 B：CLI

**核心**：`deeptutor_cli/kb.py` `kb_create` / `kb_add` / `kb_search`

- `create` **写死 LlamaIndex**，没有 `--provider`
- 收集文件：`FileTypeRouter.collect_supported_files(..., recursive=True)`
- 没有 `reindex` 命令
- 随后同样进入 `initialize_knowledge_base()` / `add_documents()`

### 3.3 入口 C：聊天附件（独立链路，不建库）

**输入**：WS 回合里的 `{filename, base64, mime_type}`

**核心**：

- `frontend/src/app/sessions.ts` `fileToAttachment`（当前前端唯一导入面）
- `deeptutor/services/session/turn_runtime.py`（约 1344 行）
- `deeptutor/utils/document_extractor.py`
  - `extract_documents_from_records()`
  - `extract_text_from_bytes()`
- Partner IM：`deeptutor/services/partners/runtime.py` 同样走 `extract_documents_from_records`

**逻辑**：

- PDF：PyMuPDF，失败回退 pypdf；按页加 `--- Page N ---`
- DOCX/XLSX/PPTX：python-docx / openpyxl / python-pptx，失败回退 OOXML
- 文本：与 KB 相同的编码链
- **不走 ParseService，无 OCR，无切分，无 Embedding**
- 额度来自 `system.json` 聊天附件限制（默认单文件 20MB、合计 25MB、单文件 20 万字符、合计 15 万字符）
- 原件落入 `AttachmentStore`，URL：`/api/attachments/{session}/{id}/{filename}`
- `GET /api/attachments/...` 只做预览/下载，不解析

**输出**：`extracted_text` 写入附件记录；落库前清空 base64

**下一步（分叉）**：

- **非 chat capability**：拼进 `effective_user_message` 的 `[Attached Documents]`
- **chat**：原文**不**拼进用户消息；进入 `source_inventory`，id 为 `at-*`
  - 预览给 `explore_context` 的 `read_source`
  - 回答循环**不**挂载 `read_source`（`has_sources=False`）

### 3.4 入口 D：出题仿题

**输入**：question WebSocket `mode=upload` + PDF base64

**核心**：

- `deeptutor/api/routers/question.py` `websocket_mimic_generate`（仅接受 `.pdf`）
- `deeptutor/agents/question/mimic_source.py` `parse_exam_paper_to_templates()`
- `deeptutor/tools/question/question_extractor.py` `extract_questions_from_paper()`

**逻辑**：

- 写到独立目录 `get_question_dir()/mimic_papers/mimic_<ts>_<stem>/`，**不进 KB raw/**
- `ParseService.parse()` → 读 markdown / `content_list` → LLM 抽题 JSON → `QuizTemplate`
- `extract_questions_with_llm` 接收 `content_list`，但 user prompt 实际只塞了 `markdown[:15000]` 和图片文件名，结构化 blocks **没有进 prompt**
- `mode=parsed`：只传已解析目录名，跳过解析
- 独立 WS `/generate`：文本 `requirement` + `kb_name`，无文件上传；默认 `kb_name="ai_textbook"`

**输出**：题目模板，**不进入知识库索引**。KB 只在后续出题 RAG 使用。

### 3.5 连接型导入（不解析）

| API | 类型 | 行为 |
|---|---|---|
| `POST /connect-obsidian` | `obsidian` | 指向本地 Markdown 库；Obsidian capability 读活文件 |
| `POST /connect-folder` | `linked` | 挂载已有引擎索引，不重建；可链 llamaindex / graphrag / lightrag，不可链 PageIndex |
| `POST /connect-lightrag-server` | `lightrag_server` | HTTP `/query`，`only_need_context=True` |
| `POST /connect-ima` | `ima` | 腾讯 IMA `search_knowledge` |
| 子代理 KB | `subagent` | 无文件、无索引 |

`POST /{kb}/link-folder` + `sync-folder` **不同**：它给普通索引型 KB 记一个可同步的外部文件夹（`metadata.linked_folders`），把支持文件同步进 `raw/`，再走增量索引。这不是 `type=linked` 的引擎索引挂载。

组织操作（不触发解析/检索）：

- `POST /{kb}/folders`、`POST /{kb}/files/move`：只动 `raw/` 目录树
- `DELETE /{kb}/files/{filename}`：`remove_raw_document` 删文件 + `file_hashes`；**不删向量**
- `GET /{kb}/file-preview-text/{filename}`：现场 `extract_text_from_path`，不写索引、不走 `ParseService`

### 3.6 解析桥：ParseService

**输入**：磁盘路径 + 可选引擎名

**核心**：

- `deeptutor/services/parsing/service.py` `ParseService.parse()`
- `deeptutor/services/parsing/engines/factory.py` `get_parser()`
- `deeptutor/services/parsing/cache.py`

**逻辑**：

1. 读 `document_parsing.json` 的 `engine`（默认 `text_only`）
2. 校验后缀 ∈ `supported_formats()`
3. 缓存键 = `sha256(文件字节)[:16]` + `ParserSignature.hash()`（哈希字节，不哈希文件名）
4. 命中则 `load_ir()`；否则 `is_ready()` 门闩 → `parser.parse()` → 写 `manifest.json`
5. `parse()` 本身返回 `None`，只往 workdir 写产物；由 `ParseService` 组装 IR
6. 空 markdown 且空 blocks → `ParserError`
7. 失败清理未完成目录后原样抛出；**不把 `MinerUError` 包成 `ParserError`**（`MinerUError` 直接继承 `RuntimeError`，与注释不符）

**输出**（`ParsedDocument`）：

```python
markdown: str
blocks: list[dict] | None      # 仅 MinerU 等产出 content_list 的引擎
asset_dir: Path | None         # images/
source_hash, parser_signature, engine, workdir
```

没有 DeepTutor 自有的 block schema。`blocks` 就是磁盘上 `*_content_list.json` 的 JSON list。

缓存目录：`data/parse_cache/<hash[:2]>/<source_hash>/<signature>/`

`find_content_dir` 会找 `auto/`、`hybrid_auto/` 或任意含 `*.md` 的子目录（兼容 MinerU 嵌套输出）。相对 `img_path` 在加载时改成绝对路径，缓存文件保持相对。

**谁调用 `ParseService`**：

| 调用方 | 用什么字段 |
|---|---|
| LlamaIndex `document_loader._parse_document` | `markdown`；图片来自 `asset_dir` |
| GraphRAG `ingestion._extract_parser_text` | 只要 `markdown` |
| LightRAG `pipeline._ingest` | 优先 `blocks`，否则把 markdown 包成单 text block |
| 出题 `mimic_source` | `workdir` 给抽题器 |

**不经过 ParseService**：

- 聊天附件：`document_extractor.extract_documents_from_records`
- KB 文本预览：`serve_kb_raw_file_text_preview`
- session artifact 预览：`artifact_attachments.py`
- PageIndex / IMA / LightRAG Server
- GraphRAG / LlamaIndex 的 `text_files`：`FileTypeRouter.read_text_file`

解析失败在 RAG 建库时**按文件 skip**，不整批中止。

### 3.7 各解析引擎实际做什么

**`TextOnlyParser`**（已接入、默认可跑）

- `extract_text_from_path(..., max_bytes=200MB, max_chars=None)`
- 只写 `<stem>.md`，无 `blocks`，无图片
- PDF 只抽文本层，无 OCR

**`MinerUParser`**

- 仅 PDF；唯一会写 structured `blocks` 的引擎
- 云：`mineru/cloud.py`，把 `is_ocr` / `model_version` / `enable_formula` / `enable_table` / `language` 放进 API body（`https://mineru.net` v4：申请 URL → PUT → 轮询 → 下载 zip）
- 本地：`mineru/local.py` 只执行 `mineru -p <pdf> -o <dir>`（或 `magic-pdf`）
- **已确认**：`language` / `enable_formula` / `enable_table` / `is_ocr` **没有**传给本地 CLI，但会进入 signature（改开关会换缓存目录却不一定改本地输出）
- `MINERU_*` 环境变量只覆盖 settings 读取，不改变本地 CLI 参数
- `is_available()` 恒 True；能不能跑看 readiness（云要 token；本地要 CLI + 模型已在缓存或允许下载）
- 产出 markdown + `*_content_list.json` + `images/`

**`DoclingParser`**

- `DocumentConverter` → `export_to_markdown()`
- `do_ocr` / `do_table_structure` 尽量写入 `PdfPipelineOptions`；options API 失败则静默退回默认 Converter
- **明确推迟** `blocks` 映射，只有 markdown

**`MarkItDownParser`**

- `MarkItDown().convert()` → markdown
- `enable_llm_image_description` 写入 signature 和设置，**`parse()` 未把 LLM 传给 MarkItDown** → 预留未接线

**`PyMuPDF4LLMParser`**

- 强制走 `pymupdf4llm.helpers.pymupdf_rag.to_markdown`（避开 1.x onnx 布局模型）
- extra 钉死 `pymupdf4llm>=0.0.17,<1.0`
- 可选抽图到 `images/`，改写 markdown 链接
- 无 OCR 开关，不写 `content_list`

**`LiteParseParser`**

- `LiteParse(output_format="markdown", ocr_failure_fatal=False).parse()`
- OCR 在第三方内部；失败不致命；无用户可配 OCR 开关
- 不写 `content_list`

解析层**没有**通用文本清洗、去页眉页脚或文档级元数据模型（无 title/author/page count）。仅有图片链接改写和 cache 里 `img_path` 绝对化。

### 3.8 切分 / 结构化 / Embedding

解析层**不做切分**。切分发生在各 RAG pipeline：

**LlamaIndex**（`llamaindex/ingestion.py`）

```
Document(text=markdown, metadata={file_name, file_path})
  → SentenceSplitter(chunk_size, chunk_overlap)   # 默认 512 / 50
  → Settings.embed_model  (CustomEmbedding → DeepTutor EmbeddingClient)
  → VectorStoreIndex
```

本机 `data/user/settings/llamaindex.json`：`chunk_size=512`，`chunk_overlap=50`，`top_k=5`，`retrieval_profile=hybrid`。

图片（单独路径）：

1. 多模态 LLM 描述（硬编码 prompt，约 180 词）
2. 多模态 Embedding
3. 预计算向量的 `ImageNode`，**不再切分**
4. 缺多模态能力则跳过图片

Embedding 统一入口：`deeptutor/services/embedding/client.py`。向量不单独存一份「embedding 库」，只作为各引擎索引的一部分。LlamaIndex 文本 embed 用 `input_type=search_document`，查询用 `search_query`。

**GraphRAG**

- 解析文本写成 `version-N/input/*.txt`
- `engine.build()` 调 `microsoft/graphrag`：LLM 抽实体/关系/社区
- 模式：`local`（默认）/ `global` / `drift` / `basic`
- **检索返回 LLM 合成答案**，不是原始 chunk 拼接

**LightRAG**

- `raganything.RAGAnything.insert_content_list(...)`
- 故意设置 `_parser_installation_checked = True`，避免 RAG-Anything 默认检查 MinerU 安装
- 内部再建图 + 向量；LLM / vision / embedding 都绑 DeepTutor 适配器
- 模式：`naive/local/global/hybrid/mix`（代码默认 `hybrid`，本机 `kb_config.json` 把 LightRAG 默认写成 `mix`）
- **本地检索不回 `sources`**：只有合成 `answer`，`sources=[]`

**PageIndex**

- `client.submit_document(原文件)` → 云端建树，**不经 ParseService、不 Embedding**
- `pipeline.search()` 只返回文档树大纲（每文档最多 6000 字）
- chat 里真正的深度阅读走 PageIndex MCP（`https://api.pageindex.ai/mcp`）

### 3.9 存储与索引生命周期

普通索引型 KB 目录：

```
data/knowledge_bases/
  kb_config.json
  <kb_name>/
    metadata.json
    .progress.json
    raw/                    # 原文件，永不改写
    version-1/              # 一次成功建库
      meta.json
      # LlamaIndex:
      #   docstore.json, index_store.json,
      #   default__vector_store.json (FAISS 二进制或 JSON)
      #   graph_store.json          # VectorStoreIndex 默认 persist，不是知识图谱
      #   image__vector_store.json  # 可能有
      #   bm25_retriever/           # 可选
      # GraphRAG:
      #   settings.yaml, input/*.txt
      #   output/{entities,communities,community_reports,text_units,relationships}.parquet
      #   output/lancedb/, cache/, logs/
      # LightRAG:
      #   kv_store_*.json, vdb_*.json (nano-vectordb)
      #   graph_chunk_entity_relation.graphml
      # PageIndex:
      #   pageindex_docs.json（远程 doc_id 映射）
    version-2/              # 换 embedding / 重建时新增，旧版保留
```

`KnowledgeBaseInitializer.create_directory_structure()` **只建 `raw/` + `metadata.json`**。`images/`、`content_list/`、`llamaindex_storage/` 不再创建。

遗留只读布局：`<kb>/llamaindex_storage/`、`<kb>/index_versions/<signature>/llamaindex_storage`、`<kb>/rag_storage/`。

- LlamaIndex 版本按 embedding signature（binding/model/dim/url/api_version 的 sha256 前 16 位）选择
- 换 embedding 会标 `needs_reindex` / `embedding_mismatch`；切回旧模型可复用旧 `version-N` 并自动清旗
- GraphRAG / LightRAG / PageIndex **不按** embedding hash 判 stale（`provider_uses_embedding_versions` 仅 LlamaIndex 为 True）
- 删单个 raw 文件：`remove_raw_document()` 只删文件和 hash；**不立刻改向量**。已索引过的文件要靠后续 reindex 清向量
- 连接型 KB：无 `raw/`，删除只丢指针，不碰外部资源
- `list_knowledge_bases` 不会因缺目录而 prune 连接型 KB
- 绑定解析顺序：`kb_config.json` → `metadata.json` → 默认 `llamaindex`

本机现状：

```
种草/          status=error   raw 有一份 .md   无 version-N
               Embedding HTTP 400（User location is not supported）
纺织面料系统学/  status=error   raw 有一份 .md   无 version-N
               Embedding HTTP 429
defaults.provider_modes.lightrag = "mix" 已写入，但无 LightRAG KB
```

因此本工作区**未实际产出任何向量或知识图谱**。

### 3.10 检索与下游消费

统一检索信封（`RAGService.search` 强制补齐）：

```python
{
  "query": str,
  "answer": str,      # 与 content 互相同步
  "content": str,
  "sources": [        # {title, content[:200], source, page, chunk_id, score}
  ],
  "provider": str,    # 以绑定为准，覆盖 pipeline 自报
  "needs_reindex": bool,  # 可选
  "error_type": str,      # 可选
  "warning": str,         # LlamaIndex embedding_mismatch
  "mode": str,            # Graph/LightRAG
}
```

各引擎 `answer` 含义不同：

| 引擎 | `answer` 是什么 | `sources` |
|---|---|---|
| LlamaIndex | 命中节点文本直接拼接 | 有：file_name / file_path / page / score |
| GraphRAG | LLM 合成答案 | 有：从 context 的 sources → reports → entities 择一 |
| LightRAG 本地 | LLM 合成答案 | **空列表** |
| LightRAG Server | 服务端返回的 context | 有：`{id, file_path}`（来自 `references`） |
| IMA | highlight 拼成的 context | 有：title / highlight / media_id |
| PageIndex `search()` | 文档树大纲 | 树顶层 title + summary |
| 无 sources 时 | — | `rag` 工具回退 `{type:"rag", query, kb_name}` |

LlamaIndex 检索：`storage.retrieve_nodes()` → 默认 hybrid（BM25 + 向量 fusion，`MockLLM`，`fusion_num_queries=1`）。无 BM25 包则退回纯向量。向量后端优先 FAISS `IndexFlatIP`（L2 归一化后等价余弦）；维度不一致或无 faiss 时用 `SimpleVectorStore`。文件头 `{` = JSON，否则当 FAISS 二进制。

**消费点（均已接线）**：

| 消费者 | 入口 | 行为 |
|---|---|---|
| Chat 开场 seed | `ChatAgenticPipeline._retrieve_kb_seed_block` | 对每个非独占 KB 调一次 `rag`，query=用户原话，截断后注入 system |
| Chat 工具 | `RAGTool.execute` → `rag_search` | 模型按 KB 再检索；`kb_name.enum` = `_coexisting_rag_kbs` |
| Chat 清单 | `kb_files` + `manifest.render_manifest_note` | 读磁盘文件列表，不读索引、不读正文 |
| 出题 / 研究 | 各自 pipeline 同样挂 `rag` | `kb_name = context.knowledge_bases[0]` |
| Book | `source_explorer._retrieve_kb_chunks`、`blocks/_rag_helpers.optional_rag_lookup` | 探索阶段检索；块生成先用缓存再 live RAG |
| 共写 | `co_writer/edit_agent.py` `gather_context` | `rag_search(..., only_need_context=True)`；无 `kb_name` 则跳过 |
| CLI | `deeptutor kb search` | 直接 `rag_search` |
| 记忆 | `RAGService.search` 成功后 `TraceEvent("kb","query")` | 只记查询痕迹 |
| Book 健康 | `kb_health.fingerprint_kbs` | 对 `raw/` 做指纹，检测漂移，不检索 |

**不消费解析结果 / 索引的模块**：

- `deeptutor/learning/`：无 `knowledge_bases` / `rag_search` 引用（掌握度、间隔重复）
- Mastery 提示要求模型用 `rag`，但检索走 chat 工具面，不另开 pipeline
- Notebook：消费笔记走 `nb-` source，不搜 KB
- 连接型 Obsidian / subagent：走自己的 capability / `consult_subagent`
- PageIndex 在 chat 里主要靠 MCP；`pipeline.search()` 只返回树大纲
- `read_source`：**不读 KB**。id 前缀只有 `nb-` / `bk-` / `hs-` / `qb-` / `at-`

**工具挂载**（`agents/_shared/tool_composition.py`）：

- `has_kb` 为真才挂 `rag` / `kb_files`
- 纯 PageIndex 或纯 Obsidian 回合不挂 `rag`
- 与 LlamaIndex KB 共存时，vault 不占 `rag`，其它 KB 仍挂 `rag`
- `read_source` 只在 `explore_context` 预扫描，不在回答循环

**`SmartRetriever`**：实现完整（多 query + LLM 汇总），但生产代码**没有调用方**，只有测试走 `RAGService.smart_retrieve()`。

**KB 如何进入回合**：

1. 客户端 `start_turn` JSON 可带 `knowledge_bases`
2. `TurnRuntime.start_turn` 写入 session preferences
3. `_run_turn` → `UnifiedContext.knowledge_bases`
4. chat pipeline 据此挂工具、写 system note
5. 当前 **frontend/src 不发送 `knowledge_bases`**
6. CLI：`deeptutor chat --kb` / `deeptutor run ... --kb` 会传
7. `regenerate` 的 `overrides.knowledge_bases` 可覆盖 session 偏好

---

## 4. 关键源码索引

| 路径 | 类 / 函数 | 角色 |
|---|---|---|
| `deeptutor/api/routers/knowledge.py` | `create_knowledge_base`, `upload_files`, `reindex_knowledge_base`, `connect_*` | HTTP 入口 |
| `deeptutor/api/main.py` | `include_router(..., prefix="/api/v1/knowledge")` | 路由挂载 |
| `deeptutor_cli/kb.py` | `kb_create/add/search` | CLI |
| `deeptutor/knowledge/initializer.py` | `KnowledgeBaseInitializer.process_documents` | 首次建库 |
| `deeptutor/knowledge/add_documents.py` | `DocumentAdder`, `remove_raw_document` | 增量 / 删文件 |
| `deeptutor/knowledge/manager.py` | `KnowledgeBaseManager` | 生命周期、状态、embedding 对账 |
| `deeptutor/knowledge/kb_types.py` | `CONNECTED_KB_TYPES` | 指针型 KB 判别 |
| `deeptutor/knowledge/manifest.py` | `build_manifest`, `render_manifest_note` | 文件清单事实 |
| `deeptutor/services/rag/file_routing.py` | `FileTypeRouter` | 类型与编码 |
| `deeptutor/services/rag/service.py` | `RAGService` | 统一 index/search |
| `deeptutor/services/rag/factory.py` | `get_pipeline`, `KNOWN_PROVIDERS` | 引擎工厂 |
| `deeptutor/services/rag/provider_binding.py` | `resolve_bound_provider` | KB→引擎绑定 |
| `deeptutor/services/rag/kb_paths.py` | `resolve_kb_dir` | 含 linked 根路径 |
| `deeptutor/services/parsing/service.py` | `ParseService` | 解析桥 |
| `deeptutor/services/parsing/types.py` | `ParsedDocument` | 解析 IR |
| `deeptutor/services/parsing/engines/*` | 六个 `*Parser` | 引擎适配 |
| `deeptutor/services/rag/pipelines/llamaindex/{document_loader,ingestion,vector_store,retrievers,pipeline}.py` | 默认 RAG | 解析→切分→向量→检索 |
| `deeptutor/services/rag/pipelines/graphrag/{ingestion,pipeline,engine}.py` | 图谱 RAG | 文本→GraphRAG |
| `deeptutor/services/rag/pipelines/lightrag/{pipeline,engine}.py` | 图+向量 RAG | content_list→RAG-Anything |
| `deeptutor/services/rag/pipelines/pageindex/pipeline.py` | 云端树检索 | 上传原文件 |
| `deeptutor/services/rag/pipelines/{lightrag_server,ima}/pipeline.py` | 远端检索 | 无本地解析 |
| `deeptutor/services/rag/index_versioning.py` | `version-N` | 索引版本 |
| `deeptutor/services/rag/index_probe.py` | `has_ready_provider_index` | 索引是否可用 |
| `deeptutor/tools/rag_tool.py` | `rag_search` | 消费入口 |
| `deeptutor/tools/builtin/__init__.py` | `RAGTool`, `KbFilesTool`, `ReadSourceTool` | 工具定义 |
| `deeptutor/agents/chat/agentic_pipeline.py` | `_retrieve_kb_seed_block`, `_coexisting_rag_kbs` | 开场自动检索 / 挂载 |
| `deeptutor/agents/_shared/tool_composition.py` | `ToolMountFlags`, `compose_enabled_tools` | 工具挂载策略 |
| `deeptutor/capabilities/explore_context/explorer.py` | `ContextExplorer` | `read_source` 预通道 |
| `deeptutor/utils/document_extractor.py` | 聊天附件抽取 | 旁路 |
| `deeptutor/agents/question/mimic_source.py` | 试卷解析 | 旁路 |
| `deeptutor/tools/question/question_extractor.py` | LLM 抽题 | 旁路 |
| `deeptutor/book/agents/source_explorer.py` | `_retrieve_kb_chunks` | Book 检索 |
| `deeptutor/book/blocks/_rag_helpers.py` | `optional_rag_lookup` | Book 块生成可选 RAG |
| `deeptutor/co_writer/edit_agent.py` | `gather_context` | 共写 RAG |
| `deeptutor/services/config/runtime_settings.py` | `DEFAULT_DOCUMENT_PARSING_SETTINGS` 等 | 配置默认值 |
| `deeptutor/services/path_service.py` | `get_knowledge_bases_root`, `get_parse_cache_root` | 磁盘根 |
| `data/user/settings/document_parsing.json` | 本机解析引擎 | 运行时 |
| `data/user/settings/llamaindex.json` | 切分/检索旋钮 | 运行时 |
| `data/knowledge_bases/kb_config.json` | KB 注册表 | 运行时 |

---

## 5. 数据结构与存储

### 5.1 解析 IR

`ParsedDocument`（`services/parsing/types.py`）：markdown 必有；`blocks` 为 MinerU 风格 `content_list`；`asset_dir` 指向抽图。`has_structure` = `bool(blocks)`。

LlamaIndex 节点 metadata：`file_name`, `file_path`；图片另有 `content_type=image`, `image_description`。

抽题 JSON：`{paper_name, extraction_time, total_questions, questions:[{question_number, question_text, question_type, difficulty, answer, images}]}`。

### 5.2 KB 配置

`kb_config.json` 每条大致含：`path`, `status`, `rag_provider`, `progress`, `index_versions`, `needs_reindex`, `embedding_mismatch`, `embedding_model` / `embedding_dim` / `embedding_signature`, `search_mode`，连接型还有 `type` + 指针字段。

`metadata.json`（非权威）：`name`, `created_at`, `rag_provider`, `file_hashes`（仅增量路径）, `last_indexed_*`, `update_history`。

版本 `meta.json`（LlamaIndex）：`version, signature, binding, model, dimension, base_url, api_version, layout, created_at`。Graph/LightRAG 的 `signature` 为 provider 名。

清单模块 `KbManifest` 只数磁盘文档，**不报索引文档数**（源码明确认为 `docstore` / `file_hashes` / `last_indexed_count` 不可信）。

### 5.3 检索结果

见 §3.10。这是下游唯一稳定契约；各引擎内部存储（FAISS、GraphRAG parquet/json、LightRAG JSON、PageIndex 远程树）对工具层不可见。

### 5.4 生命周期

`initializing` → `processing` → `ready` | `error`。reindex 写新 `version-N`（LlamaIndex 若已有匹配且有效的 flat version 则 noop；`status=error` 可强制）。删除普通 KB 会 `shutil.rmtree` 整个目录；删除连接型 KB 不碰外部资源。失败且无 `meta.json` 会清空该 version 目录。

---

## 6. Prompt、配置、外部依赖

### Prompt（源码内硬编码）

| 位置 | 用途 |
|---|---|
| `llamaindex/document_loader.py` `IMAGE_DESCRIPTION_*` | 为图片生成可检索描述（索引阶段，非解析） |
| `question_extractor.py` `system_prompt` | 从试卷 markdown 抽题 |
| `smart_retriever.py` | 多 query / 汇总（**生产未调用**） |

解析主路径（text_only / markitdown / pymupdf4llm / liteparse）**不用 LLM**。MinerU/Docling 用自己的版面模型。GraphRAG / LightRAG **建库时**用 LLM 抽图。

### 配置文件

| 文件 | 作用 |
|---|---|
| `data/user/settings/document_parsing.json` | 解析引擎及各引擎旋钮（v2；旧 `mineru.json` 首次 load 时迁移） |
| `data/user/settings/llamaindex.json` | chunk / top_k / hybrid |
| `data/user/settings/graphrag.json` / `lightrag.json` / `pageindex.json` | 各引擎查询/凭证 |
| `data/knowledge_bases/kb_config.json` | KB 绑定与状态 |
| Embedding / LLM 设置 | 走模型目录，不在上述文件 |

HTTP 设置：`GET/PUT /api/v1/settings/document-parsing`，另有 `/mineru` 旧切片、`/document-parsing/test`、`/document-parsing/install`、模型下载与 job 状态。

环境变量：`RAG_PROVIDER` 只影响全局默认展示；真正绑定在 `kb_config.json`。`DEEPTUTOR_RAG_RETRIEVAL_PROFILE` 是 LlamaIndex 旧覆盖口。MinerU 另有 `MINERU_MODE` / `MINERU_API_TOKEN` 等，仅覆盖 settings 读取。

磁盘根：`PathService.get_knowledge_bases_root()` = `<runtime-home>/data/knowledge_bases`（`DEEPTUTOR_HOME` 或 cwd 下的 `data/`）。CLI 硬编码同一位置：`project_root / "data" / "knowledge_bases"`。

### 第三方库与服务

**默认安装就会用（已接入）**

- LlamaIndex + BM25 retriever + FAISS（`faiss-cpu` + `llama-index-vector-stores-faiss`）
- PyMuPDF / pypdf / python-docx / openpyxl / python-pptx / defusedxml
- 用户配置的 Embedding HTTP API、LLM HTTP API

**可选 extra，代码已写完，缺包则 `is_available()=False`**

- `deeptutor[parse-docling]` / `[parse-markitdown]` / `[parse-pymupdf4llm]` / `[parse-liteparse]`
- 聚合 extra：`parse`（**没有** `parse-mineru`）
- `deeptutor[graphrag]` → microsoft/graphrag（`>=3.0.1,<4`，Python < 3.14）
- `deeptutor[rag-lightrag]` → raganything / LightRAG

**外部进程 / SaaS**

- MinerU：本地 CLI（`magic-pdf`/`mineru`）或 `https://mineru.net`
- PageIndex：`https://api.pageindex.ai`
- LightRAG Server、腾讯 IMA：用户自备端点
- Docling 模型：`~/.cache/docling` 或 HF hub
- GraphRAG 向量：自带 LanceDB
- LightRAG 向量：nano-vectordb（`vdb_*.json`）

**仓库里没有 Chroma。**

---

## 7. 实现状态判别

### 已实际运行（代码完整，默认路径可走）

- API/CLI 上传 → `raw/` → LlamaIndex 解析/切分/Embedding/FAISS
- `text_only` 解析（本机当前选择）
- `rag` / `kb_files` / chat seed / Book / 出题 / 研究 / 共写 检索
- 聊天附件旁路抽取
- 内容寻址解析缓存
- 连接型 KB 指针（代码完整；是否连得上取决于用户配置）
- ZIP 安全解压、文件夹上传、link-folder 同步
- 单文件删除（清 raw + hash，不即时清向量）
- 版本与 probe、linked KB、preflight

### 第三方提供、DeepTutor 只做适配

- MinerU / Docling / markitdown / PyMuPDF4LLM / LiteParse 的版面/OCR
- GraphRAG 的图谱构建
- LightRAG / RAG-Anything 的图+向量
- PageIndex / IMA / LightRAG Server 的远端检索
- FAISS、LlamaIndex SentenceSplitter / QueryFusionRetriever
- GraphRAG LanceDB、LightRAG nano-vectordb

### 仅预留 / 未接线 / 半废弃

| 项 | 依据 |
|---|---|
| markitdown `enable_llm_image_description` | 进 signature，未传入 `MarkItDown()` |
| MinerU 本地 `is_ocr` / language / formula / table | 只影响 cache key 和云 API；本地 CLI 只有 `-p -o` |
| Docling `blocks` | 注释写明 mapping deferred |
| `SmartRetriever` | 仅测试调用 |
| `DocumentValidator.ALLOWED_EXTENSIONS` | 含 `.doc/.rtf/.xls/.ppt`，实际上传被 FileTypeRouter 覆盖 |
| `KnowledgeBaseInitializer.fix_structure` | 空操作，兼容旧管线 |
| `imports.py` | 会话导入，与资料解析无关 |
| 当前 `frontend/src` | 无 KB 上传页，也不传 `knowledge_bases`；后端 API 仍在 |
| 本机两个 KB | 创建成功、索引失败，无可用向量 |
| `images/`、`content_list/` 目录 | manager 仍统计，initializer 不再创建 |
| `rag_storage` / `llamaindex_storage` / `index_versions` | 只读兼容 |
| `pipelines/__init__.py` 仍写 “currently ships with a single built-in” | 与 factory 已过时 |
| `MinerUError` 继承 `ParserError` | 注释声称，代码未做 |
| Chroma | 全仓库无引用 |

`initializer` 仍保留 `llamaindex_storage_dir` 字段名，新写入已改为 `version-N/`。

---

## 8. 已确认 / 尚未确认

### 已确认

- 默认解析引擎是 `text_only`，配置文件与源码默认一致
- 解析与 RAG 分层：`Parser` 协议刻意不在 `RAGPipeline` 上
- LlamaIndex / GraphRAG / LightRAG 共享 `ParseService`；PageIndex / IMA / LightRAG Server 不共享
- 切分只发生在 LlamaIndex `SentenceSplitter`；解析层不切
- 知识图谱只存在于 GraphRAG / LightRAG 引擎内部，DeepTutor 没有自研图谱层
- LlamaIndex 的 `graph_store.json` 不是知识图谱
- LightRAG 本地检索 `sources=[]`；GraphRAG 检索是 LLM 合成答案
- 聊天附件与 KB 文档是两条代码路径
- learning / mastery **不读**解析结果；`read_source` 不读 KB
- CLI `kb create` 不能选 RAG provider；CLI 无 reindex
- 知识库 HTTP 无 search 端点
- 当前 frontend 不调 KB API，只传聊天附件
- 本机两个 KB 因 Embedding API 失败，没有索引产物，也没有 parse_cache
- 仓库无 Chroma

### 静态分析未做运行验证的项

- MinerU 本地 CLI 在本机是否安装、实际产出目录是否总是 `<stem>/auto/`
- MinerU 本地 CLI 是否自己读环境变量做 OCR（本仓库未传、未读）
- MinerU `content_list` 完整字段表（本仓库不建模，只当 `list[dict]`）
- Docling OCR 在当前 docling 版本上 `PdfPipelineOptions` 接线是否总能成功
- LiteParse 内部 OCR 的具体引擎与质量
- FAISS 在「文本 + 图片向量维度不同」时退回 SimpleVectorStore 的现场行为
- PageIndex MCP 在 chat 里的完整工具往返
- PageIndex / IMA / LightRAG Server 响应字段在不同服务端版本上是否稳定
- 多用户 `data/users/<uid>/knowledge_bases` 的运行时切换（`PathService` 支持，未在本会话跑多用户）
- `linked_folders` 自动同步是否仍被 UI 调用
- Partner 拷贝 KB 到 workspace 后检索是否改 `base_dir`
- 前端附件预览是否一定打 `/api/attachments`
- 当前 TraeWork 前端是否计划接回 KB API（源码中无调用）

未做无关部署或性能测试。未对本机失败 KB 重跑 Embedding。

---

## 9. 一份原始资料最终变成什么、被谁用

以「用户上传 `textbook.pdf` 到新建 LlamaIndex KB」（默认路径）为例：

1. **原件原样**落在 `data/knowledge_bases/<name>/raw/textbook.pdf`，生命周期内不被改写。
2. `ParseService` 用当前引擎（本机是 text_only）抽出纯文本，缓存到 `data/parse_cache/.../<stem>.md`。
3. LlamaIndex 把整份 markdown 收成一个 `Document`，再切成约 512 token、重叠 50 的句子块，调用配置的 Embedding API，写入 `version-N/`（优先 FAISS）。
4. 磁盘上**没有**独立的「结构化知识卡片」或统一 Schema 文档库；结构化只存在于：
   - 解析缓存里的 markdown（+ 偶尔的 `content_list`）
   - LlamaIndex `docstore.json` 的 chunk 节点
   - GraphRAG/LightRAG 引擎自有图存储（若选了那些 provider）
5. 使用时：chat 先用用户原句检索一遍塞进上下文；模型还可再调 `rag`。Book / 出题 / 研究 / 共走同一 `rag_search`。清单类问题走 `kb_files` 读 `raw/` 文件名，不读向量。
6. LlamaIndex 的 `rag` 结果是**原文片段拼接**；GraphRAG / LightRAG 本地则是**模型改写后的答案**。
7. 若同一 PDF 出现在聊天附件里：只抽文本进当轮上下文 / `read_source`，**不会**进入上述索引。
8. 若同一 PDF 用于出题仿题：ParseService 后再经 LLM 变成 `QuizTemplate`，**不会**进入 KB。

一句话：**DeepTutor 的资料解析不是「文档理解中台」，而是「原件归档 + 可插拔解析桥 + 按 KB 绑定的 RAG 引擎索引」；最终被系统使用的，主要是检索片段和磁盘文件清单，而不是一份统一的结构化知识对象。**
