<div align="center">

<p align="center"><img src="assets/figs/logo/logo.png" alt="DeepTutor logo" height="56" style="vertical-align: middle;">&nbsp;<img src="assets/figs/logo/banner.png" alt="DeepTutor" height="48" style="vertical-align: middle;"></p>

# DeepTutor: Lifelong Personalized Tutoring

<p align="center">
  <a href="https://deeptutor.info" target="_blank"><img alt="Docs — deeptutor.info" src="https://img.shields.io/badge/Docs-deeptutor.info%20%E2%86%97-0A0A0A?style=for-the-badge&labelColor=F5F5F4" height="36"></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/17099?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://trendshift.io/repositories/17099?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/17099/daily" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://trendshift.io/repositories/17099?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/17099/weekly?language=Python" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>
</p>

<p align="center">
  <a href="README.md"><img alt="English" height="40" src="https://img.shields.io/badge/English-BCDCF7"></a>&nbsp;
  <a href="assets/README/README_CN.md"><img alt="简体中文" height="40" src="https://img.shields.io/badge/简体中文-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_JA.md"><img alt="日本語" height="40" src="https://img.shields.io/badge/日本語-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_ES.md"><img alt="Español" height="40" src="https://img.shields.io/badge/Español-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_FR.md"><img alt="Français" height="40" src="https://img.shields.io/badge/Français-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_AR.md"><img alt="Arabic" height="40" src="https://img.shields.io/badge/Arabic-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_RU.md"><img alt="Русский" height="40" src="https://img.shields.io/badge/Русский-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_HI.md"><img alt="Hindi" height="40" src="https://img.shields.io/badge/Hindi-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_PT.md"><img alt="Português" height="40" src="https://img.shields.io/badge/Português-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_TH.md"><img alt="Thai" height="40" src="https://img.shields.io/badge/Thai-CDCFD4"></a>&nbsp;
  <a href="assets/README/README_PL.md"><img alt="Polski" height="40" src="https://img.shields.io/badge/Polski-CDCFD4"></a>
