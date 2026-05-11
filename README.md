<div align="center">

<img src="assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: Agent-Native Personalized Tutoring

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](./Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Features](#-key-features) · [Get Started](#-get-started) · [Explore](#-explore-deeptutor) · [TutorBot](#-tutorbot--persistent-autonomous-ai-tutors) · [CLI](#%EF%B8%8F-deeptutor-cli--agent-native-interface) · [Multi-User](#-multi-user--shared-deployments-with-per-user-workspaces) · [Roadmap](#%EF%B8%8F-roadmap) · [Community](#-community--ecosystem)

[🇨🇳 中文](assets/README/README_CN.md) · [🇯🇵 日本語](assets/README/README_JA.md) · [🇪🇸 Español](assets/README/README_ES.md) · [🇫🇷 Français](assets/README/README_FR.md) · [🇸🇦 العربية](assets/README/README_AR.md) · [🇷🇺 Русский](assets/README/README_RU.md) · [🇮🇳 हिन्दी](assets/README/README_HI.md) · [🇵🇹 Português](assets/README/README_PT.md) · [🇹🇭 ภาษาไทย](assets/README/README_TH.md)  · 🇵🇱 [Polski](assets/README/README_PL.md)

</div>

---

> 🤝 **We welcome any kinds of contributing!** See our [Contributing Guide](CONTRIBUTING.md) for branching strategy, coding standards, and how to get started.

### 📦 Releases

> **[2026.5.10]** [v1.3.10](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.10) — Remote Docker CORS recovery, `DISABLE_SSL_VERIFY` across SDK providers, safer code-block citations, and optional Matrix E2EE add-on.

> **[2026.5.9]** [v1.3.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.9) — TutorBot Zulip and NVIDIA NIM support, safer thinking-model routing, `deeptutor start`, sidebar tooltips, and session-store parity.

> **[2026.5.8]** [v1.3.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.8) — Optional multi-user deployments with isolated user workspaces, admin grants, auth routes, and scoped runtime access.

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — Thinking-model/provider fixes, visible Knowledge index history, and safer Co-Writer clear/template editing.

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — Catalog-based model selection for chat and TutorBot, safer RAG re-indexing, OpenAI Responses token-limit fixes, and Skills editor validation.

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — Smoother local launch settings, safer RAG queries, cleaner local embedding auth, and Settings dark-mode polish.

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — Book page chat persistence and rebuild flows, chat-to-book references, stronger language/reasoning handling, RAG document extraction hardening.

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — NVIDIA NIM + Gemini embedding support, unified Space context for chat history/skills/memory, session snapshots, RAG re-index resilience.

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — Transparent embedding endpoint URLs, RAG re-index resilience for invalid persisted vectors, memory cleanup for thinking-model output, Deep Solve runtime fix.

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — Stability: safer RAG routing & embedding validation, Docker persistence, IME-safe input, Windows/GBK robustness.

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — Versioned KB indexes with re-index workflow, rebuilt Knowledge workspace, embedding auto-discovery with new adapters, Space hub.

<details>
<summary><b>Past releases (more than 2 weeks ago)</b></summary>

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — Persistent chat attachments with file-preview drawer, attachment-aware capability pipelines, TutorBot Markdown export.

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — Text/code/SVG attachments, one-command Setup Tour, Markdown chat export, compact KB management UI.

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — Document attachments (PDF/DOCX/XLSX/PPTX), reasoning thinking-block display, Soul template editor, Co-Writer save-to-notebook.

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — User-authored Skills system, chat input performance overhaul, TutorBot auto-start, Book Library UI, visualization fullscreen.

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — Per-stage token limits, Regenerate response across all entry points, RAG & Gemma compatibility fixes.

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Book Engine "living book" compiler, multi-document Co-Writer, interactive HTML visualizations, Question Bank @-mention.

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — Schema-driven Channels tab, RAG single-pipeline consolidation, externalized chat prompts.

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — Universal "Answer now", Co-Writer scroll sync, unified settings panel, streaming Stop button.

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — LaTeX block math overhaul, LLM diagnostic probe, Docker + local LLM guidance.

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — Bookmarkable sessions, Snow theme, WebSocket heartbeat & auto-reconnect, embedding registry overhaul.

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — Question Notebook with bookmarks & categories, Mermaid in Visualize, embedding mismatch detection, Qwen/vLLM compatibility, LM Studio & llama.cpp support, and Glass theme.

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — Search consolidation with SearXNG fallback, provider switch fix, and frontend resource leak fixes.

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — Visualize capability (Chart.js/SVG), quiz duplicate prevention, and o4-mini model support.

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — Embedding progress tracking with rate-limit retry, cross-platform dependency fixes, and MIME validation fix.

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — Native OpenAI/Anthropic SDK (drop litellm), Windows Math Animator support, robust JSON parsing, and full Chinese i18n.

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — Hot settings reload, MinerU nested output, WebSocket fix, and Python 3.11+ minimum.

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — Agent-native architecture rewrite (~200k lines): Tools + Capabilities plugin model, CLI & SDK, TutorBot, Co-Writer, Guided Learning, and persistent memory.

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Session persistence, incremental document upload, flexible RAG pipeline import, and full Chinese localization.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling support for RAG-Anything, logging system optimization, and bug fixes.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Unified service configuration, RAG pipeline selection per knowledge base, question generation overhaul, and sidebar customization.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — Multi-provider LLM & embedding support, new home page, RAG module decoupling, and environment variable refactor.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — Unified PromptManager architecture, GitHub Actions CI/CD, and pre-built Docker images on GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker deployment, Next.js 16 & React 19 upgrade, WebSocket security hardening, and critical vulnerability fixes.

</details>

### 📰 News

> **[2026.4.19]** 🎉 We've reached 20k stars after 111 days! Thank you for the incredible support — we're committed to continuous iteration toward truly personalized, intelligent tutoring for everyone.

> **[2026.4.10]** 📄 Our paper is now live on arXiv! Read the [preprint](https://arxiv.org/abs/2604.26962) to learn more about the design and ideas behind DeepTutor.

> **[2026.4.4]** Long time no see! ✨ DeepTutor v1.0.0 is finally here — an agent-native evolution featuring a ground-up architecture rewrite, TutorBot, and flexible mode switching under the Apache-2.0 license. A new chapter begins, and our story continues!

> **[2026.2.6]** 🚀 We've reached 10k stars in just 39 days! A huge thank you to our incredible community for the support!

> **[2026.1.1]** Happy New Year! Join our [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78), or [Discussions](https://github.com/HKUDS/DeepTutor/discussions) — let's shape the future of DeepTutor together!

> **[2025.12.29]** DeepTutor is officially released!


## ✨ Key Features

- **Unified Chat Workspace** — Six modes, one thread. Chat, Deep Solve, Quiz Generation, Deep Research, Math Animator, and Visualize share the same context — start a conversation, escalate to multi-agent problem solving, generate quizzes, visualize concepts, then deep-dive into research, all without losing a single message.
- **AI Co-Writer** — A multi-document Markdown workspace where AI is a first-class collaborator. Select text, rewrite, expand, or summarize — drawing from your knowledge base and the web. Every piece feeds back into your learning ecosystem.
- **Book Engine** — Turn your materials into structured, interactive "living books". A multi-agent pipeline designs outlines, retrieves relevant sources, and compiles rich pages with 13 block types — quizzes, flash cards, timelines, concept graphs, interactive demos, and more.
- **Knowledge Hub** — Upload PDFs, Markdown, and text files to build RAG-ready knowledge bases. Organize insights in color-coded notebooks, revisit quiz questions in the Question Bank, and create custom Skills that shape how DeepTutor teaches you. Your documents don't just sit there — they actively power every conversation.
- **Persistent Memory** — DeepTutor builds a living profile of you: what you've studied, how you learn, and where you're heading. Shared across all features and TutorBots, it gets sharper with every interaction.
- **Personal TutorBots** — Not chatbots — autonomous tutors. Each TutorBot lives in its own workspace with its own memory, personality, and skill set. They set reminders, learn new abilities, and evolve as you grow. Powered by [nanobot](https://github.com/HKUDS/nanobot).
- **Agent-Native CLI** — Every capability, knowledge base, session, and TutorBot is one command away. Rich terminal output for humans, structured JSON for AI agents and pipelines. Hand DeepTutor a [`SKILL.md`](SKILL.md) and your agents can operate it autonomously.
- **Optional Authentication** — Disabled by default for local use. Flip two env vars to require login when hosting publicly. Multi-user support with bcrypt-hashed passwords, JWT sessions, a self-service registration page, and a built-in admin dashboard for managing accounts and roles. Optionally back auth and storage with **PocketBase** for OAuth-ready authentication and improved multi-user concurrency — drops in as an optional sidecar with no code changes required.

---

## 🚀 Get Started

### Prerequisites

Before you begin, make sure the following are installed on your system:

| Requirement | Version | Check | Notes |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | Any | `git --version` | For cloning the repository |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | Backend runtime |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | Frontend runtime for local Web installs |
| [npm](https://www.npmjs.com/) | Bundled with Node.js | `npm --version` | Installed with Node.js |

> **Windows only (missing compiler fix):** If you do not have Visual Studio, install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and ensure the **Desktop development with C++** workload is selected.

You'll also need an **API key** from at least one LLM provider (e.g. [OpenAI](https://platform.openai.com/api-keys), [DeepSeek](https://platform.deepseek.com/), [Anthropic](https://console.anthropic.com/)). The Setup Tour will walk you through entering it.

### Option A — Setup Tour (Recommended)

A guided CLI wizard for first-time local Web setup. It checks your environment, installs Python and Node.js dependencies, writes `.env`, and lets you choose optional add-ons such as TutorBot, Matrix, and Math Animator.

**1. Clone the repository**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

**2. Create and activate a Python environment**

Pick **one** of the following based on your system.

macOS / Linux with `venv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell with `venv`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Anaconda / Miniconda:

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
```

**3. Launch the guided tour**

```bash
python scripts/start_tour.py
```

During the install step, the tour asks which dependency profile you want:

| Choice | What it installs | When to choose it |
|:---|:---|:---|
| Web app (recommended) | CLI + API server + RAG/document parsing | Most first-time users |
| Web + TutorBot | Adds TutorBot engine and common channel SDKs | If you want autonomous tutor bots or channel integrations |
| Web + TutorBot + Matrix | Adds Matrix / Element channel support without E2EE | If you need Matrix/Element rooms; install `matrix-e2e` only for encrypted rooms |
| Math Animator add-on | Installs Manim separately | Only if you need animation generation and have LaTeX/ffmpeg/system build tools ready |

Once the wizard finishes:

```bash
python scripts/start_web.py
```

> **Daily launch** — The tour is only needed once. From now on, keep that Python environment activated and run `python scripts/start_web.py` to boot both the backend and frontend. The frontend URL is printed in the terminal. Re-run `start_tour.py` only if you want to reconfigure providers, change ports, or install optional add-ons.

> **Updating a local install** — If you installed with Option A or Option B from a git clone, run `python scripts/update.py`. The updater fetches the remote for your current branch, shows the local-vs-remote commit gap, asks you to confirm the detected branch mapping, then performs a safe fast-forward pull.

### Option B — Manual Local Install

Use this path if you prefer to run each setup command yourself.

**1. Clone the repository**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

**2. Create and activate a Python environment**

Pick **one** of the following.

macOS / Linux with `venv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell with `venv`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Anaconda / Miniconda:

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
```

**3. Install dependencies**

```bash
# Backend + Web server dependencies. Includes CLI, RAG, document parsing,
# and built-in LLM provider SDKs.
python -m pip install -e ".[server]"

# Optional add-ons — install only the ones you need:
#   python -m pip install -e ".[tutorbot]"       # TutorBot engine + channel SDKs
#   python -m pip install -e ".[tutorbot,matrix]" # TutorBot + Matrix channel without E2EE/libolm
#   python -m pip install -e ".[matrix-e2e]"      # Optional encrypted Matrix rooms; requires libolm
#   python -m pip install -e ".[math-animator]"  # Manim; also requires LaTeX/ffmpeg/system build tools
#   python -m pip install -e ".[all]"            # Everything above + dev tools

# Frontend dependencies. Requires Node.js 20.9+.
cd web
npm install
cd ..
```

**4. Configure environment**

```bash
cp .env.example .env
```

Edit `.env` and fill in at least the LLM fields. Embedding fields are needed for Knowledge Base features and can be left for later if you only want to try chat first.

```dotenv
# LLM (required for chat)
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# Embedding (required for Knowledge Base / RAG)
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
# v1.3.0+: use the full endpoint URL, not just https://api.openai.com/v1
EMBEDDING_HOST=https://api.openai.com/v1/embeddings
# Leave empty unless you need to force a specific dimension.
EMBEDDING_DIMENSION=
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
| NVIDIA NIM | `nvidia_nim` | `https://integrate.api.nvidia.com/v1` |
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

**5. Start services**

The quickest way to launch everything:

```bash
python scripts/start_web.py
```

This starts both the backend and frontend. Keep the terminal open, then open the frontend URL printed in the terminal.

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
image: ghcr.io/hkuds/deeptutor:1.3.4  # or :latest
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
<summary><b>Authentication (public deployments)</b></summary>

Authentication is **disabled by default** — no login is required on localhost. For multi-tenant deployments (per-user workspaces, admin-curated models / KBs / skills, audit log), see the dedicated [Multi-User](#-multi-user--shared-deployments-with-per-user-workspaces) section below for the full setup, env-var reference, and operational caveats.

**Headless single-user (no `/register` flow):** if you can't reach the browser to bootstrap the first admin (e.g. an unattended container), pre-seed the credential via env vars:

```bash
# Generate a bcrypt hash on any host with the project checked out:
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<paste hash here>
# Optional. Auto-generated under multi-user/_system/auth/auth_secret if blank.
AUTH_SECRET=your-secret-here
```

This env-var path serves a single account and is treated as the admin. Once you run the browser registration flow, the on-disk store at `multi-user/_system/auth/users.json` takes priority and the env vars become a fallback.

</details>

<details>
<summary><b>PocketBase sidecar (optional auth + storage)</b></summary>

PocketBase is an optional lightweight backend that replaces the built-in SQLite/JSON auth and session storage. It adds OAuth-ready authentication, real-time subscriptions, and a visual admin panel — with zero changes required to switch back if you don't set `POCKETBASE_URL`.

> ⚠️ **PocketBase mode is currently single-user only.** The default schema has no `role` field on `users` (every login resolves to `role=user`, so no admin can be created), and the session/message/turn queries are not filtered by `user_id`. Multi-user deployments should keep `POCKETBASE_URL` blank and use the default JSON/SQLite backend.

**When to use it:** local single-user setups that want OAuth-ready auth and a visual admin panel without yet caring about per-user isolation.

**Quick start (Docker Compose):**

```bash
# PocketBase starts automatically alongside DeepTutor when using docker compose
docker compose up -d

# 1. Open the admin panel and create your admin account
open http://localhost:8090/_/

# 2. Bootstrap collections (run once)
pip install pocketbase
python scripts/pb_setup.py

# 3. Enable PocketBase in .env and restart
```

**Required `.env` additions:**

```dotenv
POCKETBASE_URL=http://localhost:8090          # or http://pocketbase:8090 inside Docker
POCKETBASE_ADMIN_EMAIL=admin@example.com
POCKETBASE_ADMIN_PASSWORD=your-admin-password
```

**devenv users:**

```bash
devenv up   # starts PocketBase on :8090 alongside backend and frontend
```

Leave `POCKETBASE_URL` unset (or remove it) to fall back to the built-in SQLite backend at any time — no data migration needed for new sessions.

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
| `/app/data/user` | `./data/user` | Settings, workspace, sessions, logs |
| `/app/data/memory` | `./data/memory` | Shared long-term memory (`SUMMARY.md`, `PROFILE.md`) |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | Uploaded documents & vector indices |

These directories survive `docker compose down` and are reused on the next `docker compose up`.

</details>

<details>
<summary><b>Environment variables reference</b></summary>

> See [`.env.example`](.env.example) for the canonical, fully-commented list. The table below covers the variables most users touch.

| Variable | Required | Description |
|:---|:---:|:---|
| `LLM_BINDING` | **Yes** | LLM provider (`openai`, `anthropic`, `deepseek`, etc.) |
| `LLM_MODEL` | **Yes** | Model name (e.g. `gpt-4o`) |
| `LLM_API_KEY` | **Yes** | Your LLM API key |
| `LLM_HOST` | **Yes** | Chat-completions base URL |
| `LLM_API_VERSION` | No | Required for Azure OpenAI; blank otherwise |
| `LLM_REASONING_EFFORT` | No | DeepSeek `high`/`max`/`minimal` or OpenAI o-series `low`/`medium`/`high` |
| `EMBEDDING_BINDING` | Knowledge Base only | Embedding provider |
| `EMBEDDING_MODEL` | Knowledge Base only | Embedding model name |
| `EMBEDDING_API_KEY` | Knowledge Base only | Embedding API key |
| `EMBEDDING_HOST` | Knowledge Base only | Full embedding endpoint URL (v1.3.0+ — called verbatim, no path appended) |
| `EMBEDDING_DIMENSION` | No | Vector dimension; leave empty for auto-detection |
| `EMBEDDING_SEND_DIMENSIONS` | No | Tri-state — `true`/`false`/blank (auto) |
| `SEARCH_PROVIDER` | No | `brave`, `tavily`, `serper`, `jina`, `perplexity`, `searxng`, `duckduckgo` |
| `SEARCH_API_KEY` | No | Search API key |
| `SEARCH_BASE_URL` | No | Required for self-hosted SearXNG |
| `SEARCH_PROXY` | No | Optional HTTP/HTTPS proxy for outbound search traffic |
| `BACKEND_PORT` | No | Backend port (default `8001`) |
| `FRONTEND_PORT` | No | Frontend port (default `3782`) |
| `POCKETBASE_PORT` | No | Docker port mapping for the optional PocketBase sidecar (default `8090`) |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | No | Public backend URL for cloud deployment |
| `NEXT_PUBLIC_API_BASE` | No | Direct backend URL override for the Next.js client |
| `CORS_ORIGIN` | No | Single extra origin appended to the FastAPI CORS allowlist |
| `CORS_ORIGINS` | No | Comma/newline-separated extra origins for authenticated remote deployments |
| `DISABLE_SSL_VERIFY` | No | Disable outbound TLS verification (default `false`) |
| `AUTH_ENABLED` | No | Require login when `true` (default `false`) |
| `NEXT_PUBLIC_AUTH_ENABLED` | No | Optional frontend override; blank derives from `AUTH_ENABLED` |
| `AUTH_SECRET` | No | JWT signing secret; generated under `multi-user/_system/auth/auth_secret` if blank |
| `AUTH_TOKEN_EXPIRE_HOURS` | No | Session duration in hours (default `24`) |
| `AUTH_COOKIE_SECURE` | No | Mark the auth cookie `Secure` when serving over HTTPS (default `false`) |
| `AUTH_USERNAME` | No | Single-user mode: admin username |
| `AUTH_PASSWORD_HASH` | No | Single-user mode: bcrypt hash of admin password |
| `POCKETBASE_URL` | No | Enable the PocketBase sidecar by setting it (single-user only — see warning above) |
| `POCKETBASE_ADMIN_EMAIL` / `POCKETBASE_ADMIN_PASSWORD` | No | Admin credentials for the Python backend to manage PocketBase collections |
| `POCKETBASE_EXTERNAL_URL` | No | Public PocketBase URL for OAuth redirects (remote deployments only) |
| `CHAT_ATTACHMENT_DIR` | No | Override for the chat attachment storage root |

</details>

### Option D — CLI Only

If you just want the CLI without the web frontend:

```bash
# Includes RAG, document parsing, and all built-in LLM provider SDKs.
# Same set as Option B minus FastAPI/uvicorn.
python -m pip install -e ".[cli]"
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

Pages are assembled from 13 block types — text, callout, quiz, flash cards, code, figure, deep dive, animation, interactive demo, timeline, concept graph, section, and user note — each rendered with its own interactive component. A real-time progress timeline lets you watch compilation unfold as the book takes shape.

### 📚 Knowledge Management — Your Learning Infrastructure

<div align="center">
<img src="assets/figs/dt-knowledge.png" alt="Knowledge Management" width="800">
</div>

Knowledge is where you build and manage the document collections, notes, and teaching personas that power everything else in DeepTutor.

- **Knowledge Bases** — Upload PDFs, Office files (DOCX/XLSX/PPTX), Markdown, and a wide range of text and code files to create searchable, RAG-ready collections. Add documents incrementally as your library grows.
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
- **Multi-Channel Presence** — Connect bots to Telegram, Discord, Slack, Feishu, WeChat Work, DingTalk, Matrix, QQ, WhatsApp, Email, and more. Your tutor meets you wherever you are.
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

---

### 👥 Multi-User — Shared Deployments with Per-User Workspaces

<div align="center">
<img src="assets/figs/dt-multi-user.png" alt="Multi-User" width="800">
</div>

Flip on authentication and DeepTutor turns into a multi-tenant deployment with **per-user isolated workspaces** and **admin-curated resources**. The first person to register becomes the admin and configures models, API keys, and knowledge bases on behalf of everyone else. Subsequent accounts are created by the admin (invite-only), each gets their own scoped chat history / memory / notebooks / knowledge bases, and they only see the LLMs, KBs, and skills the admin assigned to them.

**Quick start (5 steps):**

```bash
# 1. In the project root .env, enable auth.
echo 'AUTH_ENABLED=true' >> .env
# Optional — JWT signing secret. Auto-generated on first boot if blank.
echo 'AUTH_SECRET=<paste 64+ random characters>' >> .env

# 2. Restart the web stack — start_web.py mirrors AUTH_ENABLED to the frontend.
python scripts/start_web.py

# 3. Open http://localhost:3782/register and create the first account.
#    The first registration is the only public one; that user becomes admin
#    and the /register endpoint is closed automatically afterward.

# 4. As admin, navigate to /admin/users → "Add user" to provision teammates.

# 5. For each user, click the slider icon → assign LLM profiles, knowledge
#    bases, and skills. Save. The user can now sign in and start working.
```

**What the admin sees:**

- **Full Settings page** at `/settings` — manage LLM / embedding / search providers, API keys, model catalogs, and runtime "Apply".
- **User management** at `/admin/users` — create, promote, demote, and delete accounts. The public `/register` endpoint is automatically closed once the first admin exists; further accounts go through `POST /api/v1/auth/users` (admin-only).
- **Grant editor** — for each non-admin user, pick the model profiles, knowledge bases, and skills they may use. Grants carry **logical IDs only**; API keys never cross the grant boundary.
- **Audit trail** — every grant change and assigned-resource access is appended to `multi-user/_system/audit/usage.jsonl`.

**What ordinary users get:**

- **Isolated workspace** under `multi-user/<uid>/` — their own chat history (`chat_history.db`), memory (`SUMMARY.md` / `PROFILE.md`), notebooks, and personal knowledge bases. Nothing is shared by default.
- **Read-only access** to admin-assigned knowledge bases and skills, surfaced inline next to their own resources with an "Assigned by admin" badge.
- **Redacted Settings page** — only theme, language, and a summary of granted models. API keys, base URLs, and provider endpoints are never returned for non-admin requests.
- **Scoped LLM** — chat turns are routed through the admin-assigned model. If no LLM is granted, the turn is rejected up-front (no silent fallback to the admin's keys).

**Workspace layout:**

```
multi-user/
├── _system/
│   ├── auth/users.json          # Hashed credentials, roles
│   ├── auth/auth_secret         # JWT signing secret (auto-generated)
│   ├── grants/<uid>.json        # Per-user resource grants (admin-managed)
│   └── audit/usage.jsonl        # Audit trail
└── <uid>/
    ├── user/
    │   ├── chat_history.db
    │   ├── settings/interface.json
    │   └── workspace/{chat,co-writer,book,...}
    ├── memory/{SUMMARY.md,PROFILE.md}
    └── knowledge_bases/...
```

**Configuration reference:**

| Variable | Required | Description |
|:---|:---|:---|
| `AUTH_ENABLED` | Yes | Set to `true` to enable multi-user auth. Default `false` (single-user mode — admin paths everywhere). |
| `AUTH_SECRET` | Recommended | JWT signing secret. Auto-generated under `multi-user/_system/auth/auth_secret` if blank. |
| `AUTH_TOKEN_EXPIRE_HOURS` | No | JWT lifetime; defaults to `24`. |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | No | Single-user fallback credentials (legacy env-var path). Leave blank when using multi-user. |
| `NEXT_PUBLIC_AUTH_ENABLED` | Auto | Mirrored from `AUTH_ENABLED` by `start_web.py` so the Next.js middleware redirects unauthenticated requests to `/login`. |

> ⚠️ **PocketBase mode (`POCKETBASE_URL` set) is single-user only.** The default PocketBase schema has no `role` field on `users` (every login resolves to `role=user`, no admin can be created), and `sessions` / `messages` / `turns` queries are not filtered by `user_id`. Multi-user deployments must keep `POCKETBASE_URL` blank and use the default JSON/SQLite backend.

> ⚠️ **Single-process recommendation.** The first-user-becomes-admin promotion is protected by an in-process `threading.Lock`. Multi-worker deployments should provision the first admin offline (start with `AUTH_ENABLED=false`, register the admin via `python scripts/start_tour.py` or the bootstrap flow, then flip the flag) or back the user store with an external system.

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
