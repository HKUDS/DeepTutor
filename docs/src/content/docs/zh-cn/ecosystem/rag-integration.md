---
title: RAG 集成
description: 选择 DeepTutor 如何从本地索引、智能体文档树、远程知识服务与实时学习资料库中检索。
quadrant: how-to
---

DeepTutor 把检索当成一条生态边界，而不是写死成某一种向量库。[知识空间](/zh-cn/explore/knowledge/)里的知识库是用户看到的容器；背后的 **RAG 集成**决定材料如何建索引、查询、引用与同步。

## 可用集成

![知识库](/screenshots/dev/knowledge.png)

| 集成 | 检索模型 | 最适合 |
|---|---|---|
| **LlamaIndex** | 本地向量检索，BM25 可用时采用混合检索 | 开箱即用的默认本地 RAG |
| **PageIndex OSS** | 本地智能体遍历无向量文档树 | 私有、带页面级引用的推理式检索 |
| **GraphRAG** | 本地知识图谱，支持 global/local/drift/basic | 跨文档关系与语料级问题 |
| **LightRAG** | 本地图 + 向量，支持 naive/local/global/hybrid/mix | 轻量的图感知检索 |
| **LightRAG Server** | 通过 HTTP 查询已有独立服务器 | 不建本地索引，复用远端 LightRAG 基础设施 |
| **WeKnora** | 通过 HTTP 检索已有的自托管知识库 | 不复制文档、不建本地索引，直接复用 WeKnora |
| **PageIndex Cloud** | 托管上传 + MCP 驱动的文档遍历 | 不在本地构建的托管式 agentic 检索 |
| **Tencent IMA** | 通过 OpenAPI 访问已有 IMA 资料库 | 复用云端知识库，并把网址或笔记写回 |
| **MarginNote 4** | 配对设备同步笔记、摘录、卡片与脑图 | 从既有学习工作流中检索 |
| **Obsidian** | 在 vault 内实时导航与写笔记 | 不上传、不建索引，直接使用本地知识图谱 |

界面把 LlamaIndex、PageIndex OSS、GraphRAG、LightRAG 放在 **Local**，LightRAG Server 放在 **Server**，PageIndex Cloud、Tencent IMA 与 WeKnora 放在 **Cloud**，Obsidian 与 MarginNote 4 放在 **External knowledge sources**。卡片会显示 **Ready**、**Needs key**、**Needs setup** 或 **Not installed**，建库前就能看清依赖。

## 三种集成契约

多数集成响应普通 `rag` 工具；有三种刻意使用不同契约：

- **PageIndex OSS** 是智能体式检索：本地阅读循环先检查文档结构，再只打开真正需要的页面；PageIndex Cloud 通过托管存储与 MCP 工具使用同类遍历方式。
- **Obsidian** 没有检索索引；专属能力直接在实时 vault 中导航和写入。
- **MarginNote 4** 通过专用导航工具访问同步进来的学习图谱。

表中其他集成——包括 LightRAG Server 与 Tencent IMA——连接为 KB 后都可以响应普通 RAG 查询。

## 安装与配置

LlamaIndex 是默认引擎；可选本地引擎需要显式安装：

```bash
python scripts/install_extras.py graphrag
python scripts/install_extras.py rag-lightrag
```

LightRAG extra 只安装受支持的 LightRAG SDK；文档解析仍是 **Settings → Document Parsing** 下的独立选择。远程服务与实时资料库从知识引擎卡片或已连接 KB 中配置。

## 按数据归属选择

- 部署应同时拥有文档与检索状态时，选择**本地索引**。
- 页面级结构比相似片段更重要时，选择**智能体文档树**。
- 已有 RAG 部署应继续做权威来源时，选择**远程服务**。
- DeepTutor 应进入学习者原有知识系统而不是复制它时，选择**实时资料库**。

## 另见

- [知识空间](/zh-cn/explore/knowledge/)——创建、版本化、同步和使用知识库
- [沉浸式阅读](/zh-cn/explore/reading/)——直接阅读一个资料组，而不是给整个语料建索引
- [设置](/zh-cn/explore/settings/)——配置 embedding 提供商与文档解析
