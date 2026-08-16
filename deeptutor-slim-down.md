# DeepTutor 瘦身裁剪建议

> 日期：2026-08-16  
> 范围：对照现有后端能力、API 路由与 TraeWork 新前端，判断哪些功能可以裁剪。  
> 结论先行：新前端已经是 TraeWork 聊天壳，后端仍挂着 33 个路由、约 15.5 万行 Python。瘦身的关键不是再抠几行代码，而是先砍掉没有入口的产品线。

## 诊断

现在的形状是「聊天壳 + 全家桶后端」。

- `frontend/src` 大约 6k 行，没有 Book、Learning、Co-Writer、Partners、Quiz、Space 这些路由。
- `deeptutor/api/main.py` 却还挂着整套旧产品面。
- 维护成本几乎全在后端。

建议按三档处理：**整条砍掉、收成一条、降成插件**。核心只留「聊天 + 一份知识库 + 简单记忆 + 可扩展工具」。

体量对照：

| 层 | 规模 |
|---|---|
| 后端 Python | ~155k 行（`deeptutor/`） |
| 服务层 | ~69k 行（`deeptutor/services`） |
| 前端 `frontend/src` | ~6.3k 行 |
| API 路由 | 33 个 |
| 内置 capability | 7 个 |
| RAG 引擎 | LlamaIndex / GraphRAG / LightRAG / LightRAG Server / PageIndex / IMA / Obsidian |
| 解析引擎 | MinerU / Docling / MarkItDown / LiteParse / PyMuPDF4LLM / text_only |
| 搜索供应商 | 13 家 |
| Partners IM 通道 | 16 条 |
| CLI Apps | 101 个 |

---

## 一档：整条产品线建议砍

这些都是独立编排器 / 工作台，新前端没有入口，和「学习对话」主路径平行。

| 模块 | 体量 | 为什么可以砍 |
|---|---|---|
| **Book Engine** | ~7.7k 行，且平行于 `ChatOrchestrator` | 独立生命周期（提案 → 书脊 → 逐页编译）。要书，用 `visualize` / `write_note` 或技能即可 |
| **Co-Writer** | ~0.6k + 独立 storage | 多文档共写工作台。聊天附件 + 笔记本已经覆盖 |
| **Mastery Path / Guided Learning** | ~4.7k + `/learning` + quiz judge | 题型门控、调度、题库回流。掌握度可以是 chat 里的一个 skill，不必是产品面 |
| **Deep Question** | ~3.4k | 出题流水线。chat + `ask_user` 就能出题 |
| **Partners / IM 渠道** | ~12k + 16 个通道 | Telegram / Discord / 飞书 / 企微 / QQ / 微信 / WhatsApp / Slack / Matrix / Zulip / Teams / Mattermost / 钉钉 / Napcat / Email / MoChat。这是另一款产品 |
| **101 个 CLI Apps** | catalog 来自 CLI-Anything | 和「辅导」无关，还要装、沙箱、授权。要自动化走 MCP / `exec` |
| **Question Notebook 与 Notebook 双轨** | 两套 API | 笔记留一套；题库若砍 Learning 就一起走 |
| **Personas / Soul 编辑器** | 独立路由 | 系统提示词即可，不必做成表面 |
| **Dashboard / Space** | 独立工作台 | 新壳已经是会话列表 |

GeoGebra / `vision_solver` 也建议下线：`COMING_SOON_TOOL_TYPES` 已空，但仍散落在 chat / solve 里，是半死功能。

---

## 二档：同类引擎只留一条

这是真正的复杂度来源：每多一个引擎，就多一套配置、探测、索引版本、失败路径和测试。

### 知识库（~7.5k）

现在有 LlamaIndex、GraphRAG、LightRAG、LightRAG Server、PageIndex、IMA、Obsidian。建议只留 **LlamaIndex（本地默认）+ PageIndex（文档推理，可选 extra）**。

- GraphRAG / LightRAG：索引重、依赖脆、Python 3.14 还要单独挡
- IMA：腾讯云托管检索，和本地 KB 不是一类东西
- Obsidian：做成「链一个文件夹当 KB」即可，不必独立 capability

### 文档解析（~3.1k）

