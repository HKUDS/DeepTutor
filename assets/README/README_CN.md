<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor：智能体原生的个性化辅导

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[核心亮点](#key-features) · [快速开始](#get-started) · [探索 DeepTutor](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli) · [多用户](#multi-user) · [路线图](#roadmap) · [社区](#community)

[🇬🇧 English](../../README.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **欢迎各种形式的贡献！** 分支策略、编码规范与上手方式见 [贡献指南](../../CONTRIBUTING.md)。

### 📦 版本发布

> **[2026.5.10]** [v1.3.10](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.10) — 修复远程 Docker CORS、SDK Provider 的 `DISABLE_SSL_VERIFY`、代码块引用误注入，并将 Matrix E2EE 改为可选扩展。

> **[2026.5.9]** [v1.3.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.9) — TutorBot 支持 Zulip 与 NVIDIA NIM，思考模型路由更安全，新增 `deeptutor start`，侧栏提示与会话存储一致性提升。

> **[2026.5.8]** [v1.3.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.8) — 可选多用户部署，隔离用户工作区、管理员授权、认证路由与作用域运行时访问。

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — 思考模型/提供商修复，知识索引历史可见，Co-Writer 清空与模板编辑更安全。

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — 聊天与 TutorBot 基于目录的模型选择，更安全的 RAG 重建索引，OpenAI Responses token 上限修复，Skills 编辑器校验。

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — 本地启动设置更顺滑，RAG 查询更安全，本地嵌入鉴权更清晰，设置页深色模式打磨。

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — 书籍页对话持久化与重建流程，聊天到书籍引用，语言/推理处理增强，RAG 文档抽取加固。

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — NVIDIA NIM 与 Gemini 嵌入支持，统一 Space 上下文（聊天历史/技能/记忆），会话快照，RAG 重建索引韧性。

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — 嵌入端点 URL 透明可读，无效持久化向量时 RAG 重建索引韧性，思考模型输出记忆清理，Deep Solve 运行时修复。

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — 稳定性：更安全的 RAG 路由与嵌入校验，Docker 持久化，输入法友好输入，Windows/GBK 健壮性。

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — 版本化知识库索引与重建工作流，知识工作区重构，嵌入自动发现与新适配器，Space 枢纽。

<details>
<summary><b>更早发布（两周以前）</b></summary>

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — 聊天附件持久化与文件预览抽屉，感知附件的能力流水线，TutorBot Markdown 导出。

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — 文本/代码/SVG 附件，一键 Setup Tour，Markdown 聊天导出，紧凑知识库管理界面。

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — 文档附件（PDF/DOCX/XLSX/PPTX），推理思维块展示，Soul 模板编辑器，Co-Writer 保存至笔记本。

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — 用户自建 Skills 体系，聊天输入性能重构，TutorBot 自动启动，图书库 UI，可视化全屏。

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — 分阶段 token 上限，各入口重新生成回复，RAG 与 Gemma 兼容性修复。

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Book Engine「活书」编译器，多文档 Co-Writer，交互式 HTML 可视化，题库 @ 提及。

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — 基于 Schema 的 Channels 标签页，RAG 单一流水线收敛，聊天提示外置。

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — 通用「立即回答」，Co-Writer 滚动同步，统一设置面板，流式停止按钮。

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — LaTeX 块级公式重构，LLM 诊断探测，Docker 与本地 LLM 说明。

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — 可收藏会话，Snow 主题，WebSocket 心跳与自动重连，嵌入注册表重构。

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — 题目笔记本（书签与分类），Visualize 支持 Mermaid，嵌入不匹配检测，Qwen/vLLM 兼容，LM Studio 与 llama.cpp，Glass 主题。

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — 搜索整合与 SearXNG 回退，提供商切换修复，前端资源泄漏修复。

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — Visualize（Chart.js/SVG），测验去重，o4-mini。

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — 嵌入进度与限流重试，跨平台依赖修复，MIME 校验修复。

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — 原生 OpenAI/Anthropic SDK（移除 litellm），Windows 数学动画，健壮 JSON 解析，完整中文 i18n。

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — 设置热重载，MinerU 嵌套输出，WebSocket 修复，最低 Python 3.11+。

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — 智能体原生架构重写（约 20 万行）：Tools + Capabilities、CLI 与 SDK、TutorBot、Co-Writer、引导学习与持久记忆。

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — 会话持久化，增量上传，灵活 RAG 导入，完整中文本地化。

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — RAG-Anything 支持 Docling，日志优化与修复。

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — 统一服务配置，按知识库选择 RAG，出题改版，侧栏定制。

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — 多提供商 LLM/嵌入，新首页，RAG 解耦，环境变量重构。

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — 统一 PromptManager，GitHub Actions CI/CD，GHCR 预构建镜像。

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker，Next.js 16 与 React 19，WebSocket 加固，关键漏洞修复。

</details>

### 📰 动态

> **[2026.4.19]** 🎉 111 天内突破 20k star！感谢支持 —— 我们会持续迭代，让个性化智能辅导惠及更多人。

> **[2026.4.10]** 📄 论文已上线 arXiv，阅读[预印本](https://arxiv.org/abs/2604.26962)了解设计与思路。

> **[2026.4.4]** 好久不见！✨ DeepTutor v1.0.0：Apache-2.0 下的智能体原生演进，架构重写、TutorBot、灵活模式切换。新篇章开启。

> **[2026.2.6]** 🚀 39 天突破 10k star！感谢社区！

> **[2026.1.1]** 新年快乐！欢迎加入 [Discord](https://discord.gg/eRsjPgMU4t)、[微信](https://github.com/HKUDS/DeepTutor/issues/78) 或 [Discussions](https://github.com/HKUDS/DeepTutor/discussions)。

> **[2025.12.29]** DeepTutor 正式发布！

<a id="key-features"></a>
## ✨ 核心亮点

- **统一聊天工作区** — 六种模式，一条线程。聊天、深度解题、测验生成、深度研究、数学动画与可视化共享上下文：从对话到多智能体解题、出题、可视化，再深入调研，消息不丢。
- **AI Co-Writer** — 多文档 Markdown 工作区，AI 是一等协作者。划选文本即可改写、扩展或缩写，可结合知识库与网络；内容回流到你的学习闭环。
- **Book Engine** — 将资料变为结构化、交互式「活书」。多智能体流水线设计大纲、检索来源并编译页面，含 **13** 种块类型：测验、闪卡、时间线、概念图、交互演示等。
- **知识中枢** — 上传 PDF、Markdown、文本等构建 RAG 知识库；彩色笔记本整理洞见；题库回顾测验；自定义 Skill 塑造教学风格。文档主动驱动每次对话。
- **持久记忆** — 勾勒学习画像：学过什么、如何学习、去向何方。全功能与 TutorBot 共享，越用越准。
- **个人 TutorBot** — 非聊天机器人，而是自主导师。独立工作区、记忆、人格与技能；提醒、学新能力、随你成长。由 [nanobot](https://github.com/HKUDS/nanobot) 驱动。
- **智能体原生 CLI** — 能力、知识库、会话、TutorBot 一条命令；Rich 给人看，JSON 给智能体。将根目录 [`SKILL.md`](../../SKILL.md) 交给工具型智能体即可自主操作。
- **可选身份认证** — 本地默认关闭；公网托管时改两个环境变量即可要求登录。多用户支持 bcrypt 密码、JWT 会话、自助注册页与内置管理后台。可选用 **PocketBase** 承载认证与存储（OAuth 友好、并发更佳），作为可选侧车接入，无需改代码。

---

<a id="get-started"></a>
## 🚀 快速开始

### 前提条件

开始前请确认已安装：

| 依赖 | 版本 | 检查 | 说明 |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | 任意 | `git --version` | 克隆仓库 |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | 后端 |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | 本地 Web 前端 |
| [npm](https://www.npmjs.com/) | 随 Node 附带 | `npm --version` | 随 Node 安装 |

> **仅 Windows（缺少编译器）：** 若未安装 Visual Studio，请安装 [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)，并勾选 **使用 C++ 的桌面开发** 工作负载。

至少准备一个 LLM 提供商的 **API Key**（如 [OpenAI](https://platform.openai.com/api-keys)、[DeepSeek](https://platform.deepseek.com/)、[Anthropic](https://console.anthropic.com/)）。Setup Tour 会引导填写。

### 方案 A — Setup Tour（推荐）

面向首次本地 Web 安装的 CLI 向导：检查环境、安装 Python/Node 依赖、写入 `.env`，并可选用 TutorBot、Matrix、数学动画等扩展。

**1. 克隆仓库**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

**2. 创建并激活 Python 环境**

任选其一。

macOS / Linux（`venv`）：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell（`venv`）：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Anaconda / Miniconda：

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
```

**3. 启动向导**

```bash
python scripts/start_tour.py
```

安装步骤中会询问依赖组合：

| 选项 | 安装内容 | 适用场景 |
|:---|:---|:---|
| Web app（推荐） | CLI + API + RAG/文档解析 | 大多数首次用户 |
| Web + TutorBot | 增加 TutorBot 与常见频道 SDK | 需要自主导师或频道集成 |
| Web + TutorBot + Matrix | 非 E2EE Matrix/Element | 需要 Matrix/Element 房间；加密房间再单独安装 `matrix-e2e` |
| 数学动画扩展 | 单独安装 Manim | 需要动画且已备好 LaTeX/ffmpeg 等 |

向导结束后：

```bash
python scripts/start_web.py
```

> **日常启动** — 向导只需跑一次。之后保持虚拟环境激活，执行 `python scripts/start_web.py` 同时启动前后端；前端 URL 会在终端打印。仅在重配提供商、改端口或加装扩展时再跑 `start_tour.py`。

> **更新本地安装** — 若以方案 A 或 B 从 git 克隆安装，可运行 `python scripts/update.py`：拉取当前分支远端、展示本地与远端提交差、确认分支映射后执行安全的 fast-forward pull。

<a id="option-b--manual-local-install"></a>
### 方案 B — 手动本地安装

希望逐步执行命令时使用本路径。

**1. 克隆仓库**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

**2. 创建并激活 Python 环境**

同上，任选一种 venv/conda 方式。

**3. 安装依赖**

```bash
# 后端 + Web：含 CLI、RAG、文档解析与内置 LLM SDK
python -m pip install -e ".[server]"

# 可选扩展（按需）：
#   python -m pip install -e ".[tutorbot]"
#   python -m pip install -e ".[tutorbot,matrix]"  # 非 E2EE Matrix，无需 libolm
#   python -m pip install -e ".[matrix-e2e]"       # 加密 Matrix 房间；需要 libolm
#   python -m pip install -e ".[math-animator]"
#   python -m pip install -e ".[all]"

# 前端，需要 Node.js 20.9+
cd web
npm install
cd ..
```

**4. 配置环境**

```bash
cp .env.example .env
```

编辑 `.env`，至少填写 LLM 相关字段。若暂只试用聊天，嵌入字段可稍后填写（知识库功能需要）。

```dotenv
# LLM（聊天必需）
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# 嵌入（知识库 / RAG 必需）
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
# v1.3.0+：填写完整端点 URL，而非仅 https://api.openai.com/v1
EMBEDDING_HOST=https://api.openai.com/v1/embeddings
# 除非需强制维度，否则留空
EMBEDDING_DIMENSION=
```

<details>
<summary><b>支持的 LLM 提供商</b></summary>

| Provider | Binding | Default Base URL |
|:--|:--|:--|
| AiHubMix | `aihubmix` | `https://aihubmix.com/v1` |
| Anthropic | `anthropic` | `https://api.anthropic.com/v1` |
| Azure OpenAI | `azure_openai` | — |
| BytePlus | `byteplus` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| BytePlus Coding Plan | `byteplus_coding_plan` | `https://ark.ap-southeast.bytepluses.com/api/coding/v3` |
| Custom | `custom` | — |
| Custom (Anthropic API) | `custom_anthropic` | — |
| DashScope | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| DeepSeek | `deepseek` | `https://api.deepseek.com` |
| Gemini | `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| GitHub Copilot | `github_copilot` | `https://api.githubcopilot.com` |
| Groq | `groq` | `https://api.groq.com/openai/v1` |
| llama.cpp | `llama_cpp` | `http://localhost:8080/v1` |
| LM Studio | `lm_studio` | `http://localhost:1234/v1` |
| MiniMax | `minimax` | `https://api.minimaxi.com/v1` |
| MiniMax (Anthropic) | `minimax_anthropic` | `https://api.minimaxi.com/anthropic` |
| Mistral | `mistral` | `https://api.mistral.ai/v1` |
| Moonshot | `moonshot` | `https://api.moonshot.cn/v1` |
| Ollama | `ollama` | `http://localhost:11434/v1` |
| OpenAI | `openai` | `https://api.openai.com/v1` |
| OpenAI Codex | `openai_codex` | `https://chatgpt.com/backend-api` |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` |
| OpenVINO Model Server | `ovms` | `http://localhost:8000/v3` |
| Qianfan | `qianfan` | `https://qianfan.baidubce.com/v2` |
| SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1` |
| Step Fun | `stepfun` | `https://api.stepfun.com/v1` |
| vLLM/Local | `vllm` | — |
| VolcEngine | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| VolcEngine Coding Plan | `volcengine_coding_plan` | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| Xiaomi MIMO | `xiaomi_mimo` | `https://api.xiaomimimo.com/v1` |
| Zhipu AI | `zhipu` | `https://open.bigmodel.cn/api/paas/v4` |

</details>

<details>
<summary><b>支持的嵌入提供商</b></summary>

| Provider | Binding | Model Example | Default Dim |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | deployment name | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | Any embedding model | — |
| Any OpenAI-compatible | `custom` | — | — |

兼容 OpenAI 的提供商（DashScope、SiliconFlow 等）可通过 `custom` 或 `openai` binding 使用。

</details>

<details>
<summary><b>支持的网页搜索提供商</b></summary>

| Provider | Env Key | Notes |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | 推荐，有免费档 |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | 经 Serper 的 Google 结果 |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | 自建，无需 Key |
| DuckDuckGo | — | 无需 Key |
| Perplexity | `PERPLEXITY_API_KEY` | 需要 Key |

</details>

**5. 启动服务**

最快方式：

```bash
python scripts/start_web.py
```

也可分终端手动启动：

```bash
python -m deeptutor.api.run_server
# 另一终端
cd web && npm run dev -- -p 3782
```

| 服务 | 默认端口 |
|:---:|:---:|
| 后端 | `8001` |
| 前端 | `3782` |

浏览器打开 [http://localhost:3782](http://localhost:3782)。

### 方案 C — Docker

单容器封装前后端，无需本地 Python/Node。需 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Linux 可用 Docker Engine + Compose）。

**1. 配置环境变量**（下面两种方式都需要）

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

编辑 `.env`，必填项与 [方案 B](#option-b--manual-local-install) 相同。

**2a. 拉取官方镜像（推荐）**

镜像发布在 [GHCR](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor)，支持 `linux/amd64` 与 `linux/arm64`。

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

固定版本可改 `docker-compose.ghcr.yml` 中的 tag：

```yaml
image: ghcr.io/hkuds/deeptutor:1.3.4  # 或 :latest
```

**2b. 源码构建**

```bash
docker compose up -d
```

**3. 验证与管理**

容器健康后访问 [http://localhost:3782](http://localhost:3782)。

```bash
docker compose logs -f   # 跟踪日志
docker compose down       # 停止并移除容器
```

<details>
<summary><b>云端 / 远程部署</b></summary>

远程部署时，浏览器需知道后端公网地址，在 `.env` 增加：

```dotenv
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

前端启动脚本会在运行时注入，无需重建镜像。

</details>

<details>
<summary><b>认证（公网部署）</b></summary>

认证**默认关闭**，本地无需登录。多租户（每用户工作区、管理员配置模型/知识库/技能、审计日志）详见下文 [多用户](#multi-user)。

**无头单用户（不走 `/register`）：** 若无法在浏览器创建首个管理员（如无值守容器），可用环境变量预置：

```bash
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<粘贴 bcrypt 哈希>
AUTH_SECRET=your-secret-here
```

该路径视为单一管理员账户。若之后在浏览器完成注册流程，磁盘上的 `multi-user/_system/auth/users.json` 优先，环境变量作为回退。

</details>

<details>
<summary><b>PocketBase 侧车（可选认证与存储）</b></summary>

PocketBase 可替代内置 SQLite/JSON 认证与会话存储，提供 OAuth 友好认证、实时订阅与管理后台；不设 `POCKETBASE_URL` 即可随时切回。

> ⚠️ **当前 PocketBase 模式仅适合单用户。** 默认 schema 的 `users` 无 `role`（登录均为 `role=user`，无法创建管理员），会话/消息/轮次查询未按 `user_id` 过滤。**多用户部署请保持 `POCKETBASE_URL` 为空**，使用默认 JSON/SQLite 后端。

**适用：** 本地单用户，希望 OAuth 与管理界面，暂不关心每用户隔离。

**Docker Compose 快速开始：**

```bash
docker compose up -d
open http://localhost:8090/_/
pip install pocketbase
python scripts/pb_setup.py
# 再在 .env 启用 PocketBase 并重启
```

**`.env` 追加：**

```dotenv
POCKETBASE_URL=http://localhost:8090
POCKETBASE_ADMIN_EMAIL=admin@example.com
POCKETBASE_ADMIN_PASSWORD=your-admin-password
```

**devenv：**

```bash
devenv up
```

删除或不设置 `POCKETBASE_URL` 即可回到内置后端（新会话无需迁移）。

</details>

<details>
<summary><b>开发模式（热重载）</b></summary>

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

`deeptutor/`、`deeptutor_cli/`、`scripts/`、`web/` 变更会即时反映。

</details>

<details>
<summary><b>自定义端口</b></summary>

`.env`：

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

重启 `docker compose up -d`（或 ghcr 编排文件）。

</details>

<details>
<summary><b>数据持久化</b></summary>

| 容器路径 | 主机路径 | 内容 |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | 设置、工作区、会话、日志 |
| `/app/data/memory` | `./data/memory` | 长期记忆（`SUMMARY.md`、`PROFILE.md`） |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | 文档与向量索引 |

`docker compose down` 后目录仍保留。

</details>

<details>
<summary><b>环境变量参考</b></summary>

> 权威、带完整注释的列表见 [`.env.example`](../../.env.example)。下表列出多数用户会接触到的变量。

| 变量 | 必填 | 说明 |
|:---|:---:|:---|
| `LLM_BINDING` | **是** | LLM 提供商（`openai`、`anthropic`、`deepseek` 等） |
| `LLM_MODEL` | **是** | 模型名称（如 `gpt-4o`） |
| `LLM_API_KEY` | **是** | LLM API 密钥 |
| `LLM_HOST` | **是** | Chat Completions 基 URL |
| `LLM_API_VERSION` | 否 | 使用 Azure OpenAI 时需要；否则留空 |
| `LLM_REASONING_EFFORT` | 否 | DeepSeek 的 `high`/`max`/`minimal` 或 OpenAI o 系列的 `low`/`medium`/`high` |
| `EMBEDDING_BINDING` | 仅知识库 | 嵌入提供商 |
| `EMBEDDING_MODEL` | 仅知识库 | 嵌入模型名称 |
| `EMBEDDING_API_KEY` | 仅知识库 | 嵌入 API 密钥 |
| `EMBEDDING_HOST` | 仅知识库 | 嵌入端点完整 URL（v1.3.0+ 按原文请求，不自动追加路径） |
| `EMBEDDING_DIMENSION` | 否 | 向量维度；留空则自动检测 |
| `EMBEDDING_SEND_DIMENSIONS` | 否 | 三态：`true`/`false`/留空（自动） |
| `SEARCH_PROVIDER` | 否 | `brave`、`tavily`、`serper`、`jina`、`perplexity`、`searxng`、`duckduckgo` |
| `SEARCH_API_KEY` | 否 | 搜索 API 密钥 |
| `SEARCH_BASE_URL` | 否 | 自建 SearXNG 时需要 |
| `SEARCH_PROXY` | 否 | 出站搜索流量的可选 HTTP/HTTPS 代理 |
| `BACKEND_PORT` | 否 | 后端端口（默认 `8001`） |
| `FRONTEND_PORT` | 否 | 前端端口（默认 `3782`） |
| `POCKETBASE_PORT` | 否 | 可选 PocketBase 侧车在 Docker 中的端口映射（默认 `8090`） |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | 否 | 云端部署时对外可访问的后端 URL |
| `NEXT_PUBLIC_API_BASE` | 否 | Next.js 客户端直连后端的 URL 覆盖 |
| `CORS_ORIGIN` | 否 | 追加到 FastAPI CORS 允许列表的单个额外 Origin |
| `CORS_ORIGINS` | 否 | 认证远程部署可用的逗号/换行分隔额外 Origins |
| `DISABLE_SSL_VERIFY` | 否 | 关闭出站 TLS 校验（默认 `false`） |
| `AUTH_ENABLED` | 否 | 为 `true` 时要求登录（默认 `false`） |
| `NEXT_PUBLIC_AUTH_ENABLED` | 否 | 前端可选覆盖；留空则从 `AUTH_ENABLED` 推导 |
| `AUTH_SECRET` | 否 | JWT 签名密钥；留空则在 `multi-user/_system/auth/auth_secret` 生成 |
| `AUTH_TOKEN_EXPIRE_HOURS` | 否 | 会话时长（小时，默认 `24`） |
| `AUTH_COOKIE_SECURE` | 否 | HTTPS 服务时将认证 Cookie 标为 `Secure`（默认 `false`） |
| `AUTH_USERNAME` | 否 | 单用户模式：管理员用户名 |
| `AUTH_PASSWORD_HASH` | 否 | 单用户模式：管理员密码的 bcrypt 哈希 |
| `POCKETBASE_URL` | 否 | 设置后即启用 PocketBase 侧车（仅适合单用户，见上文警告） |
| `POCKETBASE_ADMIN_EMAIL` / `POCKETBASE_ADMIN_PASSWORD` | 否 | Python 后端管理 PocketBase 集合的管理员凭据 |
| `POCKETBASE_EXTERNAL_URL` | 否 | PocketBase 对外 URL，用于 OAuth 重定向（仅远程部署） |
| `CHAT_ATTACHMENT_DIR` | 否 | 聊天附件存储根目录覆盖 |

</details>

### 方案 D — 仅 CLI

若只需要 CLI、不需要 Web 前端：

```bash
# 含 RAG、文档解析及所有内置 LLM 提供商 SDK。
# 与方案 B 相同，但不包含 FastAPI/uvicorn。
python -m pip install -e ".[cli]"
```

仍需配置 LLM 提供商，最快方式：

```bash
cp .env.example .env   # 然后编辑 .env 填入 API 密钥
```

配置完成后即可使用：

```bash
deeptutor chat                                   # 交互式 REPL
deeptutor run chat "Explain Fourier transform"   # 单次运行能力
deeptutor run deep_solve "Solve x^2 = 4"         # 多智能体解题
deeptutor kb create my-kb --doc textbook.pdf     # 构建知识库
```

完整能力与命令说明见 [DeepTutor CLI](#deeptutor-cli)。

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

六种模式共处同一工作区，由**统一上下文管理**串联：历史、知识库与引用跨模式保留，可按需在同类话题下切换。

| 模式 | 作用 |
|:---|:---|
| **Chat** | 工具增强对话：RAG、搜索、代码执行、深度推理、头脑风暴、论文检索等自由组合 |
| **Deep Solve** | 多智能体解题：规划、探究、求解与验证，步骤带来源引用 |
| **Quiz Generation** | 基于知识库的测验生成与校验 |
| **Deep Research** | 拆分子课题，并行检索 RAG/网络/论文，输出带引用报告 |
| **Math Animator** | Manim 驱动的数学动画与分镜 |
| **Visualize** | 从自然语言生成 SVG、Chart.js、Mermaid 或独立 HTML |

工具与**工作流解耦**：每种模式可自行开关工具数量，编排负责推理，工具由你组合。

> 从一道简单的聊天问题起步，题目变难时再升级到 Deep Solve，可视化某个概念，生成测验题自测，接着发起深度研究继续深挖——所有这些都在同一条连续对话线程里完成。

### ✍️ Co-Writer — 多文档 AI 写作

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

将 Chat 的智能带入写作面：多文档持久化，全功能 Markdown 编辑，AI 为协作者。**改写 / 扩展 / 缩写**可选知识库或网络上下文；支持撤销重做，内容可写入笔记本。

### 📖 Book Engine — 交互式「活书」

<div align="center">
<img src="../../assets/figs/dt-book-0.png" alt="书库" width="270"><img src="../../assets/figs/dt-book-1.png" alt="阅读" width="270"><img src="../../assets/figs/dt-book-2.png" alt="动画" width="270">
</div>

给定主题与知识库，生成可读、可测、可上下文讨论的结构化书籍。多智能体负责大纲、检索、章节树、页面规划与块编译；你可审阅大纲、调整章节、在任意页旁聊天。

页面由 **13** 种块组成：正文、标注、测验、闪卡、代码、图示、深度阅读、动画、交互演示、时间线、概念图、分区、用户笔记等，各有交互组件；实时进度时间线展示编译过程。

### 📚 知识管理 — 学习基础设施

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="知识管理" width="800">
</div>

「知识」模块用于构建并管理文档集合、笔记与教学人格——它们驱动 DeepTutor 中的其余一切功能。

- **知识库** — PDF、Office（DOCX/XLSX/PPTX）、Markdown 及多种文本/代码文件，支持增量入库。
- **笔记本** — 跨会话整理记录，来自聊天、Co-Writer、书籍或深度研究。
- **题库** — 浏览生成过的测验，书签与聊天中 @ 提及以复盘。
- **Skills** — 通过 `SKILL.md` 自定义教学人格；激活时注入系统提示，塑造苏格拉底式同伴、研究助手等角色。

知识库不是静态仓库，而是主动参与每次对话与研究路径。

### 🧠 记忆 — 与你同步成长

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="记忆" width="800">
</div>

DeepTutor 通过两个互补维度，对你形成持久且不断更新的理解：

- **Summary** — 学习进度摘要：学过什么、探索过哪些主题、理解如何演进。
- **Profile** — 学习者画像：偏好、水平、目标与沟通风格，随交互自动精炼。

记忆在所有功能与 TutorBot 间共享。使用 DeepTutor 越多，体验就越个性化、越高效。

---

<a id="tutorbot"></a>
### 🦞 TutorBot — 持久、自主的 AI 导师

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="TutorBot 架构" width="800">
</div>

TutorBot 不是聊天机器人——而是建立在 [nanobot](https://github.com/HKUDS/nanobot) 之上的**持久、可多实例**智能体。每个 TutorBot 在独立的工作区、记忆与人格下运行各自的智能体循环。你可以同时启用苏格拉底式数学导师、耐心的写作教练与严谨的研究顾问——并行运行，并随你一起成长。

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Soul 模板** — 通过可编辑的 Soul 文件定义导师的人格、语气与教学理念。可选用内置原型（苏格拉底式、鼓励型、严谨型），或完全自拟——Soul 塑造每一次回复。
- **独立工作区** — 每 bot 独立目录（记忆、会话、技能、配置），仍可访问共享知识层。
- **主动 Heartbeat** — 周期性复习提醒与定时任务。
- **完整工具** — RAG、代码、搜索、论文、深度推理、头脑风暴等。
- **技能学习** — 向工作区添加 skill 文件即可扩展能力。
- **多渠道** — Telegram、Discord、Slack、飞书、企业微信、钉钉、Matrix、QQ、WhatsApp、邮件等。
- **团队与子智能体** — 单 bot 内多智能体协作与长任务编排。

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list                  # 查看当前所有导师实例
```

---

<a id="deeptutor-cli"></a>
### ⌨️ DeepTutor CLI — 智能体原生界面

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI 架构" width="800">
</div>

DeepTutor 完全以 CLI 为一等公民：每一种能力、知识库、会话、记忆与 TutorBot 都能用一条命令触达，无需浏览器。CLI 既为人类提供 Rich 终端渲染，也为 AI 智能体与流水线提供结构化 JSON 输出。

将项目根目录的 [`SKILL.md`](../../SKILL.md) 交给任意支持工具调用的智能体（[nanobot](https://github.com/HKUDS/nanobot)，或任何具备工具能力的 LLM），即可自主配置并操作 DeepTutor。

**单次执行** — 在终端直接运行任意能力：

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
deeptutor run visualize "Draw the architecture of a transformer"
```

**交互式 REPL** — 持久会话，运行中切换模式：

```bash
deeptutor chat --capability deep_solve --kb my-kb
# 在 REPL 内：/cap、/tool、/kb、/history、/notebook、/config 可随时切换
```

**知识库生命周期** — 仅在终端构建、查询并管理可用于 RAG 的集合：

```bash
deeptutor kb create my-kb --doc textbook.pdf       # 从文档创建
deeptutor kb add my-kb --docs-dir ./papers/         # 添加整目录文献
deeptutor kb search my-kb "gradient descent"        # 直接检索
deeptutor kb set-default my-kb                      # 设为默认知识库（作用于后续命令）
```

**双输出模式** — Rich 供人阅读，JSON 供流水线解析：

```bash
deeptutor run chat "Summarize chapter 3" -f rich    # 彩色、格式化输出
deeptutor run chat "Summarize chapter 3" -f json    # 按行分隔的 JSON 事件流
```

**会话连续性** — 从上次中断处继续：

```bash
deeptutor session list                              # 列出会话
deeptutor session open <id>                         # 在 REPL 中恢复
```

<details>
<summary><b>CLI 命令参考（完整）</b></summary>

**顶层**

| 命令 | 说明 |
|:---|:---|
| `deeptutor run <capability> <message>` | 单轮运行任意能力（`chat`、`deep_solve`、`deep_question`、`deep_research`、`math_animator`、`visualize`） |
| `deeptutor chat` | 交互式 REPL，可选 `--capability`、`--tool`、`--kb`、`--language` |
| `deeptutor serve` | 启动 DeepTutor API 服务 |

**`deeptutor bot`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor bot list` | 列出所有 TutorBot 实例 |
| `deeptutor bot create <id>` | 创建并启动新 bot（`--name`、`--persona`、`--model`） |
| `deeptutor bot start <id>` | 启动 bot |
| `deeptutor bot stop <id>` | 停止 bot |

**`deeptutor kb`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor kb list` | 列出所有知识库 |
| `deeptutor kb info <name>` | 查看知识库详情 |
| `deeptutor kb create <name>` | 从文档创建（`--doc`、`--docs-dir`） |
| `deeptutor kb add <name>` | 增量添加文档 |
| `deeptutor kb search <name> <query>` | 在知识库中检索 |
| `deeptutor kb set-default <name>` | 设为默认知识库 |
| `deeptutor kb delete <name>` | 删除知识库（`--force`） |

**`deeptutor memory`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor memory show [file]` | 查看记忆（`summary`、`profile` 或 `all`） |
| `deeptutor memory clear [file]` | 清空记忆（`--force`） |

**`deeptutor session`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor session list` | 列出会话（`--limit`） |
| `deeptutor session show <id>` | 查看会话消息 |
| `deeptutor session open <id>` | 在 REPL 中恢复会话 |
| `deeptutor session rename <id>` | 重命名会话（`--title`） |
| `deeptutor session delete <id>` | 删除会话 |

**`deeptutor notebook`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor notebook list` | 列出笔记本 |
| `deeptutor notebook create <name>` | 创建笔记本（`--description`） |
| `deeptutor notebook show <id>` | 查看笔记本记录 |
| `deeptutor notebook add-md <id> <path>` | 将 Markdown 导入为记录 |
| `deeptutor notebook replace-md <id> <rec> <path>` | 替换某条 Markdown 记录 |
| `deeptutor notebook remove-record <id> <rec>` | 删除记录 |

**`deeptutor book`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor book list` | 列出工作区中的所有书籍 |
| `deeptutor book health <book_id>` | 检查知识库漂移与书籍健康度 |
| `deeptutor book refresh-fingerprints <book_id>` | 刷新知识库指纹并清理过期页面 |

**`deeptutor config` / `plugin` / `provider`**

| 命令 | 说明 |
|:---|:---|
| `deeptutor config show` | 打印当前配置摘要 |
| `deeptutor plugin list` | 列出已注册的工具与能力 |
| `deeptutor plugin info <name>` | 查看工具或能力详情 |
| `deeptutor provider login <provider>` | 提供商认证（`openai-codex` 为 OAuth 登录；`github-copilot` 校验已有 Copilot 登录会话） |

</details>

---

<a id="multi-user"></a>
### 👥 多用户 — 共享部署与每用户工作区

<div align="center">
<img src="../../assets/figs/dt-multi-user.png" alt="多用户" width="800">
</div>

开启认证后，DeepTutor 成为多租户部署：**每用户隔离工作区**，**资源由管理员编排**。首位注册用户为管理员，代为配置模型、API Key 与知识库；其余账号由管理员邀请创建，各自拥有范围的聊天/记忆/笔记本/知识库，仅可见被授予的 LLM、KB 与 Skills。

**快速开始（5 步）：**

```bash
# 1. 在项目根目录 .env 中启用认证。
echo 'AUTH_ENABLED=true' >> .env
# 可选 — JWT 签名密钥；留空则首次启动时可自动生成。
echo 'AUTH_SECRET=<粘贴 64 位以上随机字符>' >> .env

# 2. 重启 Web 栈 — start_web.py 会将 AUTH_ENABLED 同步到前端。
python scripts/start_web.py

# 3. 打开 http://localhost:3782/register 创建首个账号。
#    首次注册是唯一公开的注册；该用户成为管理员，
#    此后 /register 端点会自动关闭。

# 4. 以管理员身份进入 /admin/users →「添加用户」为同伴开通账号。

# 5. 对每个用户点击滑块图标 → 分配 LLM 配置、知识库与 Skills → 保存。用户即可登录使用。
```

**管理员可见：**

- **`/settings` 完整设置页** — LLM/嵌入/搜索、Key、模型目录与运行时「应用」。
- **`/admin/users`** — 创建、升降级、删除账号。首个管理员出现后公共 `/register` 关闭；更多用户走 `POST /api/v1/auth/users`（仅管理员）。
- **授予编辑器** — 为非管理员指定可用模型配置、知识库与 Skills；授予侧仅**逻辑 ID**，API Key 不跨越边界。
- **审计** — 授予变更与资源访问写入 `multi-user/_system/audit/usage.jsonl`。

**普通用户获得：**

- **`multi-user/<uid>/` 隔离空间** — 自有 `chat_history.db`、记忆、笔记本与个人知识库；默认不与他人共享。
- **管理员分配的资源只读访问**，与自有资源并列展示，带「由管理员分配」标记。
- **脱敏设置页** — 主题、语言、已授予模型摘要；非管理员请求不返回 Key、基 URL 与提供商端点。
- **限定 LLM** — 对话使用管理员授予的模型；未授予则在入口处拒绝（不回退到管理员 Key）。

**目录结构：**

```
multi-user/
├── _system/
│   ├── auth/users.json          # 哈希凭据与角色
│   ├── auth/auth_secret         # JWT 签名密钥（自动生成）
│   ├── grants/<uid>.json        # 每用户资源授予（管理员维护）
│   └── audit/usage.jsonl        # 审计轨迹
└── <uid>/
    ├── user/
    │   ├── chat_history.db
    │   ├── settings/interface.json
    │   └── workspace/{chat,co-writer,book,...}
    ├── memory/{SUMMARY.md,PROFILE.md}
    └── knowledge_bases/...
```

**配置参考：**

| Variable | Required | Description |
|:---|:---|:---|
| `AUTH_ENABLED` | 是 | `true` 启用多用户；默认 `false`（单用户，全局管理员路径）。 |
| `AUTH_SECRET` | 建议 | JWT 密钥；空则写入 `multi-user/_system/auth/auth_secret`。 |
| `AUTH_TOKEN_EXPIRE_HOURS` | 否 | 默认 24 小时。 |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | 否 | 单用户回退（遗留）；多用户时请留空。 |
| `NEXT_PUBLIC_AUTH_ENABLED` | 自动 | `start_web.py` 从 `AUTH_ENABLED` 镜像，供 Next 中间件跳转 `/login`。 |

> ⚠️ **PocketBase（`POCKETBASE_URL`）仍为单用户场景**，原因同上：无 `role`、查询未按 `user_id`。**多用户请勿启用 PocketBase**，使用默认 JSON/SQLite。

> ⚠️ **建议单进程**。首位管理员晋升由进程内 `threading.Lock` 保护。多 Worker 环境请离线创建首位管理员（先 `AUTH_ENABLED=false` 完成引导再开启），或使用外部用户存储。

<a id="roadmap"></a>
## 🗺️ 路线图

| 状态 | 里程碑 |
|:---:|:---|
| 🎯 | **认证与登录** — 公网可选登录与多用户 |
| 🎯 | **主题与外观** — 多样主题与可定制界面 |
| 🎯 | **交互改进** — 图标与细节优化 |
| 🔜 | **更强记忆** — 更好记忆管理 |
| 🔜 | **LightRAG** — 接入 [LightRAG](https://github.com/HKUDS/LightRAG) |
| 🔜 | **文档站** — 指南、API、教程 |

> 若 DeepTutor 对你有用，欢迎 [Star](https://github.com/HKUDS/DeepTutor/stargazers)。

---

<a id="community"></a>
## 🌐 社区与生态

DeepTutor 建立在众多优秀开源项目之上：

| 项目 | 作用 |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | TutorBot 轻量引擎 |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG 与索引骨干 |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | 数学动画生成 |

**HKUDS 生态：**

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| 简洁高速 RAG | 零代码智能体 | 自动化研究 | 超轻量智能体 |

## 🤝 贡献

<div align="center">

希望 DeepTutor 能成为送给社区的礼物。🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

开发环境搭建、代码规范与 Pull Request 流程请参阅 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

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

<p align="center">
 <a href="https://www.star-history.com/hkuds/deeptutor">
  <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
   <img alt="Star History Rank" src="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
  </picture>
 </a>
</p>

<div align="center">

**[Data Intelligence Lab @ HKU](https://github.com/HKUDS)**

[⭐ Star](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 问题反馈](https://github.com/HKUDS/DeepTutor/issues) · [💬 讨论](https://github.com/HKUDS/DeepTutor/discussions)

---

采用 [Apache License 2.0](../../LICENSE)。

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
