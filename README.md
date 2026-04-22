<div align="center">

<img src="assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: Agent-Native Personalized Tutoring

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-Coming_Soon-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](#)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](./Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Features](#-key-features) · [Get Started](#-get-started) · [Explore](#-explore-deeptutor) · [TutorBot](#-tutorbot--persistent-autonomous-ai-tutors) · [CLI](#%EF%B8%8F-deeptutor-cli--agent-native-interface) · [Roadmap](#%EF%B8%8F-roadmap) · [Community](#-community--ecosystem)

[🇨🇳 中文](assets/README/README_CN.md) · [🇯🇵 日本語](assets/README/README_JA.md) · [🇪🇸 Español](assets/README/README_ES.md) · [🇫🇷 Français](assets/README/README_FR.md) · [🇸🇦 العربية](assets/README/README_AR.md) · [🇷🇺 Русский](assets/README/README_RU.md) · [🇮🇳 हिन्दी](assets/README/README_HI.md) · [🇵🇹 Português](assets/README/README_PT.md) · [🇹🇭 ภาษาไทย](assets/README/README_TH.md)

</div>

---

### 📦 Releases

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — User-authored Skills system (CRUD + chat integration), chat input performance overhaul with state colocation, `response_format` auto-fallback for incompatible providers, LAN remote access fix, sidebar version badge, Deep Solve image attachments, TutorBot WebSocket auto-start, Book Library UI, and visualization fullscreen mode.

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — Per-stage chat token limits in `agents.yaml` (8000-token responses), Regenerate last response across CLI / WebSocket / Web UI, RAG `None`-embedding crash fix, Gemma `json_object` compatibility, and dark code-block readability.

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Book Engine multi-agent "living book" compiler with 14 block types, multi-document Co-Writer workspace, interactive HTML visualizations, Question Bank @-mention in chat, prompt externalization phase 2, and sidebar overhaul.

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — Schema-driven Channels tab with secret masking, RAG collapsed to single pipeline, RAG/KB consistency hardening, externalized chat prompts, and Thai README.

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — Universal "Answer now" across all capabilities, Co-Writer scroll sync, Save-to-Notebook message selection, unified settings panel, streaming Stop button, and TutorBot atomic config writes.

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — LaTeX block math parsing overhaul, LLM diagnostic probe via agents.yaml, extra headers forwarding fix, SaveToNotebook UUID fix, and Docker + local LLM guidance.

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — URL-based bookmarkable sessions, Snow theme, WebSocket heartbeat & auto-reconnect, ChatComposer performance fix, embedding provider registry overhaul, and Serper search provider.

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — Question Notebook with bookmarks & categories, Mermaid in Visualize, embedding mismatch detection, Qwen/vLLM compatibility, LM Studio & llama.cpp support, and Glass theme.

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — Search consolidation with SearXNG fallback, provider switch fix, and frontend resource leak fixes.

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — Visualize capability (Chart.js/SVG), quiz duplicate prevention, and o4-mini model support.

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — Embedding progress tracking with rate-limit retry, cross-platform dependency fixes, and MIME validation fix.

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — Native OpenAI/Anthropic SDK (drop litellm), Windows Math Animator support, robust JSON parsing, and full Chinese i18n.

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — Hot settings reload, MinerU nested output, WebSocket fix, and Python 3.11+ minimum.

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — Agent-native architecture rewrite (~200k lines): Tools + Capabilities plugin model, CLI & SDK, TutorBot, Co-Writer, Guided Learning, and persistent memory.

<details>
<summary><b>Past releases</b></summary>

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Session persistence, incremental document upload, flexible RAG pipeline import, and full Chinese localization.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling support for RAG-Anything, logging system optimization, and bug fixes.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Unified service configuration, RAG pipeline selection per knowledge base, question generation overhaul, and sidebar customization.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — Multi-provider LLM & embedding support, new home page, RAG module decoupling, and environment variable refactor.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — Unified PromptManager architecture, GitHub Actions CI/CD, and pre-built Docker images on GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker deployment, Next.js 16 & React 19 upgrade, WebSocket security hardening, and critical vulnerability fixes.

</details>

### 📰 News

> **[2026.4.19]** 🎉 We've reached 20k stars after 111 days! Thank you for the incredible support — we're committed to continuous iteration toward truly personalized, intelligent tutoring for everyone.

> **[2026.4.4]** Long time no see! ✨ DeepTutor v1.0.0 is finally here — an agent-native evolution featuring a ground-up architecture rewrite, TutorBot, and flexible mode switching under the Apache-2.0 license. A new chapter begins, and our story continues! 

> **[2026.2.6]** 🚀 We've reached 10k stars in just 39 days! A huge thank you to our incredible community for the support! 

> **[2026.1.1]** Happy New Year! Join our [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78), or [Discussions](https://github.com/HKUDS/DeepTutor/discussions) — let's shape the future of DeepTutor together!

> **[2025.12.29]** DeepTutor is officially released!


## ✨ Key Features

- **Unified Chat Workspace** — Six modes, one thread. Chat, Deep Solve, Quiz Generation, Deep Research, Math Animator, and Visualize share the same context — start a conversation, escalate to multi-agent problem solving, generate quizzes, visualize concepts, then deep-dive into research, all without losing a single message.
- **AI Co-Writer** — A multi-document Markdown workspace where AI is a first-class collaborator. Select text, rewrite, expand, or summarize — drawing from your knowledge base and the web. Every piece feeds back into your learning ecosystem.
- **Book Engine** — Turn your materials into structured, interactive "living books". A multi-agent pipeline designs outlines, retrieves relevant sources, and compiles rich pages with 14 block types — quizzes, flash cards, timelines, concept graphs, interactive demos, and more.
- **Knowledge Hub** — Upload PDFs, Markdown, and text files to build RAG-ready knowledge bases. Organize insights in color-coded notebooks, revisit quiz questions in the Question Bank, and create custom Skills that shape how DeepTutor teaches you. Your documents don't just sit there — they actively power every conversation.
- **Persistent Memory** — DeepTutor builds a living profile of you: what you've studied, how you learn, and where you're heading. Shared across all features and TutorBots, it gets sharper with every interaction.
- **Personal TutorBots** — Not chatbots — autonomous tutors. Each TutorBot lives in its own workspace with its own memory, personality, and skill set. They set reminders, learn new abilities, and evolve as you grow. Powered by [nanobot](https://github.com/HKUDS/nanobot).
- **Agent-Native CLI** — Every capability, knowledge base, session, and TutorBot is one command away. Rich terminal output for humans, structured JSON for AI agents and pipelines. Hand DeepTutor a [`SKILL.md`](SKILL.md) and your agents can operate it autonomously.

---

## 🚀 Get Started

### Prerequisites

Before you begin, make sure the following are installed on your system:

| Requirement | Version | Check | Notes |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | Any | `git --version` | For cloning the repository |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | Backend runtime |
| [Node.js](https://nodejs.org/) | 18+ | `node --version` | Frontend build (not needed for CLI-only or Docker) |
| [npm](https://www.npmjs.com/) | 9+ | `npm --version` | Bundled with Node.js |

You'll also need an **API key** from at least one LLM provider (e.g. [OpenAI](https://platform.openai.com/api-keys), [DeepSeek](https://platform.deepseek.com/), [Anthropic](https://console.anthropic.com/)). The Setup Tour will walk you through entering it.

### Option A — Setup Tour (Recommended)

A **single interactive script** that walks you through everything: dependency installation, environment configuration, live connection testing, and launch. No manual `.env` editing needed.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Create a Python virtual environment (pick one):
conda create -n deeptutor python=3.11 && conda activate deeptutor   # if you use Anaconda/Miniconda
python -m venv .venv && source .venv/bin/activate                    # otherwise (macOS/Linux)
python -m venv .venv && .venv\Scripts\activate                       # otherwise (Windows)

# Launch the guided tour
python scripts/start_tour.py
```

The tour asks how you'd like to use DeepTutor:

- **Web mode** (recommended) — Installs all dependencies (pip + npm), spins up a temporary server, and opens the **Settings** page in your browser. A four-step guided tour walks you through LLM, Embedding, and Search provider setup with live connection testing. Once complete, DeepTutor restarts automatically with your configuration.
- **CLI mode** — A fully interactive terminal flow: choose a dependency profile, install dependencies, configure providers, verify connections, and apply — all without leaving the shell.

Either way, you end up with a running DeepTutor at [http://localhost:3782](http://localhost:3782).

> **Daily launch** — The tour is only needed once. From now on, start DeepTutor with:
>
> ```bash
> python scripts/start_web.py
> ```
>
> This boots both the backend and frontend in one command and opens the browser automatically. Re-run `start_tour.py` only if you need to reconfigure providers or reinstall dependencies.

### Option B — Manual Local Install

If you prefer full control, install and configure everything yourself.

**1. Install dependencies**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Create & activate a Python virtual environment (same as Option A)
conda create -n deeptutor python=3.11 && conda activate deeptutor

# Install DeepTutor with backend + web server dependencies
pip install -e ".[server]"

# Install frontend dependencies (requires Node.js 18+)
cd web && npm install && cd ..
```

**2. Configure environment**

```bash
cp .env.example .env
```

Edit `.env` and fill in at least the required fields:

```dotenv
# LLM (Required)
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# Embedding (Required for Knowledge Base)
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

<details>
<summary><b>Supported LLM Providers</b></summary>

| Provider | Binding | Default Base URL |
|:--|:--|:--|
| AiHubMix | `aihubmix` | `https://aihubmix.com/v1` |
| Anthropic | `anthropic` | `https://api.anthropic.com/v1` |
| Azure OpenAI | `azure_openai` | — |
| BytePlus | `byteplus` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| BytePlus Coding Plan | `byteplus_coding_plan` | `https://ark.ap-southeast.bytepluses.com/api/coding/v3` |
| Custom (OpenAI-compat) | `custom` | — |
| DashScope (Qwen) | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| DeepSeek | `deepseek` | `https://api.deepseek.com` |
| Gemini | `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| GitHub Copilot | `github_copilot` | `https://api.githubcopilot.com` |
| Groq | `groq` | `https://api.groq.com/openai/v1` |
| llama.cpp | `llama_cpp` | `http://localhost:8080/v1` |
| LM Studio | `lm_studio` | `http://localhost:1234/v1` |
| MiniMax | `minimax` | `https://api.minimax.io/v1` |
| Mistral | `mistral` | `https://api.mistral.ai/v1` |
| Moonshot (Kimi) | `moonshot` | `https://api.moonshot.ai/v1` |
| Ollama | `ollama` | `http://localhost:11434/v1` |
| OpenAI | `openai` | `https://api.openai.com/v1` |
| OpenAI Codex | `openai_codex` | `https://chatgpt.com/backend-api` |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` |
| OpenVINO Model Server | `ovms` | `http://localhost:8000/v3` |
| Qianfan (Ernie) | `qianfan` | `https://qianfan.baidubce.com/v2` |
| SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1` |
| Step Fun | `stepfun` | `https://api.stepfun.com/v1` |
| vLLM | `vllm` | `http://localhost:8000/v1` |
| VolcEngine | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| VolcEngine Coding Plan | `volcengine_coding_plan` | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| Xiaomi MIMO | `xiaomi_mimo` | `https://api.xiaomimimo.com/v1` |
| Zhipu AI (GLM) | `zhipu` | `https://open.bigmodel.cn/api/paas/v4` |

</details>

<details>
<summary><b>Supported Embedding Providers</b></summary>

| Provider | Binding | Model Example | Default Dim |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | deployment name | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | Any embedding model | — |
| Any OpenAI-compatible | `custom` | — | — |

OpenAI-compatible providers (DashScope, SiliconFlow, etc.) work via the `custom` or `openai` binding.

</details>

<details>
<summary><b>Supported Web Search Providers</b></summary>

| Provider | Env Key | Notes |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | Recommended, free tier available |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | Google Search results via Serper |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | Self-hosted, no API key needed |
| DuckDuckGo | — | No API key needed |
| Perplexity | `PERPLEXITY_API_KEY` | Requires API key |

</details>

**3. Start services**

The quickest way to launch everything:

```bash
python scripts/start_web.py
```

This starts both the backend and frontend and opens the browser automatically.

Alternatively, start each service manually in separate terminals:

```bash
# Backend (FastAPI)
python -m deeptutor.api.run_server

# Frontend (Next.js) — in a separate terminal
cd web && npm run dev -- -p 3782
```

| Service | Default Port |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

Open [http://localhost:3782](http://localhost:3782) and you're ready to go.

### Option C — Docker Deployment

Docker wraps the backend and frontend into a single container — no local Python or Node.js required. You only need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose on Linux).

**1. Configure environment variables** (required for both options below)

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

Edit `.env` and fill in at least the required fields (same as [Option B](#option-b--manual-local-install) above).

**2a. Pull official image (recommended)**

Official images are published to [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor) on every release, built for `linux/amd64` and `linux/arm64`.

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

To pin a specific version, edit the image tag in `docker-compose.ghcr.yml`:

```yaml
image: ghcr.io/hkuds/deeptutor:1.0.0  # or :latest
```

**2b. Build from source**

```bash
docker compose up -d
```

This builds the image locally from `Dockerfile` and starts the container.

**3. Verify & manage**

Open [http://localhost:3782](http://localhost:3782) once the container is healthy.

```bash
docker compose logs -f   # tail logs
docker compose down       # stop and remove container
```

<details>
<summary><b>Cloud / remote server deployment</b></summary>

When deploying to a remote server, the browser needs to know the public URL of the backend API. Add one more variable to your `.env`:

```dotenv
# Set to the public URL where the backend is reachable
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

The frontend startup script applies this value at runtime — no rebuild needed.

</details>

<details>
<summary><b>Development mode (hot-reload)</b></summary>

Layer the dev override to mount source code and enable hot-reload for both services:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Changes to `deeptutor/`, `deeptutor_cli/`, `scripts/`, and `web/` are reflected immediately.

</details>

<details>
<summary><b>Custom ports</b></summary>

Override the default ports in `.env`:

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

Then restart:

```bash
docker compose up -d     # or docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>Data persistence</b></summary>

User data and knowledge bases are persisted via Docker volumes mapped to local directories:

| Container path | Host path | Content |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | Settings, memory, workspace, sessions, logs |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | Uploaded documents & vector indices |

These directories survive `docker compose down` and are reused on the next `docker compose up`.

</details>

<details>
<summary><b>Environment variables reference</b></summary>

| Variable | Required | Description |
|:---|:---:|:---|
| `LLM_BINDING` | **Yes** | LLM provider (`openai`, `anthropic`, etc.) |
| `LLM_MODEL` | **Yes** | Model name (e.g. `gpt-4o`) |
| `LLM_API_KEY` | **Yes** | Your LLM API key |
| `LLM_HOST` | **Yes** | API endpoint URL |
| `EMBEDDING_BINDING` | **Yes** | Embedding provider |
| `EMBEDDING_MODEL` | **Yes** | Embedding model name |
| `EMBEDDING_API_KEY` | **Yes** | Embedding API key |
| `EMBEDDING_HOST` | **Yes** | Embedding endpoint |
| `EMBEDDING_DIMENSION` | **Yes** | Vector dimension |
| `SEARCH_PROVIDER` | No | Search provider (`tavily`, `jina`, `serper`, `perplexity`, etc.) |
| `SEARCH_API_KEY` | No | Search API key |
| `BACKEND_PORT` | No | Backend port (default `8001`) |
| `FRONTEND_PORT` | No | Frontend port (default `3782`) |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | No | Public backend URL for cloud deployment |
| `DISABLE_SSL_VERIFY` | No | Disable SSL verification (default `false`) |

</details>

### Option D — CLI Only

If you just want the CLI without the web frontend:

```bash
pip install -e ".[cli]"
```

You still need to configure your LLM provider. The quickest way:

```bash
cp .env.example .env   # then edit .env to fill in your API keys
```

Once configured, you're ready to go:

```bash
deeptutor chat                                   # Interactive REPL
deeptutor run chat "Explain Fourier transform"   # One-shot capability
deeptutor run deep_solve "Solve x^2 = 4"         # Multi-agent problem solving
deeptutor kb create my-kb --doc textbook.pdf     # Build a knowledge base
```

> See [DeepTutor CLI](#%EF%B8%8F-deeptutor-cli--agent-native-interface) for the full feature guide and command reference.

---

## 📖 Explore DeepTutor

<div align="center">
<img src="assets/figs/deeptutor-architecture.png" alt="DeepTutor Architecture" width="800">
</div>

### 💬 Chat — Unified Intelligent Workspace

<div align="center">
<img src="assets/figs/dt-chat.png" alt="Chat Workspace" width="800">
</div>

Six distinct modes coexist in a single workspace, bound by a **unified context management system**. Conversation history, knowledge bases, and references persist across modes — switch between them freely within the same topic, whenever the moment calls for it.

| Mode | What It Does |
|:---|:---|
| **Chat** | Fluid, tool-augmented conversation. Choose from RAG retrieval, web search, code execution, deep reasoning, brainstorming, and paper search — mix and match as needed. |
| **Deep Solve** | Multi-agent problem solving: plan, investigate, solve, and verify — with precise source citations at every step. |
| **Quiz Generation** | Generate assessments grounded in your knowledge base, with built-in validation. |
| **Deep Research** | Decompose a topic into subtopics, dispatch parallel research agents across RAG, web, and academic papers, and produce a fully cited report. |
| **Math Animator** | Turn mathematical concepts into visual animations and storyboards powered by Manim. |
| **Visualize** | Generate interactive SVG diagrams, Chart.js charts, Mermaid graphs, or self-contained HTML pages from natural language descriptions. |

Tools are **decoupled from workflows** — in every mode, you decide which tools to enable, how many to use, or whether to use any at all. The workflow orchestrates the reasoning; the tools are yours to compose.

> Start with a quick chat question, escalate to Deep Solve when it gets hard, visualize a concept, generate quiz questions to test yourself, then launch a Deep Research to go deeper — all in one continuous thread.

### ✍️ Co-Writer — Multi-Document AI Writing Workspace

<div align="center">
<img src="assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

Co-Writer brings the intelligence of Chat directly into a writing surface. Create and manage multiple documents, each persisted in its own workspace — not a single throwaway scratchpad, but a full-featured multi-document Markdown editor where AI is a first-class collaborator.

Select any text and choose **Rewrite**, **Expand**, or **Shorten** — optionally drawing context from your knowledge base or the web. The editing flow is non-destructive with full undo/redo, and every piece you write can be saved straight to your notebooks, feeding back into your learning ecosystem.

### 📖 Book Engine — Interactive "Living Books"

<div align="center">
<img src="assets/figs/dt-book-0.png" alt="Book Library" width="270"><img src="assets/figs/dt-book-1.png" alt="Book Reader" width="270"><img src="assets/figs/dt-book-2.png" alt="Book Animation" width="270">
</div>

Give DeepTutor a topic, point it at your knowledge base, and it produces a structured, interactive book — not a static export, but a living document you can read, quiz yourself on, and discuss in context.

Behind the scenes, a multi-agent pipeline handles the heavy lifting: proposing an outline, retrieving relevant sources from your knowledge base, synthesizing a chapter tree, planning each page, and compiling every block. You stay in control — review the proposal, reorder chapters, and chat alongside any page.

Pages are assembled from 14 block types — text, callout, quiz, flash cards, code, figure, deep dive, animation, interactive demo, timeline, concept graph, section, user note, and placeholder — each rendered with its own interactive component. A real-time progress timeline lets you watch compilation unfold as the book takes shape.

### 📚 Knowledge Management — Your Learning Infrastructure

<div align="center">
<img src="assets/figs/dt-knowledge.png" alt="Knowledge Management" width="800">
</div>

Knowledge is where you build and manage the document collections, notes, and teaching personas that power everything else in DeepTutor.

- **Knowledge Bases** — Upload PDF, TXT, or Markdown files to create searchable, RAG-ready collections. Add documents incrementally as your library grows.
- **Notebooks** — Organize learning records across sessions. Save insights from Chat, Co-Writer, Book, or Deep Research into categorized, color-coded notebooks.
- **Question Bank** — Browse and revisit all generated quiz questions. Bookmark entries and @-mention them directly in chat to reason over past performance.
- **Skills** — Create custom teaching personas via `SKILL.md` files. Each skill defines a name, description, optional triggers, and a Markdown body that is injected into the chat system prompt when active — turning DeepTutor into a Socratic tutor, a peer study partner, a research assistant, or any role you design.

Your knowledge base is not passive storage — it actively participates in every conversation, every research session, and every learning path you create.

### 🧠 Memory — DeepTutor Learns As You Learn

<div align="center">
<img src="assets/figs/dt-memory.png" alt="Memory" width="800">
</div>

DeepTutor maintains a persistent, evolving understanding of you through two complementary dimensions:

- **Summary** — A running digest of your learning progress: what you've studied, which topics you've explored, and how your understanding has developed.
- **Profile** — Your learner identity: preferences, knowledge level, goals, and communication style — automatically refined through every interaction.

Memory is shared across all features and all your TutorBots. The more you use DeepTutor, the more personalized and effective it becomes.

---

### 🦞 TutorBot — Persistent, Autonomous AI Tutors

<div align="center">
<img src="assets/figs/tutorbot-architecture.png" alt="TutorBot Architecture" width="800">
</div>

TutorBot is not a chatbot — it is a **persistent, multi-instance agent** built on [nanobot](https://github.com/HKUDS/nanobot). Each TutorBot runs its own agent loop with independent workspace, memory, and personality. Create a Socratic math tutor, a patient writing coach, and a rigorous research advisor — all running simultaneously, each evolving with you.

<div align="center">
<img src="assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Soul Templates** — Define your tutor's personality, tone, and teaching philosophy through editable Soul files. Choose from built-in archetypes (Socratic, encouraging, rigorous) or craft your own — the soul shapes every response.
- **Independent Workspace** — Each bot has its own directory with separate memory, sessions, skills, and configuration — fully isolated yet able to access DeepTutor's shared knowledge layer.
- **Proactive Heartbeat** — Bots don't just respond — they initiate. The built-in Heartbeat system enables recurring study check-ins, review reminders, and scheduled tasks. Your tutor shows up even when you don't.
- **Full Tool Access** — Every bot reaches into DeepTutor's complete toolkit: RAG retrieval, code execution, web search, academic paper search, deep reasoning, and brainstorming.
- **Skill Learning** — Teach your bot new abilities by adding skill files to its workspace. As your needs evolve, so does your tutor's capability.
- **Multi-Channel Presence** — Connect bots to Telegram, Discord, Slack, Feishu, WeChat Work, DingTalk, Email, and more. Your tutor meets you wherever you are.
- **Team & Sub-Agents** — Spawn background sub-agents or orchestrate multi-agent teams within a single bot for complex, long-running tasks.

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list                  # See all your active tutors
```

---

### ⌨️ DeepTutor CLI — Agent-Native Interface

<div align="center">
<img src="assets/figs/cli-architecture.png" alt="DeepTutor CLI Architecture" width="800">
</div>

DeepTutor is fully CLI-native. Every capability, knowledge base, session, memory, and TutorBot is one command away — no browser required. The CLI serves both humans (with rich terminal rendering) and AI agents (with structured JSON output).

Hand the [`SKILL.md`](SKILL.md) at the project root to any tool-using agent ([nanobot](https://github.com/HKUDS/nanobot), or any LLM with tool access), and it can configure and operate DeepTutor autonomously.

**One-shot execution** — Run any capability directly from the terminal:

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
deeptutor run visualize "Draw the architecture of a transformer"
```

**Interactive REPL** — A persistent chat session with live mode switching:

```bash
deeptutor chat --capability deep_solve --kb my-kb
# Inside the REPL: /cap, /tool, /kb, /history, /notebook, /config to switch on the fly
```

**Knowledge base lifecycle** — Build, query, and manage RAG-ready collections entirely from the terminal:

```bash
deeptutor kb create my-kb --doc textbook.pdf       # Create from document
deeptutor kb add my-kb --docs-dir ./papers/         # Add a folder of papers
deeptutor kb search my-kb "gradient descent"        # Search directly
deeptutor kb set-default my-kb                      # Set as default for all commands
```

**Dual output mode** — Rich rendering for humans, structured JSON for pipelines:

```bash
deeptutor run chat "Summarize chapter 3" -f rich    # Colored, formatted output
deeptutor run chat "Summarize chapter 3" -f json    # Line-delimited JSON events
```

**Session continuity** — Resume any conversation right where you left off:

```bash
deeptutor session list                              # List all sessions
deeptutor session open <id>                         # Resume in REPL
```

<details>
<summary><b>Full CLI command reference</b></summary>

**Top-level**

| Command | Description |
|:---|:---|
| `deeptutor run <capability> <message>` | Run any capability in a single turn (`chat`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`, `visualize`) |
| `deeptutor chat` | Interactive REPL with optional `--capability`, `--tool`, `--kb`, `--language` |
| `deeptutor serve` | Start the DeepTutor API server |

**`deeptutor bot`**

| Command | Description |
|:---|:---|
| `deeptutor bot list` | List all TutorBot instances |
| `deeptutor bot create <id>` | Create and start a new bot (`--name`, `--persona`, `--model`) |
| `deeptutor bot start <id>` | Start a bot |
| `deeptutor bot stop <id>` | Stop a bot |

**`deeptutor kb`**

| Command | Description |
|:---|:---|
| `deeptutor kb list` | List all knowledge bases |
| `deeptutor kb info <name>` | Show knowledge base details |
| `deeptutor kb create <name>` | Create from documents (`--doc`, `--docs-dir`) |
| `deeptutor kb add <name>` | Add documents incrementally |
| `deeptutor kb search <name> <query>` | Search a knowledge base |
| `deeptutor kb set-default <name>` | Set as default KB |
| `deeptutor kb delete <name>` | Delete a knowledge base (`--force`) |

**`deeptutor memory`**

| Command | Description |
|:---|:---|
| `deeptutor memory show [file]` | View memory (`summary`, `profile`, or `all`) |
| `deeptutor memory clear [file]` | Clear memory (`--force`) |

**`deeptutor session`**

| Command | Description |
|:---|:---|
| `deeptutor session list` | List sessions (`--limit`) |
| `deeptutor session show <id>` | View session messages |
| `deeptutor session open <id>` | Resume session in REPL |
| `deeptutor session rename <id>` | Rename a session (`--title`) |
| `deeptutor session delete <id>` | Delete a session |

**`deeptutor notebook`**

| Command | Description |
|:---|:---|
| `deeptutor notebook list` | List notebooks |
| `deeptutor notebook create <name>` | Create a notebook (`--description`) |
| `deeptutor notebook show <id>` | View notebook records |
| `deeptutor notebook add-md <id> <path>` | Import markdown as record |
| `deeptutor notebook replace-md <id> <rec> <path>` | Replace a markdown record |
| `deeptutor notebook remove-record <id> <rec>` | Remove a record |

**`deeptutor book`**

| Command | Description |
|:---|:---|
| `deeptutor book list` | List all books in the workspace |
| `deeptutor book health <book_id>` | Check KB drift and book health |
| `deeptutor book refresh-fingerprints <book_id>` | Refresh KB fingerprints and clear stale pages |

**`deeptutor config` / `plugin` / `provider`**

| Command | Description |
|:---|:---|
| `deeptutor config show` | Print current configuration summary |
| `deeptutor plugin list` | List registered tools and capabilities |
| `deeptutor plugin info <name>` | Show tool or capability details |
| `deeptutor provider login <provider>` | Provider auth (`openai-codex` OAuth login; `github-copilot` validates an existing Copilot auth session) |

</details>

## 🗺️ Roadmap

| Status | Milestone |
|:---:|:---|
| 🎯 | **Authentication & Login** — Optional login page for public deployments with multi-user support |
| 🎯 | **Themes & Appearance** — Diverse theme options and customizable UI appearance |
| 🎯 | **Interaction Improvement** — optimize icon design and interaction details |
| 🔜 | **Better Memories** — integrating better memory management |
| 🔜 | **LightRAG Integration** — Integrate [LightRAG](https://github.com/HKUDS/LightRAG) as an advanced knowledge base engine |
| 🔜 | **Documentation Site** — Comprehensive docs page with guides, API reference, and tutorials |

> If you find DeepTutor useful, [give us a star](https://github.com/HKUDS/DeepTutor/stargazers) — it helps us keep going!

---

## 🌐 Community & Ecosystem

DeepTutor stands on the shoulders of outstanding open-source projects:

| Project | Role in DeepTutor |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | Ultra-lightweight agent engine powering TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG pipeline and document indexing backbone |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | AI-driven math animation generation for Math Animator |

**From the HKUDS ecosystem:**

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| Simple & Fast RAG | Zero-Code Agent Framework | Automated Research | Ultra-Lightweight AI Agent |


## 🤝 Contributing

<div align="center">

We hope DeepTutor becomes a gift for the community. 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on setting up your development environment, code standards, and pull request workflow.

## ⭐ Star History

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

[⭐ Star us](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Report a bug](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---

Licensed under the [Apache License 2.0](LICENSE).

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>


<!-- PR for #366 -->
