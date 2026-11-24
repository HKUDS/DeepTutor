---
title: 知识空间
description: 创建、版本化、同步、检查并复用为主页、伙伴、学习笔记本、书籍等学习界面提供依据的知识库。
quadrant: how-to
---

知识空间是你构建与管理 **RAG** 背后文档库的地方；在 Web UI 中，这个入口显示为 **Knowledge Center / 知识中心**。一个知识库（KB）可以为主页对话、学习笔记本、书籍生成与伙伴对话提供依据。本页聚焦 KB 生命周期；引擎架构与选型归入 [RAG 集成](/zh-cn/ecosystem/rag-integration/)。

## 它在哪里

从左侧栏的**资料 → 知识中心**进入。两个标签会把职责分开：**Knowledge bases** 管理你已建的资料库生命周期，**Knowledge engines** 展示当前部署可用的全部检索集成。

![知识库](/screenshots/dev/knowledge.png)

## 选择 RAG 集成

每个 KB 都绑定一个检索集成。打开 **Knowledge engines**，目录会按 Local、Server、Cloud 与 External knowledge sources 分组；建库前即可看到 **Ready**、**Needs key**、**Needs setup** 或 **Not installed**。完整比较见 [RAG 集成](/zh-cn/ecosystem/rag-integration/)，其中 PageIndex OSS 与 PageIndex Cloud 是两个不同 contract。

## 创建一个知识库

点击 **New knowledge base** 建索引库。先选择：

- **Create new**（新建）——上传文档并构建一个全新索引。
- **Link existing**（关联已有）——复用你在别处已建好的索引；DeepTutor 就地读取，不上传、不重建索引。

然后给 KB 命名、选择**索引引擎**、检索模式与存储工作区（账号库或就绪的工作区），再添加文档。PageIndex Cloud 上传到托管服务，PageIndex OSS 在本地构建。已有 ZIM 则从 **Knowledge engines → Kiwix / ZIM → Connect archive** 输入 kiwix-serve URL 和一个档案；文章留在服务器。KB 还可追踪 **GitHub 来源**（仓库、分支、路径、glob）或有界 **Web 来源**（URL、深度、页数），按需同步变更。

![创建知识库](/screenshots/dev/knowledge-create.png)

## 知识库内部

打开一个 KB 进行管理。面板把**文档查看器**与自适应导航配在一起：

| 标签页 | 作用 |
| --- | --- |
| **Files** | 源文档、抽取状态、预览与**来源视觉覆盖率**检查；即使 KB 处于 error 状态，也可删除单个文件而无需重建整个库。 |
| **Add documents** | 上传更多 PDF、Office、Markdown、文本、代码或数据。 |
| **Linked folders** | 关联一个本地文件夹，按需同步以索引新增和改动的文件。 |
| **GitHub** | 管理仓库来源并同步。 |
| **Web** | 管理有界站点抓取，可按需同步或每 1–168 小时定时同步。 |
| **Index versions** | 扁平 `version-N` 存储目录，带有各引擎的签名与构建元数据；适用时显示 embedding 和 LightRAG 索引模型信息。 |
| **Settings** | Embedding 模型、分块与检索参数、引擎信息及默认库；符合条件时预览并移动自有 KB 到另一存储工作区。 |


MarginNote 显示 **Devices** 与 **Settings**，由 add-on 推送数据。Kiwix 显示 **Articles** 与 **Settings**；可搜索 ZIM 文章并在阅读器中打开。

**版本模型。** 重新建索引写入新的 `version-N` 目录，并保留旧版本。LlamaIndex 只有在验证完成后才发布新索引；某一处理阶段结束，不代表整个索引已经可用。

## 文档解析

**Settings → Knowledge & documents → Document Parsing** 选择文本抽取与原图保留方式，具体能力取决于解析器。保留的 PDF 还支持精确页面或区域检查。**本地模型下载默认关闭**，只有明确允许才会发生。

![文档解析设置](/screenshots/dev/settings-parsing.png)

| 引擎 | 权衡 |
| --- | --- |
| **Text-only**（内置） | 对 PDF/Office/文本做纯文本抽取。无需安装包、无下载、无版面结构。 |
| **MinerU** | 多模态解析（版面、表格、公式）。本地 CLI 下载模型，或用云 API；超大 PDF 自动拆分，重试复用已完成部分。支持 PDF；BMP、GIF、JP2、JPEG、JPG、PNG、TIFF、WebP 图片；DOCX、PPTX、XLSX。 |
| **Docling** | 结构化转换（版面/表格）。首次运行下载本地模型，也可以 **remote** 模式连到 Docling Serve 服务器（无需本地安装与模型）。PDF/Office/HTML/图片。 |
| **Tika** | 仅远端：连接 Settings → Document Parsing 中配置的 Apache Tika 服务器，无需本地安装与模型。格式支持广 → 输出 Markdown。 |
| **markitdown** | 轻量、无下载、格式支持广 → 输出 Markdown。`pip install deeptutor[parse-markitdown]`。 |
| **PyMuPDF4LLM** | 轻量、无下载、无需 CUDA。转换 PDF、电子书、XPS、图片、文本与 Markdown，并可抽取图片。`pip install deeptutor[parse-pymupdf4llm]`。 |
| **LiteParse** | 轻量结构化解析，无需下载本地模型。`pip install deeptutor[parse-liteparse]`。 |

## CLI 对应命令

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

## 提示

- 在构建正式 KB 前，先到 **Settings → Embedding models** 配好 embedding 提供商。
- 若更换了 embedding 模型，请重建索引，而不要混用向量空间；原生 LightRAG 索引会记录 embedding，恢复或重建前拒绝查询。
- 中断后查看**索引恢复详情**：重试复用已验证的解析结果与兼容的 LlamaIndex 向量化检查点；未检查点化的工作重新执行。取消等待安全边界。
- 留一个小的测试 KB 用于伙伴/渠道冒烟测试。
- 用 Docker 时，持久化整个 `data/` 目录树，让 KB 版本能在容器重启后存活。

## 另见

- [RAG 集成](/zh-cn/ecosystem/rag-integration/)——比较知识库背后的知识引擎
- [主页](/zh-cn/explore/chat-workspace/)——把 KB 挂到一轮里
- [沉浸式阅读](/zh-cn/explore/reading/)——读一份文档，而不是给一整个语料库建索引
- [书籍](/zh-cn/explore/book/)——从 KB 编译学习材料
- [伙伴](/zh-cn/explore/partners/)——把 KB 拷贝进伙伴工作区
- [设置](/zh-cn/explore/settings/)——embedding 提供商与解析引擎

## 在工作区中使用知识库

在目标工作区创建知识库并等索引就绪。未手动选择的聊天继承工作区已就绪的指定库或默认库；知识库选择器可覆盖继承。先用能对照原文核验的问题测试，例如：“第二章对平稳性作了哪些假设？请引用来源。”检查检索段落后再扩充材料。上传到一段对话的附件不会自动加入知识库。

资源分配决定工作区可使用哪些知识库；共享可用性与转移归属不同。知识库设置提供工作区迁移时，应先检查预览、资源分配与阻碍项再确认。知识库可为聊天、书籍等支持的活动提供来源依据；希望在导师旁直接查看原文时，则适合使用阅读。