</p>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](./Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Features](#-key-features) · [Get Started](#-get-started) · [Explore](#-explore-deeptutor) · [CLI](#%EF%B8%8F-deeptutor-cli--agent-native-interface) · [Ecosystem](#-ecosystem--eduhub--the-skills-community) · [Community](#-community)

</div>

---

> 🤝 **We welcome any kinds of contributing!** Vote on roadmap items or propose new ones at [`Roadmap`](https://github.com/HKUDS/DeepTutor/issues/498), and see our [Contributing Guide](CONTRIBUTING.md) for branching strategy, coding standards, and how to get started.

### 📦 Releases

> **[2026.7.9]** [v1.5.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.5.1) — Remove a single failed document from a knowledge base — even one stuck in an **error** state — instead of deleting and rebuilding the whole base.

> **[2026.7.4]** [v1.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.5.0) — LlamaIndex ingestion now honors your **Document Parsing** engine with multimodal image extraction, Partner & Soul ids stay URL-safe for non-Latin names, and optional RAG extras install cleanly on Python 3.14+.

<details>
<summary><b>Past releases (more than 1 week ago)</b></summary>

> **[2026.6.30]** [v1.4.15](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.15) — A native **Mattermost** channel for Partners, plus fixes so Guided Learning multiple-choice questions grade correctly and a configured zero chunk overlap is honored.

> **[2026.6.29]** [v1.4.14](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.14) — Click an assigned partner to chat in one step, Deep Research flags partial reports, LightRAG indexes without MinerU, FAISS handles non-ASCII paths, and PocketBase sessions are isolated per user.

> **[2026.6.27]** [v1.4.13](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.13) — Partners support non-Latin names and become assignable to users, logos render after login (#599), tiny knowledge bases retrieve reliably, and containers start cleanly under rootless Podman.

> **[2026.6.24]** [v1.4.12](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.12) — A new **LightRAG Server** retrieval engine, a lightweight **PyMuPDF4LLM** parsing engine, and a FAISS vector backend that makes large knowledge-base retrieval dramatically faster.

> **[2026.6.23]** [v1.4.11](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.11) — Native tool calling on every cloud OpenAI-compatible provider, a redesigned admin Users page, LaTeX in quiz options, an honest session-loading spinner, and configurable container host binding.

> **[2026.6.21]** [v1.4.10](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.10) — A self-service **Profile** page with avatars, a rootless-ready container guide with a single-port request-time proxy, and deny-by-default MCP tools for non-admin users.

> **[2026.6.19]** [v1.4.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.9) — Settings polish: Search shows only the fields your provider needs, connection profiles can be renamed and auto-named by provider, and graded Mastery Path questions flow into your Question Bank.

> **[2026.6.18]** [v1.4.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.8) — Connect your own **Partners** under **My Agents** and consult them live in chat — answering through their own persona, library and skills — and each Partner gains its own private memory.

> **[2026.6.18]** [v1.4.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.7) — Connect your local **Claude Code / Codex** and consult it live mid-turn, **My Agents** graduates to a top-level `/agents`, and Partner conversations gain branch / resume / delete with a replayable trace.

> **[2026.6.17]** [v1.4.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.6) — Four-surface consolidation: a Space learning dashboard with importable **My Agents** and top-level Memory, a **Knowledge Center** with GraphRAG / PageIndex / LightRAG / linked-KB / Obsidian, opened-up Settings, and per-model capability gating.

> **[2026.6.14]** [v1.4.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.5) — Guided Learning rebuilt on the chat agent loop with a hard per-type mastery gate and a `/learning` dashboard, a new loop-plugin framework, plus Markdown export / save-to-notebook for Partner conversations.

> **[2026.6.13]** [v1.4.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.4) — Install community skills from [ClawHub](https://clawhub.ai/) with `deeptutor skill install` behind a security gate, plus real in-browser DOCX/XLSX previews for knowledge-base files.

> **[2026.6.12]** [v1.4.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.3) — TutorBot becomes **Partners** on a production-grade IM pipeline (15 channels, live streaming), Chat moves to a single agent loop, real per-user isolation, and a rebuilt Visualize.

> **[2026.5.28]** [v1.4.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.2) — Stability + polish: Gemini 2.5+ unblocked across Visualize and Chat, auth-routing fix (#485), smooth-streaming chat UX, a Recents sidebar, and Lemonade local-provider support.

> **[2026.5.27]** [v1.4.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.1) — Security + stability: TutorBot tool sandbox locked down, per-user resource isolation, multimodal image fallback, an HTTP/SSE API for TutorBots, and a v1.4.0 chat regression fix.

> **[2026.5.22]** [v1.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.0) — GA cut of v1.4: Auto Mode, three-layer Memory, agentic Deep Research / Solve / Question, LlamaIndex RAG refactor, Visualize/Animator merge, and restart-safe turn runtime.

> **[2026.5.21]** [v1.4.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.4.0-beta) — Three-layer Memory workbench (L1/L2/L3), every chat capability rebuilt on a single agentic engine, LlamaIndex-only RAG, and a unified Settings + Capabilities surface.

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

- **2026-05-22** 🌐 Official docs site live at [**deeptutor.info**](https://deeptutor.info/) — guides, references, and capability tours in one place.
- **2026-04-19** 🎉 20k stars in 111 days! Thank you for the support toward truly personalized, intelligent tutoring.
- **2026-04-10** 📄 Our paper is live on arXiv — read the [preprint](https://arxiv.org/abs/2604.26962) for the design and ideas behind DeepTutor.
- **2026-02-06** 🚀 10k stars in just 39 days! A huge thank you to our incredible community.
- **2026-01-01** 🎊 Happy New Year! Join our [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78), or [Discussions](https://github.com/HKUDS/DeepTutor/discussions) — let's shape DeepTutor together.
- **2025-12-29** 🎓 DeepTutor is officially released!

## ✨ Key Features

DeepTutor is an agent-native learning workspace that connects tutoring, problem solving, quiz generation, research, visualization, and mastery practice in one extensible system.

- **One runtime for every mode** — Chat, Quiz, Research, Visualize, Solve, and Mastery Path run on the same agent loop, so you switch the objective, not the engine, and context moves with the learner.
- **Connected learning context** — Knowledge bases, books, Co-Writer drafts, notebooks, question banks, personas, and Memory stay available across every workflow instead of living in isolated tools.
- **Subagents and Partners** — consult a live Claude Code, Codex, or Partner from any turn (or import their past conversations), and run persistent IM companions on the same brain.
- **Multi-engine knowledge** — versioned RAG libraries across LlamaIndex, PageIndex, GraphRAG, LightRAG, or a linked Obsidian vault, with pluggable document parsing.
- **Extensible tools and skills** — built-in tools, MCP servers, image / video / voice generation models, and installable community skills from EduHub.
- **Inspectable memory** — L1 traces, L2 surface summaries, and L3 synthesis make personalization visible and editable, with a Memory Graph that traces every claim back to its evidence.

---

## 🚀 Get Started

DeepTutor ships four installation paths. They all share one workspace layout: settings live in `data/user/settings/` under the directory you launch from (or under `DEEPTUTOR_HOME` / `deeptutor start --home` if you set one explicitly). For the full app, the recommended flow is **pick a workspace directory → install → `deeptutor init` → `deeptutor start`**.

<details>
<summary><b>Option 1 — Install From PyPI</b> · full local Web app + CLI, no clone required</summary>

Full local Web app + CLI, no clone required. Needs **Python 3.11+** and a **Node.js 20+** runtime on PATH (the packaged Next.js standalone server is spawned by `deeptutor start`).

```bash
mkdir -p my-deeptutor && cd my-deeptutor
pip install -U deeptutor
deeptutor init     # prompts for ports + LLM provider + optional embedding
deeptutor start    # starts backend + frontend; keep the terminal open
```

`deeptutor init` prompts for backend port (default `8001`), frontend port (default `3782`), LLM provider / base URL / API key / model, and an optional embedding provider for Knowledge Base / RAG.

After `deeptutor start`, open the frontend URL printed in the terminal — by default [http://127.0.0.1:3782](http://127.0.0.1:3782). Press `Ctrl+C` in that terminal to stop both backend and frontend. Skipping `deeptutor init` is fine for a quick trial; the app boots with default ports and empty model settings, configure them later in **Settings → Models**.

</details>

<details>
<summary><b>Option 2 — Install From Source</b> · develop against a checkout</summary>

For development against a checkout. Use **Python 3.11+** and **Node.js 22 LTS** to match CI and Docker.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Create a venv (macOS/Linux). Windows PowerShell:
#   py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# Install backend + frontend deps
python -m pip install -e .
( cd web && npm ci --legacy-peer-deps )

deeptutor init
deeptutor start
```

Source installs run Next.js in dev mode against the local `web/` directory; everything else (config layout, ports, stop with `Ctrl+C`) matches Option 1.

<details>
<summary><b>Conda environment</b> (instead of <code>venv</code>)</summary>

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
```

</details>

<details>
<summary><b>Optional install extras</b> — dev / partners / matrix / math-animator</summary>

```bash
pip install -e ".[dev]"             # tests/lint tools
pip install -e ".[partners]"        # Partner IM channel SDKs + MCP client
pip install -e ".[matrix]"          # Matrix channel without E2EE/libolm
pip install -e ".[matrix-e2e]"      # Matrix E2EE; requires libolm
pip install -e ".[math-animator]"   # Manim addon; requires LaTeX/ffmpeg/system libs
```

</details>

<details>
<summary><b>Frontend dependency tweaks & dev-server troubleshooting</b></summary>

**Changing frontend dependencies:** run `npm install --legacy-peer-deps` to refresh `web/package-lock.json`, then commit both `web/package.json` and `web/package-lock.json`.

**Stuck dev server:** if `deeptutor start` reports an existing frontend that isn't responding, stop the PID it prints. If no Next.js process is actually running, the lock files are stale — remove them and retry:

```bash
rm -f web/.next/dev/lock web/.next/lock
deeptutor start
```

</details>

</details>

<details>
<summary><b>Option 3 — Docker</b> · one self-contained container</summary>

One container for the full Web app. Images on GitHub Container Registry:

- `ghcr.io/hkuds/deeptutor:latest` — stable release
- `ghcr.io/hkuds/deeptutor:pre` — pre-release, when available

> See [CONTAINERIZATION.md](./CONTAINERIZATION.md) for podman/rootless/read-only-rootfs deployments and the full per-installation guide.

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

> **Only `3782` needs to be published.** The browser talks exclusively to the frontend origin; the Next.js middleware (`web/proxy.ts`) forwards `/api/*` and `/ws/*` to the FastAPI backend **inside the container**. Publishing `8001` (`-p 127.0.0.1:8001:8001`) is optional — handy only for hitting the API directly with curl or scripts.

Open [http://127.0.0.1:3782](http://127.0.0.1:3782). The container creates `/app/data/user/settings/*.json` on first boot; configure model providers from the Web Settings page. Config, API keys, logs, workspace files, memory, and knowledge bases persist in the `deeptutor-data` volume.

- **Different host ports:** change the left side of each `-p host:container` mapping (e.g. `-p 127.0.0.1:8088:3782`). If you change container-side ports in `/app/data/user/settings/system.json`, restart and update the right side of each mapping to match.
- **Detached:** add `-d`, then `docker logs -f deeptutor` to follow, `docker stop deeptutor` to stop, `docker rm deeptutor` before reusing the name. The `deeptutor-data` volume keeps your settings and workspace across restarts.

**Remote Docker / reverse proxy:** the browser only talks to the frontend
origin (`:3782`); the in-container Next.js middleware forwards `/api/*` and
`/ws/*` to the backend server-side. For the common single-container case you
don't configure an API base at all — just point your reverse proxy / TLS
terminator at `:3782`. You only need an API base for a **split deployment**
(backend in a separate container/host): set `next_public_api_base` in
`data/user/settings/system.json` to the in-network address the frontend server
uses to reach the backend (it's read server-side, never sent to the browser).

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

`next_public_api_base_external` (and its alias `public_api_base`) are accepted as
lower-precedence fallbacks. CORS uses frontend **origins**, not API URLs. With
auth disabled, DeepTutor permits normal HTTP/HTTPS browser origins by default.
With auth enabled, add exact frontend origins:

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

<details>
<summary><b>Connecting to Ollama / LM Studio / llama.cpp / vLLM / Lemonade on the host</b></summary>

Inside Docker, `localhost` is the container itself, not your host machine. To reach a model service running on the host, use the host gateway (recommended):

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 -p 127.0.0.1:8001:8001 \
  --add-host=host.docker.internal:host-gateway \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Then in **Settings → Models**, point the provider Base URL at `host.docker.internal`:

- Ollama LLM: `http://host.docker.internal:11434/v1`
- Ollama embedding: `http://host.docker.internal:11434/api/embed`
- LM Studio: `http://host.docker.internal:1234/v1`
- llama.cpp: `http://host.docker.internal:8080/v1`
- Lemonade: `http://host.docker.internal:13305/api/v1`

Docker Desktop (macOS/Windows) usually resolves `host.docker.internal` without `--add-host`. On Linux, the flag is the portable way to create that hostname on modern Docker Engine.

**Linux alternative — host networking:** add `--network=host` and drop the `-p` flags. The container shares the host network directly, so open [http://127.0.0.1:3782](http://127.0.0.1:3782) (or the `frontend_port` in `system.json`), and host services can be reached with normal localhost URLs like `http://127.0.0.1:11434/v1`. Note that host networking exposes container ports directly on the host and may conflict with existing services — to keep them on loopback, set `BACKEND_HOST=127.0.0.1` and `FRONTEND_HOST=127.0.0.1` (see [CONTAINERIZATION.md](./CONTAINERIZATION.md)).

</details>

</details>

<details>
<summary><b>Option 4 — CLI Only</b> · no Web UI, from a source checkout</summary>

When you don't need the Web UI. The CLI-only package is installed from a source checkout, not from PyPI.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Create a venv (macOS/Linux). Windows PowerShell:
#   py -3.11 -m venv .venv-cli ; .\.venv-cli\Scripts\Activate.ps1
python3 -m venv .venv-cli && source .venv-cli/bin/activate
python -m pip install --upgrade pip

python -m pip install -e ./packaging/deeptutor-cli
deeptutor init --cli
deeptutor chat
```

`deeptutor init --cli` shares the same `data/user/settings/` layout as the full app but skips the backend/frontend port prompts and defaults embeddings to **off** (choose `Yes` if you plan to use `deeptutor kb …` or RAG tools). It still writes a complete runtime layout (`system.json`, `auth.json`, `integrations.json`, `model_catalog.json`, `main.yaml`, `agents.yaml`) and still prompts for the active LLM provider and model.

<details>
<summary><b>Common commands</b></summary>

```bash
deeptutor chat                                          # interactive REPL
deeptutor chat --capability deep_solve --tool rag --kb my-kb
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4" --tool rag --kb my-kb
deeptutor kb create my-kb --doc textbook.pdf
deeptutor memory show
deeptutor config show
```

</details>

The local `deeptutor-cli` install ships no Web assets or server dependencies. Keep the source checkout around — the editable install points to it. To add the Web app later, install the PyPI package (Option 1) and run `deeptutor init` + `deeptutor start` from the same workspace.

</details>

<details>
<summary><b>Code Execution Sandbox (office skills)</b> · running model-generated code for docx / pdf / pptx / xlsx</summary>

The built-in office skills — **docx / pdf / pptx / xlsx** — work by having the
model write a short Python script (`python-docx`, `reportlab`, `openpyxl`, …),
run it through the `exec` / `code_execution` tools, and hand back a download URL.
Those tools mount whenever a sandbox backend is active, which it is **by default**
in every deployment shape:

- **Local (Option 1 / 2) and Docker (Option 3, single container):** a restricted
  subprocess sandbox runs the model's code (on the host locally, or inside the
  container under Docker — the container being its own isolation boundary).
- **docker-compose:** routed instead to a hardened, least-privileged **runner
  sidecar** (`Dockerfile.runner`) via `DEEPTUTOR_SANDBOX_RUNNER_URL` — the
  strongest posture, and preferred automatically when present.

The subprocess sandbox is controlled by the `sandbox_allow_subprocess` setting in
`data/user/settings/system.json` (default `true`). Running model-generated code
on your host is a real trust decision — set it to `false` (or export
`DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS=0`) to disable host-side execution, at the
cost of the office skills no longer being able to produce files.

</details>

<details>
<summary><b>Configuration reference</b> — config files under <code>data/user/settings/</code> (JSON/YAML)</summary>

Everything under `data/user/settings/` is plain JSON/YAML. The **Settings** page in the browser is the recommended editor.

| File | Purpose |
|:---|:---|
| `model_catalog.json` | LLM, embedding, and search provider profiles; API keys; active models |
| `system.json` | Backend/frontend ports, public API base, CORS, SSL verification, attachment directory |
| `auth.json` | Optional auth toggle, username, password hash, token/cookie settings |
| `integrations.json` | Optional PocketBase and sidecar integration settings |
| `interface.json` | UI language / theme / sidebar preferences |
| `main.yaml` | Runtime behavior defaults and path injection |
| `agents.yaml` | Capability/tool temperature and token settings |

Project-root `.env` is **not** read as an application config file. For a minimal model setup, open **Settings → Models**, add an LLM profile (Base URL / API key / model name), and save. Add an embedding profile only if you plan to use Knowledge Base / RAG features.

</details>

## 📖 Explore DeepTutor

Start with the main surfaces you will use day to day: Chat, Partners, My Agents, Co-Writer, Book, Knowledge Center, Learning Space, Memory, and Settings. The tour then covers Multi-User deployments for shared, isolated workspaces.

<div align="center">
<img src="assets/figs/web-1.4.6+/OVERVIEW.png" alt="DeepTutor home — the Chat workspace with every surface in the sidebar" width="900">
</div>

<details>
<summary><b>🏗️ System architecture</b></summary>

<div align="center">
<img src="assets/figs/system/system%20architecture.png" alt="DeepTutor system architecture" width="900">
</div>

</details>

<details>
<summary><b>💬 Chat — The Agent Loop You Actually Use</b></summary>

Chat is the default capability and where most work begins. A single thread can talk normally, call tools, ground itself in selected knowledge bases, read attachments, generate images, consult subagents, write notebook records, and continue with the same context across turns.

<div align="center">
<img src="assets/figs/web-1.4.6+/home/00-overview.png" alt="DeepTutor chat workspace" width="900">
</div>

The loop is deliberately simple: the model thinks in rounds, calls tools when useful, observes the results, and finishes with a tool-free message. `ask_user` is special — instead of guessing, the agent can pause the turn, ask a structured clarifying question, and resume once you answer.

<div align="center">
<img src="assets/figs/system/chat-agent-loop.png" alt="DeepTutor chat agent loop" width="900">
</div>

User-toggleable tools are `brainstorm`, `web_search`, `paper_search`, `reason`, and `geogebra_analysis` — plus `imagegen` and `videogen` once you configure the matching generation model. Contextual tools such as `rag`, `read_source`, `read_memory`, `write_memory`, `read_skill`, `load_tools`, `exec`, `web_fetch`, `ask_user`, `list_notebook`, `write_note`, `github`, and `consult_subagent` mount automatically when the turn has the right context.

Context comes in two kinds: **sticky session context** (subagent, knowledge bases, persona, model, voice) lives on the composer toolbar and persists across turns; **one-time references** (files, chat history, books, notebooks, question bank, imported agents) come from the `+` menu for a single turn.

Chat is also the launch point for deeper capabilities: **Quiz** for question generation, **Research** for cited reports, **Visualize** for charts / diagrams / animations, and — under *More Capabilities* — **Solve** for worked reasoning and **Mastery Path** for learning-plan flows.

</details>

<details>
<summary><b>🤝 Partner — Persistent Companions on the Same Brain</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/partners/00-partners%20overview.png" alt="DeepTutor partners workspace" width="900">
</div>

Partners are persistent companions with their own soul, model policy, library, memory, and channels. They are not a separate bot engine: every inbound web or IM message becomes a normal `ChatOrchestrator` turn inside a partner-scoped workspace. A partner is "a chat that has a personality and a phone number."

<div align="center">
<img src="assets/figs/system/partners-architecture.png" alt="DeepTutor partners architecture" width="900">
</div>

Each partner has a `SOUL.md`, model selection, channels, tool policy, and assigned library. Knowledge bases, skills, and notebooks are copied into `data/partners/<id>/workspace/`, so the same RAG, skill, notebook, and memory tools work without special cases. A partner reads its owner's memory but writes only its own.

<div align="center">
<img src="assets/figs/web-1.4.6+/partners/02-IM%20config%20for%20each%20partner.png" alt="Per-partner IM channel configuration" width="900">
</div>

The channel layer is schema-driven and can connect to IM platforms such as Feishu, Telegram, Slack, Discord, DingTalk, QQ/NapCat, WeCom, WhatsApp, Zulip, Mattermost, Matrix, Mochat, and Microsoft Teams depending on installed extras and configured credentials. A partner can also be connected as a subagent and consulted from a normal chat turn — see **My Agents** below.

</details>

<details>
<summary><b>🧑‍🚀 My Agents — Consult & Import Other Agents</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/myagents/00-overview.png" alt="DeepTutor My Agents workspace" width="900">
</div>

My Agents turns other agents into context for DeepTutor, and does two distinct things. **Connect a live agent** — a Claude Code or Codex CLI on your machine, or one of your Partners — and consult it from inside a chat turn: DeepTutor actually *runs* the other agent and streams its work into the Activity panel via the `consult_subagent` tool. Select it with the Agent chip (or type `@`), and set how many rounds the consult may take.

<div align="center">
<img src="assets/figs/web-1.4.6+/home/08-subagent%20demo%20with%20claude%20code.png" alt="Consulting a Claude Code subagent live" width="900">
</div>

**Import past conversations** — bring in your existing Claude Code and Codex history as named, searchable, resumable agents. Pick which days to import; refreshing re-syncs them. Reference an imported conversation from any chat turn via `+` → My Agents, and DeepTutor reads it as a third-party transcript — it stays *their* conversation, not DeepTutor's own voice.

</details>

<details>
<summary><b>✍️ Co-Writer — Selection-Aware Markdown Drafting</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/co-writer/00-overview.png" alt="DeepTutor Co-Writer workspace" width="900">
</div>

Co-Writer is a split-view Markdown workspace for reports, tutorials, notes, and long-form learning artifacts. Documents autosave and render a live preview (KaTeX math, diagram fences), and can be saved back into notebooks when a draft becomes reusable context.

<div align="center">
<img src="assets/figs/web-1.4.6+/co-writer/01-edit%20panel.png" alt="Co-Writer editor with live preview" width="900">
</div>

Its defining idea is **surgical editing**: select a span and ask DeepTutor to rewrite, expand, or shorten it. The edit agent can ground the change in a knowledge base or web evidence, keeps a trace of its tool calls, and shows every change as an accept/reject diff — so nothing lands until you approve it.

</details>

<details>
<summary><b>📖 Book — Living Books from Your Materials</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/book/00-book_overview.png" alt="DeepTutor book library" width="900">
</div>

Book turns selected sources into an interactive **living book** — not a static PDF, but a reading environment built from typed blocks. A book can start from knowledge bases, notebooks, question banks, or chat history; the creation flow proposes a chapter outline before content is generated, so you review the shape instead of accepting a blind one-shot output.

<p align="center">
<img src="assets/figs/web-1.4.6+/book/01-book-demo-quiz%20card.png" alt="Book quiz block" width="31%">
&nbsp;
<img src="assets/figs/web-1.4.6+/book/02-book-demo-manim%20video.png" alt="Book Manim animation block" width="31%">
&nbsp;
<img src="assets/figs/web-1.4.6+/book/03-book-demo%20interactive%20module.png" alt="Book interactive widget block" width="31%">
</p>

Each chapter compiles into typed blocks — text, callouts, quizzes, flash cards, timelines, code, figures, interactive HTML, animations, concept graphs, deep dives, and user notes — and every page has its own Page Chat. Blocks are editable: insert, move, regenerate, or switch a block's type without rewriting the chapter. Maintenance commands such as `deeptutor book health` and `deeptutor book refresh-fingerprints` help detect when source knowledge has drifted from compiled pages.

</details>

<details>
<summary><b>📚 Knowledge Center — Multi-Engine RAG Libraries</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/knowledge/00-overview.png" alt="DeepTutor Knowledge Center" width="900">
</div>

Knowledge bases are the document collections behind RAG — they ground Chat turns, Co-Writer edits, Book generation, and Partner conversations. What's distinctive is a **choice of retrieval engines**: **LlamaIndex** (the default, local vector + BM25), **PageIndex** (hosted, reasoning retrieval with page-level citations), **GraphRAG** and **LightRAG** (knowledge-graph retrieval), **LightRAG Server** (retrieval offloaded to an external LightRAG instance you connect over HTTP), or a linked **Obsidian** vault the tutor reads and writes in place. Each KB is bound to one engine.

<div align="center">
<img src="assets/figs/web-1.4.6+/knowledge/01-create%20knowledge%20base.png" alt="Create a knowledge base" width="900">
</div>

Creating a KB, you either **create new** (upload documents and build a fresh index) or **link existing** (reuse an index built elsewhere, read in place with no re-index). Re-indexing writes a new flat `version-N` directory and keeps prior ones, so a working index is never destroyed mid-rebuild. A single document can be removed even from an **error**-state base — dropping a file that failed to parse without a full delete-and-rebuild. Document parsing — Text-only, MinerU, Docling, markitdown, or PyMuPDF4LLM — is chosen in **Settings → Knowledge Base**, with local model downloads off by default. The CLI mirrors the lifecycle with `deeptutor kb list`, `info`, `create`, `add`, `search`, `set-default`, and `delete`.

</details>

<details>
<summary><b>🌐 Learning Space — Skills, Personas, and Reusable Context</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/learning-space/00-overview.png" alt="DeepTutor Learning Space hub" width="900">
</div>

Learning Space is the library and personalization layer — where the things that persist live. **Conversations & Materials** holds your chat history, notebooks, and a question bank (each saved question keeps your answer, the reference answer, and an explanation). **Personalization** holds mastery paths, personas (behavior presets such as *peer*, *research-assistant*, *teacher*), and skills (`SKILL.md` playbooks the model reads on demand). Everything here can be reused from Chat, Partners, Co-Writer, and Book.

<div align="center">
<img src="assets/figs/web-1.4.6+/learning-space/07-%20download%20skills%20from%20eduhub.png" alt="Import skills from EduHub" width="900">
</div>

You don't have to write every skill yourself — **Import from EduHub** browses the community catalog and downloads a skill straight into your library through a security gate (see [Ecosystem](#-ecosystem--eduhub--the-skills-community)).

</details>

<details>
<summary><b>🧠 Memory — Inspectable Personalization</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/memory/00-overview.png" alt="DeepTutor memory overview" width="900">
</div>

Memory is a file-backed, three-layer system you can read, curate, and audit — deliberately *not* a hidden vector store. **L1** is the workspace mirror plus an append-only event trace (`trace/<surface>/<date>.jsonl`); **L2** is per-surface curated facts (`L2/<surface>.md`); **L3** is cross-surface synthesis (`L3/<profile|recent|scope|preferences>.md`). Because L2 cites L1 and L3 cites L2, nothing in your profile is unaccountable.

<div align="center">
<img src="assets/figs/web-1.4.6+/memory/01-3%20layer%20memory%20graph.png" alt="DeepTutor memory graph" width="900">
</div>

The Memory Graph shows the whole pyramid — L3 synthesis at the centre, L2 in the middle ring, L1 traces on the outside — so you can trace any synthesized claim back to the exact raw event behind it. Memory is tracked across `chat`, `notebook`, `quiz`, `kb`, `book`, partner, and `cowriter` surfaces; the consolidator's Update / Audit / Dedup budgets are tuned in **Settings → Memory**.

</details>

<details>
<summary><b>⚙️ Settings — One Control Plane</b></summary>

<div align="center">
<img src="assets/figs/web-1.4.6+/settings/00-setting%20overview.png" alt="DeepTutor settings hub" width="900">
</div>

Settings is the operational control plane, with a live status strip (Backend, LLM, Embedding, Search) and one card per area: **Appearance** (theme + UI language), **Network** (API base, ports, CORS), **Models** (LLM, Embedding, Search, Text-to-Speech, Speech-to-Text, Image Generation, Video Generation), **Knowledge Base** (document parsing engine), **Chat** (tools, MCP servers, per-capability parameters), **Partners & Agents** (the subagents you can consult from a turn), and **Memory** (the consolidator's budgets).

<div align="center">
<img src="assets/figs/web-1.4.6+/settings/01-appearance%20settings.png" alt="DeepTutor appearance settings and themes" width="900">
</div>

Most sections use a draft-and-apply flow, so you can test a provider before committing it. Four themes ship in the box — Default, Cream, Dark, and Glass. Project-root `.env` files are intentionally ignored; runtime configuration lives under `data/user/settings/*.json` unless `DEEPTUTOR_HOME` or `deeptutor start --home` points the app elsewhere.

</details>

<details>
<summary><b>👥 Multi-User — Shared Deployments</b> · optional auth, isolated per-user workspaces</summary>

Authentication is **off by default** — DeepTutor runs single-user. Turn it on and one `data/` tree hosts an admin workspace, isolated per-user workspaces, and partner workspaces side by side:

```text
data/
├── user/                    # Admin workspace + global settings
├── users/<uid>/             # Per-user scope: chat history, memory, notebooks, KBs
├── partners/<id>/workspace/ # Partner (synthetic-user) scope
└── system/                  # auth/users.json · grants/<uid>.json · audit/usage.jsonl
```

The **first registered user becomes admin** and owns model catalogs, provider credentials, shared knowledge bases, skills, and per-user grants. Everyone else gets an isolated workspace and a redacted Settings page — admin-assigned models, KBs, and skills show up as scoped, read-only options, never as raw API keys.

**Enable it:** turn auth on in `data/user/settings/auth.json`, restart `deeptutor start`, register the first admin at `/register`, then add users from `/admin/users` and assign models, KBs, skills, partners, tool/MCP policy, and code-execution access through grants.

> PocketBase stays a single-user integration — keep `integrations.pocketbase_url` blank for multi-user deployments unless you've wired up an external user store.

</details>

## ⌨️ DeepTutor CLI — Agent-Native Interface

One `deeptutor` binary, two ways in: an interactive **REPL** for people who live in the terminal, and structured **JSON** for other agents that drive DeepTutor as a tool. Same capabilities, tools, and knowledge bases either way.

<details>
<summary><b>Drive it yourself</b></summary>

`deeptutor chat` opens an interactive REPL; `deeptutor run <capability> "<message>"` fires a single turn and exits. Both speak the same `--capability`, `--tool`, `--kb`, and `--config` flags.

```bash
deeptutor chat                                              # interactive REPL
deeptutor chat --capability deep_solve --kb my-kb --tool rag
deeptutor run chat "Explain the Fourier transform" --tool rag --kb textbook
deeptutor run deep_research "Survey 2026 papers on RAG" \
  --config mode=report --config depth=standard
```

Everything the Web app does is here too — knowledge bases (`kb`), sessions (`session`), partners (`partner`), skills (`skill`), notebooks, memory, and config. Full list below.

</details>

<details>
<summary><b>Let an agent drive it</b></summary>

DeepTutor is built to be *operated by another agent*. Add `--format json` to any `run` and each turn streams **NDJSON — one event per line** (`content`, `tool_call`, `tool_result`, `done`, …), every line tagged with its `session_id`. Runs are headless-safe: an `ask_user` pause with no TTY auto-resolves with an empty reply instead of hanging.

```bash
# One shot, machine-readable
deeptutor run deep_solve "Find d/dx[sin(x^2)]" --tool reason --format json

# Chain turns in one stateful session — capture the id, reuse it
SID=$(deeptutor run deep_research "Survey 2026 papers on RAG" \
  --config mode=report --config depth=standard --format json \
  | jq -r 'select(.type=="done").session_id')
deeptutor run deep_question "Quiz me on that survey" --session "$SID" --format json
```

The repo ships a root [`SKILL.md`](SKILL.md) — a ~150-line handover doc that teaches any tool-using LLM the whole surface in one read. Hand it to Claude Code, Codex, or OpenCode (they pick up `SKILL.md` automatically), or wrap `deeptutor run` as a tool in a LangChain / AutoGen loop. Full recipes: [Agent Handoff](https://deeptutor.info/docs/cli/agent-handoff/).

</details>

<details>
<summary><b>Command reference</b></summary>

| Command | Description |
|:---|:---|
| `deeptutor init` | Create or update `data/user/settings` for the current workspace |
| `deeptutor start [--home PATH]` | Launch backend + frontend together |
| `deeptutor serve [--port PORT]` | Start only the FastAPI backend |
| `deeptutor run <capability> <message>` | Run a single capability turn (`chat`, `deep_solve`, `deep_question`, `deep_research`, `visualize`, `math_animator`, `mastery_path`); add `--format json` for NDJSON output |
| `deeptutor chat` | Interactive REPL with capability, tool, KB, notebook, and history controls |
| `deeptutor partner list/create/start/stop` | Manage IM-connected partners |
| `deeptutor kb list/info/create/add/search/set-default/delete` | Manage LlamaIndex knowledge bases |
| `deeptutor skill search/install/list/remove/login/logout/publish/update` | Manage skills, install from hubs, and publish your own (`eduhub:<slug>` by default, see Ecosystem) |
| `deeptutor memory show/clear` | Inspect L2/L3 memory docs or clear L1/all memory |
| `deeptutor session list/show/open/rename/delete` | Manage shared sessions |
| `deeptutor notebook list/create/show/add-md/replace-md/remove-record` | Manage notebooks from Markdown files |
| `deeptutor book list/health/refresh-fingerprints` | Inspect books and refresh source fingerprints |
| `deeptutor plugin list/info` | Inspect registered tools and capabilities |
| `deeptutor config show` | Print configuration summary |
| `deeptutor provider login <provider>` | Provider auth (`openai-codex` OAuth login; `github-copilot` validates an existing Copilot auth session) |

</details>

<details>
<summary><b>CLI-only distribution</b></summary>

The CLI-only package lives in `packaging/deeptutor-cli`. In this checkout, install it from source:

```bash
python -m pip install -e ./packaging/deeptutor-cli
```

It isn't published to PyPI yet, so the main [Get Started](#-get-started) section keeps the source-install path.

</details>

## 🧩 Ecosystem — EduHub & the Skills Community

DeepTutor skills use the open **Agent-Skills** format — a folder with a `SKILL.md` playbook (YAML frontmatter + Markdown) and optional reference files. Nothing about it is DeepTutor-specific, so any registry that speaks the format becomes a source for your library. DeepTutor ships with **[EduHub](https://eduhub.deeptutor.info/)** — our own education-focused skill registry — wired in as the default hub.

<details>
<summary><b>EduHub — DeepTutor's skill ecosystem</b></summary>

[**EduHub**](https://eduhub.deeptutor.info/) is the community hub DeepTutor launched for sharing teaching-oriented agent skills — Socratic tutors, flashcard builders, essay feedback, exam blueprints, concept explainers, and more. It is built into DeepTutor, so there's nothing to configure: a bare slug or an `eduhub:` prefix resolves to it.

**Find and install** — in the browser, open **Learning Space → Skills → Import from EduHub** to browse the catalog and download a skill straight into your library. From the terminal:

```bash
deeptutor skill search "socratic tutor"               # search EduHub (the default hub)
deeptutor skill install socratic-tutor                # fetch → verify → register
deeptutor skill install eduhub:socratic-tutor@1.2.0   # pin a hub and a version
deeptutor skill list                                  # local skills with their hub provenance
```

**Publish your own** — package a `SKILL.md` and share it back to the community:

```bash
deeptutor skill login                                 # browser sign-in to EduHub
deeptutor skill publish ./my-skill                    # interactive: pick a track + tags, then upload
deeptutor skill update                                # roll back or release a new version
```

EduHub is also a standalone, ClawHub-compatible registry, so agents that aren't DeepTutor (Claude Code, Codex, …) can use it directly through the `eduhub` CLI — `npx eduhub install socratic-tutor`.

</details>

<details>
<summary><b>The import safety gate</b></summary>

Whatever the source, every import passes the **same safety gate** before anything touches your workspace:

- the registry's **security verdict** is checked first — flagged packages are refused unless you pass `--allow-unverified`;
- archives are extracted defensively (zip-slip / zip-bomb guards) behind a text/script **suffix whitelist**, so binaries never land in the workspace;
- frontmatter is normalized to DeepTutor's schema and `always:` is **stripped**, so a downloaded skill can never force itself into every system prompt;
- provenance — hub, version, verdict, and install time — is written to `.hub-lock.json` for audits and updates.

In multi-user deployments, installing is admin-only: a new skill lands in the admin catalog and stays invisible to other users until a grant assigns it, so an admin can vet it before rolling it out.

</details>

<details>
<summary><b>Also compatible with ClawHub</b></summary>

Because DeepTutor speaks the open Agent-Skills format, **[ClawHub](https://clawhub.ai/)** works as a first-class source too — it's built in alongside EduHub. Pick it with the hub prefix:

```bash
deeptutor skill search "git release notes" --hub clawhub
deeptutor skill install clawhub:git-release-notes@1.0.1
```

Add more registries in `settings/skill_hubs.json`: a `type: "clawhub"` entry points at any compatible HTTP API (EduHub and ClawHub both speak it), `type: "command"` wraps whatever fetch CLI a registry ships, and `"default"` chooses the hub used for bare slugs. All of them feed the same import gate.

</details>

## 🌐 Community

### 📮 Contact

DeepTutor is an open-source project led by [Bingxi Zhao](https://github.com/pancacake) within the [HKUDS](https://github.com/HKUDS) Group, and it iterates in a **fully open-source form**, built together with the community. So far, we **DO NOT** have paid online products of any form. Feel free to reach out at **bingxizhao39@gmail.com** for discussions, ideas, or collaboration.

### 🙏 Appreciation

Heartfelt thanks to [**Chao Huang**](https://sites.google.com/view/chaoh), director of the Data Intelligence Lab @ HKU, and to our HKUDS labmates for their warm support — especially [**Jiahao Zhang**](https://github.com/zzhtx258), [**Zirui Guo**](https://github.com/LarFii), and [**Xubin Ren**](https://github.com/Re-bin). We're also deeply grateful to the **open-source community**: your stars, issues, pull requests, and discussions shape DeepTutor every single day.

DeepTutor also stands on the shoulders of outstanding open-source projects that gave us both tools and inspiration:

| Project | Role / Inspiration |
|:---|:---|
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG pipeline and document-indexing backbone |
| [**nanobot**](https://github.com/HKUDS/nanobot) | Ultra-lightweight agent engine that powered the original TutorBot *(HKUDS)* |
| [**LightRAG**](https://github.com/HKUDS/LightRAG) | Simple & fast RAG *(HKUDS)* |
| [**AutoAgent**](https://github.com/HKUDS/AutoAgent) | Zero-code agent framework *(HKUDS)* |
| [**AI-Researcher**](https://github.com/HKUDS/AI-Researcher) | Automated research pipeline *(HKUDS)* |
| [**OpenClaw**](https://github.com/openclaw/openclaw) | Open agent gateway and skill ecosystem behind ClawHub |
| [**Codex**](https://github.com/openai/codex) | Agent-native coding CLI that inspired our CLI workflow |
| [**Claude Code**](https://github.com/anthropics/claude-code) | Agentic coding CLI that inspired the DeepTutor agent loop |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | AI-driven math animation generation for Math Animator |

### 🗺️ Roadmap & Contribute

We want DeepTutor to keep iterating and improving — and ultimately to become a gift we give back to the open-source community. Our [**roadmap**](https://github.com/HKUDS/DeepTutor/issues/498) is updated continuously; vote on items there or propose new ones. If you'd like to contribute, see the [**Contributing Guide**](CONTRIBUTING.md) for branching strategy, coding standards, and how to get started.

<div align="center">

We hope DeepTutor becomes a gift for the community. 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

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

Licensed under the [Apache License 2.0](LICENSE).

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