MinerU / Docling / MarkItDown / LiteParse / PyMuPDF4LLM / text_only。建议 **LiteParse + PyMuPDF4LLM**，MinerU 降成 extra。默认安装不该拉 OCR 全家桶。

### 搜索（~2.9k，13 家）

Tavily / Brave / Serper / Jina / Perplexity / SearXNG / DuckDuckGo / Doubao / Bocha / Zhipu / Firecrawl / Qianfan / Aliyun IQS。建议 **Tavily 或 Brave + SearXNG（自托管）+ 国内一家**。其余走 OpenAI 兼容适配器，不要每家一个 provider 文件。

### 可视化

`visualize`（SVG / Chart.js / Mermaid / HTML）留下；`math_animator`（Manim，6 阶段流水线 + LaTeX / ffmpeg）保持 extra，默认包和 UI 都不要出现。

### 记忆（~6.3k）

L1 轨迹 + L2 摘要 + L3 综合 + Memory Graph + consolidator 四种 mode。建议 **L1 原文 + 一份可编辑的 `preferences.md`**。三层巩固和证据图是研究型功能，不是辅导最小集。

### 会话存储

SQLite 与 PocketBase 双轨。单用户只留 SQLite；多用户整包做成 extra，不要进默认安装。

---

## 三档：能力收进 chat，不要并列入口

`chat` 已经是带工具挂载的 agent loop。下面这些都可以变成 prompt / skill / 工具组合，而不是一级 capability：

| 现在 | 建议 |
|---|---|
| `deep_solve` | chat + `reason` + `code_execution` |
| `deep_research`（~5.2k，四阶段） | chat + `web_search` + `web_fetch` + `paper_search` |
| `visualize` | 留下，或收成一个 `visualize` 工具 |
| `mastery_path` | 随 Learning 一起砍 |
| `brainstorm` / `reason` | `reason` 可留；`brainstorm` 只是换了个 system prompt |

工具层同样偏多。建议默认只挂：`web_search`、`web_fetch`、`rag`、`read_source`、`exec` / `code_execution`、`read_memory` / `write_memory`、`ask_user`。`github`、`cron`、`media_gen`、`paper_search`、mastery 工具做成按需加载。

---

## 四档：集成降成 extra，不要进默认包

| 留下（核心） | extra / 插件 |
|---|---|
| OpenAI 兼容 + Anthropic | Codex OAuth、CodeBuddy、Copilot、Lemonade、Novita、Eden、Atlas… |
| Claude Code / Codex 各一个 subagent | Gemini CLI、Kimi、opencode、MiMo |
| MCP + Skills | 101 CLI Apps |
| 本地语音可选 | 内置 imagegen / videogen / voice 适配器矩阵 |

`deeptutor/services/llm` 已经 1 万行，再加一家网关就多一套鉴权、reasoning、token 限制。默认包只保证「填 base URL + key 能聊」。

Partners 若还要，最多留 **Telegram + 飞书**，其余通道删。16 条 IM 管线不是辅导产品该养的。

---

## 建议留下的最小产品

```
入口：Web 聊天（现 TraeWork 壳）+ CLI
运行时：ChatOrchestrator + 一套工具注册表
知识：LlamaIndex KB + 一种解析
记忆：preferences.md + 会话历史
扩展：MCP、Skills、可选 PageIndex / Manim / 多用户
```

按这个切，后端大概能从 **15.5 万行收到 6–8 万行**，API 路由从 33 个收到十来个。用户感知到的主路径不会变：对话、查资料、写笔记、跑代码。

---

## 建议的砍法顺序

1. **先停挂路由，不删代码**：Book、Co-Writer、Learning、Partners、CLI Apps、Question Notebook。新前端本来就没接，风险最低。
2. **RAG / 解析 / 搜索收口**：默认只暴露一套，其余标 deprecated。
3. **capability 合并进 chat**：`deep_question`、`deep_solve`、`mastery_path` 改 skill。
4. **最后再物理删除** 和补测试。先藏再删，回滚便宜。

不建议先动：chat loop、session / WS、LlamaIndex 摄入、设置里的模型配置。那是现在唯一还在被新前端打到的路径。

落地时下一刀建议做第 1 步：把无 UI 的路由改成 feature flag 默认关闭，并列一张「删除清单 + 依赖方」。
