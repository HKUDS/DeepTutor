<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor：迈向智能体驱动的个性化辅导

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/HKUDS/DeepTutor?style=flat-square)](https://github.com/HKUDS/DeepTutor/commits)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[核心亮点](#key-features) · [快速开始](#get-started) · [探索 DeepTutor](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [社区](#community)

[🇬🇧 English](../../README.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

---
### 📰 动态

> **[2026.3.24]** 久等了！✨ DeepTutor v1.0.0 正式发布 —— 在 Apache-2.0 许可下的智能体原生演进：轻量重构、TutorBot、灵活模式切换。新篇章开启，故事继续！

> **[2026.2.6]** 🚀 仅用 39 天即突破 10k star！感谢社区的大力支持！

> **[2026.1.1]** 新年快乐！欢迎加入 [Discord](https://discord.gg/eRsjPgMU4t)、[微信](https://github.com/HKUDS/DeepTutor/issues/78) 或 [Discussions](https://github.com/HKUDS/DeepTutor/discussions)，一起塑造 DeepTutor 的未来！

> **[2025.12.29]** DeepTutor 正式发布！

### 📦 版本发布

> **[2026.3.24]** [v1.0.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0) — 智能体原生重构、灵活工具集成、CLI 与 SDK 入口、基于 nanobot 的 TutorBot、Co-Writer、引导式学习与持久记忆。更轻、更快、更好用！

<details>
<summary><b>历史版本</b></summary>

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — 会话持久化、增量文档上传、灵活 RAG 流水线导入与完整中文本地化。

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — RAG-Anything 支持 Docling、日志优化与问题修复。

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — 统一服务配置、按知识库选择 RAG 流水线、出题改版与侧栏定制。

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — 多提供商 LLM 与嵌入、新首页、RAG 解耦与环境变量重构。

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — 统一 PromptManager、GitHub Actions CI/CD 与 GHCR 预构建镜像。

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker 部署、Next.js 16 与 React 19、WebSocket 加固与关键漏洞修复。

</details>

<a id="key-features"></a>
## ✨ 核心亮点

- **统一聊天工作区** — 五种模式，同一条对话线。聊天、深度解题、测验生成、深度研究与数学动画共享上下文：从闲聊到多智能体解题、出题、再深入调研，消息不丢。
- **个人 TutorBot** — 不是聊天机器人，而是自主导师。每个 TutorBot 拥有独立工作区、记忆、人格与技能；可提醒、可学新能力、随你成长。由 [nanobot](https://github.com/HKUDS/nanobot) 驱动。
- **AI Co-Writer** — Markdown 编辑器中 AI 是一等协作者。划选文本即可改写、扩写或缩写，可结合知识库与网络；内容可沉淀到笔记本，反哺学习闭环。
- **引导式学习** — 把资料变成结构化、可视化的学习路径：多步计划、每步交互页面、步步可讨论。
- **知识中枢** — 上传 PDF、Markdown、纯文本构建 RAG 知识库；用彩色笔记本跨会话整理洞见。文档主动参与每次对话。
- **持久记忆** — 持续勾勒你的学习画像：学过什么、如何学习、目标何在。全功能与 TutorBot 共享，越用越准。
- **智能体原生 CLI** — 能力、知识库、会话、TutorBot 一条命令可达；终端 Rich 输出给人看，JSON 给智能体与流水线。将根目录 [`SKILL.md`](../../SKILL.md) 交给智能体即可自主操作。

---

<a id="get-started"></a>
## 🚀 快速开始

### 方案 A — 引导式安装（推荐）

**一条交互脚本**完成依赖安装、环境配置、连通性检测与启动，无需手改 `.env`。

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# 创建 Python 环境
conda create -n deeptutor python=3.11 && conda activate deeptutor
# 或：python -m venv .venv && source .venv/bin/activate

# 启动引导
python scripts/start_tour.py
```

向导会询问使用方式：

- **Web 模式**（推荐）— 选择依赖配置、安装 pip + npm、拉起临时服务并在浏览器打开**设置**页；四步引导配置 LLM、嵌入与搜索并现场测通；完成后自动按配置重启。
- **CLI 模式** — 全终端交互：选配置、装依赖、配提供商、验证连接并应用，无需离开 shell。

完成后访问 [http://localhost:3782](http://localhost:3782)。

<a id="option-b-manual"></a>
### 方案 B — 本地手动安装

若希望完全自控，可自行安装与配置。

**1. 安装依赖**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
pip install -e ".[server]"

# 前端
cd web && npm install && cd ..
```

**2. 配置环境**

```bash
cp .env.example .env
```

编辑 `.env`，至少填写必填项：

```dotenv
# LLM（必填）
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# 嵌入（知识库必填）
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

**3. 启动服务**

```bash
# 后端（FastAPI）
python -m deeptutor.api.run_server

# 前端（Next.js）— 另开终端
cd web && npm run dev -- -p 3782
```

| 服务 | 默认端口 |
|:---:|:---:|
| 后端 | `8001` |
| 前端 | `3782` |

浏览器打开 [http://localhost:3782](http://localhost:3782)。

### 方案 C — Docker 部署

Docker 将前后端打包为单容器，本机无需 Python/Node。任选其一：

**1. 配置环境变量**（两种方式均需）

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

编辑 `.env`，填写必填项（与[方案 B](#option-b-manual)相同）。

**2a. 拉取官方镜像（推荐）**

镜像发布于 [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor)，支持 `linux/amd64` 与 `linux/arm64`。

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

固定版本可编辑 `docker-compose.ghcr.yml` 中的镜像标签：

```yaml
image: ghcr.io/hkuds/deeptutor:1.0.0  # 或 :latest
```

**2b. 源码构建**

```bash
docker compose up -d
```

本地根据 `Dockerfile` 构建并启动。

**3. 验证与管理**

容器健康后打开 [http://localhost:3782](http://localhost:3782)。

```bash
docker compose logs -f   # 查看日志
docker compose down       # 停止并移除容器
```

<details>
<summary><b>云端 / 远程部署</b></summary>

远程部署时，浏览器需知晓后端公网地址。在 `.env` 中增加：

```dotenv
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

前端启动脚本会在运行时应用，无需重新构建。

</details>

<details>
<summary><b>开发模式（热重载）</b></summary>

叠加 dev 覆盖以挂载源码并热重载：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

`deeptutor/`、`deeptutor_cli/`、`scripts/`、`web/` 的修改会即时生效。

</details>

<details>
<summary><b>自定义端口</b></summary>

在 `.env` 中覆盖：

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

然后重启：

```bash
docker compose up -d     # 或 docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>数据持久化</b></summary>

用户数据与知识库通过卷映射到本地：

| 容器内路径 | 宿主机路径 | 内容 |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | 设置、记忆、工作区、会话、日志 |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | 上传文档与向量索引 |

`docker compose down` 后目录仍保留，下次 `up` 会复用。

</details>

<details>
<summary><b>环境变量参考</b></summary>

| 变量 | 必填 | 说明 |
|:---|:---:|:---|
| `LLM_BINDING` | **是** | LLM 提供商（`openai`、`anthropic` 等） |
| `LLM_MODEL` | **是** | 模型名（如 `gpt-4o`） |
| `LLM_API_KEY` | **是** | API 密钥 |
| `LLM_HOST` | **是** | API 地址 |
| `EMBEDDING_BINDING` | **是** | 嵌入提供商 |
| `EMBEDDING_MODEL` | **是** | 嵌入模型名 |
| `EMBEDDING_API_KEY` | **是** | 嵌入 API 密钥 |
| `EMBEDDING_HOST` | **是** | 嵌入端点 |
| `EMBEDDING_DIMENSION` | **是** | 向量维度 |
| `SEARCH_PROVIDER` | 否 | 搜索（`tavily`、`jina`、`serper`、`perplexity` 等） |
| `SEARCH_API_KEY` | 否 | 搜索 API 密钥 |
| `BACKEND_PORT` | 否 | 后端端口（默认 `8001`） |
| `FRONTEND_PORT` | 否 | 前端端口（默认 `3782`） |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | 否 | 云端部署时后端公网 URL |
| `DISABLE_SSL_VERIFY` | 否 | 关闭 SSL 校验（默认 `false`） |

</details>

### 方案 D — 仅 CLI

若只要 CLI、不要 Web 前端：

```bash
pip install -e ".[cli]"
deeptutor chat                                   # 交互 REPL
deeptutor run chat "Explain Fourier transform"   # 单次能力调用
deeptutor run deep_solve "Solve x^2 = 4"         # 多智能体解题
deeptutor kb create my-kb --doc textbook.pdf     # 构建知识库
```

> 完整 CLI 说明与命令表见 [DeepTutor CLI](#deeptutor-cli-guide)。

---

<a id="explore-deeptutor"></a>
## 📖 探索 DeepTutor

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="DeepTutor 架构" width="800">
</div>

### 💬 聊天 — 统一智能工作区

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="聊天工作区" width="800">
</div>

五种模式共处同一工作区，由**统一上下文管理**串联：历史、知识库与引用跨模式保留，同一主题下可随时切换。

| 模式 | 作用 |
|:---|:---|
| **聊天** | 工具增强对话：RAG、联网搜索、代码执行、深度推理、头脑风暴、论文检索，按需组合。 |
| **深度解题** | 多智能体解题：规划、检索、求解与验证，步步可溯源引用。 |
| **测验生成** | 基于知识库出题，内置校验。 |
| **深度研究** | 主题拆解、并行调研 RAG/网络/论文，输出带引用报告。 |
| **数学动画** | 基于 Manim 将数学概念可视化为动画与分镜。 |

工具与**工作流解耦**：每种模式下你可自选启用哪些工具、用几个、或完全不用；流程负责推理节奏，工具由你编排。

> 从快速聊天起步，难题切到深度解题，自测用测验，再开深度研究深挖 —— 同一条对话线贯穿始终。

### ✍️ Co-Writer — 编辑器里的 AI

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

Co-Writer 把聊天的智能放进写作界面：完整 Markdown 编辑器，AI 是**一等协作者**，而非侧栏挂件。

划选文本即可**改写**、**扩写**或**缩写**，可选用知识库或网络上下文；支持撤销/重做，作品可存入笔记本，回流学习生态。

### 🎓 引导式学习 — 可视化、分步掌握

<div align="center">
<img src="../../assets/figs/dt-guide.png" alt="引导式学习" width="800">
</div>

将个人材料变成结构化、多步学习路径：给出主题，可选关联笔记本记录，DeepTutor 将：

1. **设计学习计划** — 从材料中提炼 3–5 个递进知识点。  
2. **生成交互页面** — 每点对应富视觉 HTML 页面，含讲解、图示与示例。  
3. **上下文问答** — 每步旁路聊天，深入探讨。  
4. **学习小结** — 结束后汇总所学。

会话可暂停、恢复或回看任一步。

### 📚 知识管理 — 学习基础设施

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="知识管理" width="800">
</div>

在此构建与管理驱动全局的文档集合。

- **知识库** — 上传 PDF、TXT、Markdown，形成可检索、RAG 就绪的集合；可增量追加。  
- **笔记本** — 跨会话整理学习记录；聊天、引导学习、Co-Writer、深度研究的洞见可按色分类保存。

知识库不是冷存储 —— 它主动参与每次对话、研究与学习路径。

### 🧠 记忆 — 与你一同成长

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="记忆" width="800">
</div>

DeepTutor 从两个互补维度持续理解你：

- **摘要** — 学习进度流水账：学过什么、探索过哪些主题、理解如何演进。  
- **学习画像** — 学习者身份：偏好、水平、目标与沟通风格，随交互自动精炼。

记忆在全功能与 TutorBot 间共享；用得越多，越贴合你。

---

<a id="tutorbot"></a>
### 🦞 TutorBot — 持久、自主的 AI 导师

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="TutorBot 架构" width="800">
</div>

TutorBot 不是聊天机器人 —— 它是基于 [nanobot](https://github.com/HKUDS/nanobot) 的**持久、可多实例**智能体。每个实例独立循环、工作区、记忆与人格；你可同时运行多个角色，各自演进。

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Soul 模板** — 通过可编辑 Soul 文件定义人格、语气与教学理念；可选内置原型或完全自定义。  
- **独立工作区** — 每实例独立目录：记忆、会话、技能与配置隔离，仍可访问 DeepTutor 共享知识层。  
- **主动心跳** — 不止被动回复：心跳系统支持定期学习提醒、复习与计划任务。  
- **完整工具** — RAG、代码执行、联网、论文检索、深度推理、头脑风暴。  
- **技能扩展** — 在工作区添加技能文件即可教会新能力。  
- **多通道** — 可接 Telegram、Discord、Slack、飞书、企业微信、钉钉、邮件等。  
- **团队与子智能体** — 后台子任务或多智能体协作，应对长程复杂任务。

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list                  # 查看所有导师实例
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI — 智能体原生界面

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="DeepTutor CLI 架构" width="800">
</div>

DeepTutor **全面 CLI 化**：能力、知识库、会话、记忆、TutorBot 均可命令行操作，无需浏览器。终端 Rich 输出面向人类，JSON 面向智能体与流水线。

将项目根目录 [`SKILL.md`](../../SKILL.md) 交给任意支持工具的代理（[nanobot](https://github.com/HKUDS/nanobot) 或其他 LLM），即可自主配置与操作。

**单次执行** — 终端直接跑任意能力：

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
```

**交互 REPL** — 持久会话，运行时切换模式：

```bash
deeptutor chat --capability deep_solve --kb my-kb
# REPL 内：/cap、/tool、/kb、/history、/notebook、/config 等即时切换
```

**知识库闭环** — 终端完成建库、追加与检索：

```bash
deeptutor kb create my-kb --doc textbook.pdf
deeptutor kb add my-kb --docs-dir ./papers/
deeptutor kb search my-kb "gradient descent"
deeptutor kb set-default my-kb
```

**双输出模式** — Rich 给人看，JSON 给管道：

```bash
deeptutor run chat "Summarize chapter 3" -f rich
deeptutor run chat "Summarize chapter 3" -f json
```

**会话续接** — 断点续聊：

```bash
deeptutor session list
deeptutor session open <id>
```

<details>
<summary><b>CLI 命令参考（完整）</b></summary>

**顶层**

| 命令 | 说明 |
|:---|:---|
| `deeptutor run <capability> <message>` | 单次执行能力（`chat`、`deep_solve`、`deep_question`、`deep_research`、`math_animator`） |
| `deeptutor chat` | 交互 REPL，可选 `--capability`、`--tool`、`--kb`、`--language` |
| `deeptutor serve` | 启动 API 服务 |

**`deeptutor bot`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor bot list` | 列出 TutorBot |
| `deeptutor bot create <id>` | 创建并启动（`--name`、`--persona`、`--model`） |
| `deeptutor bot start <id>` | 启动 |
| `deeptutor bot stop <id>` | 停止 |

**`deeptutor kb`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor kb list` | 列出知识库 |
| `deeptutor kb info <name>` | 详情 |
| `deeptutor kb create <name>` | 从文档创建（`--doc`、`--docs-dir`） |
| `deeptutor kb add <name>` | 增量添加 |
| `deeptutor kb search <name> <query>` | 检索 |
| `deeptutor kb set-default <name>` | 设为默认 |
| `deeptutor kb delete <name>` | 删除（`--force`） |

**`deeptutor memory`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor memory show [file]` | 查看（`summary`、`profile`、`all`） |
| `deeptutor memory clear [file]` | 清空（`--force`） |

**`deeptutor session`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor session list` | 列表（`--limit`） |
| `deeptutor session show <id>` | 消息 |
| `deeptutor session open <id>` | REPL 续聊 |
| `deeptutor session rename <id>` | 重命名（`--title`） |
| `deeptutor session delete <id>` | 删除 |

**`deeptutor notebook`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor notebook list` | 列表 |
| `deeptutor notebook create <name>` | 创建（`--description`） |
| `deeptutor notebook show <id>` | 记录 |
| `deeptutor notebook add-md <id> <path>` | 导入 Markdown |
| `deeptutor notebook replace-md <id> <rec> <path>` | 替换记录 |
| `deeptutor notebook remove-record <id> <rec>` | 删除记录 |

**`deeptutor config` / `plugin` / `provider`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor config show` | 配置摘要 |
| `deeptutor plugin list` | 已注册工具与能力 |
| `deeptutor plugin info <name>` | 工具或能力详情 |
| `deeptutor provider login <provider>` | OAuth（`openai-codex`、`github-copilot`） |

</details>

<a id="community"></a>
## 🌐 社区与生态

DeepTutor 受益于优秀开源项目：

| 项目 | 在 DeepTutor 中的角色 |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | 驱动 TutorBot 的轻量智能体引擎 |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG 与文档索引骨干 |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | 数学动画（Math Animator）的 AI 生成 |

**HKUDS 生态：**

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| 简洁高速 RAG | 零代码智能体框架 | 自动化研究 | 超轻量 AI 智能体 |


## 🤝 参与贡献

<div align="center">

希望 DeepTutor 能成为送给社区的一份礼物。🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

请参阅 [CONTRIBUTING.md](../../CONTRIBUTING.md) 了解开发环境、规范与 PR 流程。

## ⭐ Star 历史

<div align="center">

<a href="https://www.star-history.com/#HKUDS/DeepTutor&type=timeline&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
  </picture>
</a>

</div>

<div align="center">

**[Data Intelligence Lab @ HKU](https://github.com/HKUDS)**

[⭐ Star](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 反馈问题](https://github.com/HKUDS/DeepTutor/issues) · [💬 讨论](https://github.com/HKUDS/DeepTutor/discussions)

---

采用 [Apache License 2.0](../../LICENSE) 许可。

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
