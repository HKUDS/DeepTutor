# 🚀 DeepTutor v1.0.0-beta1 Release Notes

**Release Date:** 2026.04.04

We're thrilled to announce **DeepTutor v1.0.0-beta1** — the first beta of the **DeepTutor 2.0** architecture. This is a ground-up rewrite that transforms DeepTutor from a monolithic RAG tutor into an **agent-native learning platform** with a two-layer plugin model (Tools + Capabilities), three unified entry points (CLI / WebSocket / Python SDK), and a completely rebuilt web application shell.

> ⚠️ **Beta Notice:** This is **beta 1** of v1.0.0. The core architecture is stable, but some **UI interactions and edge-case workflows may still contain bugs**. We appreciate your patience and welcome bug reports via [Issues](https://github.com/HKUDS/DeepTutor/issues).

> 📌 **Knowledge Base Note:** In this release, the RAG pipeline has been **simplified to LlamaIndex only**. LightRAG and RAG-Anything pipelines along with their related knowledge base content have been **temporarily removed** to focus on stability. They will be re-introduced in upcoming releases.

> [!TIP]
> **Call for Feedback:** If you encounter any bugs or have feature requests, please [open an issue](https://github.com/HKUDS/DeepTutor/issues)! PRs are welcome — see our [Contributing Guide](https://github.com/HKUDS/DeepTutor/blob/main/CONTRIBUTING.md).

**Diff Scope:** `main...dev` (903 files changed, 92,701 insertions, 73,749 deletions)

---

## Quick Summary

- **Architecture** — Complete rewrite from `src/` to `deeptutor/` + `deeptutor_cli/` with agent-native runtime (Tools + Capabilities).
- **Entry Points** — Three unified entry points: standalone CLI (`deeptutor`), WebSocket API (`/api/v1/ws`), and Python SDK facade.
- **Capabilities** — Five built-in capabilities: `chat`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`.
- **Tools** — Seven LLM-callable tools: `rag`, `web_search`, `code_execution`, `reason`, `brainstorm`, `paper_search`, `geogebra_analysis`.
- **Web App** — Rebuilt Next.js app with workspace/utility route groups, new Playground, Co-Writer, Agents, and Guide pages.
- **TutorBot** — Multi-channel bot agent supporting 12 messaging platforms.
- **Infra** — SQLite-backed session persistence, turn runtime, provider-level LLM traffic control and telemetry.

---

## ✨ Highlights

### 🏗️ Agent-Native Runtime (Tools + Capabilities)

Introduced a two-layer plugin model that decouples tool execution from high-level agent workflows:

- **Core Contracts:** `ToolProtocol`, `CapabilityProtocol`, `UnifiedContext`, `StreamEvent`, and `StreamBus` — the foundation of all runtime execution.
- **ChatOrchestrator:** Central coordinator with two registries:
  - `ToolRegistry` — tool discovery, OpenAI-style schema export, and execution.
  - `CapabilityRegistry` — capability routing, manifest management, and stage-aware streaming.

### 🖥️ Unified Entry Points: CLI / WebSocket / Python SDK

Three entry points share a single `ChatOrchestrator` runtime:

| Entry Point | Description |
|:---|:---|
| **CLI** (`deeptutor`) | Typer-based CLI with sub-commands: `run`, `chat`, `bot`, `kb`, `memory`, `session`, `notebook`, `plugin`, `config`, `provider`, `serve` |
| **WebSocket** (`/api/v1/ws`) | Unified endpoint with turn lifecycle: `start_turn`, `subscribe_turn`, `subscribe_session`, `resume_from`, `cancel_turn` |
| **Python SDK** (`deeptutor.app.facade`) | Programmatic facade for SDK-style integrations |

### 🧠 Capability Layer

Five built-in capabilities, each a multi-step agent pipeline:

| Capability | Stages | Description |
|:---|:---|:---|
| `chat` | responding | Default tool-augmented conversation |
| `deep_solve` | planning → reasoning → writing | Multi-stage problem solving |
| `deep_question` | ideation → evaluation → generation → validation | Intelligent question generation with follow-up mode |
| `deep_research` | search → analyze → synthesize → report | Multi-agent research with report generation |
| `math_animator` | analysis → design → codegen → review → render | Manim-based math concept video generation |

### 🔧 Tooling System

Seven unified LLM-callable tools with bilingual prompt hints (en/zh):

| Tool | Description |
|:---|:---|
| `rag` | Knowledge base retrieval via LlamaIndex |
| `web_search` | 10 search providers: Tavily, Exa, Jina, Serper, Perplexity, Brave, Baidu, SearXNG, DuckDuckGo, OpenRouter |
| `code_execution` | Sandboxed Python execution with AST-based safety guards |
| `reason` | Dedicated deep-reasoning LLM call |
| `brainstorm` | Breadth-first idea exploration with structured rationale |
| `paper_search` | arXiv academic paper search |

### 🤖 TutorBot — Multi-Channel Bot Agent

New autonomous bot system (`deeptutor/tutorbot/`) that brings DeepTutor to messaging platforms:

- **12 Channels:** Telegram, Discord, Slack, WeChat Work (WeCom), Feishu, DingTalk, WhatsApp, Matrix, QQ, Email, MoChat
- **Agent Loop:** Tool-augmented LLM loop with memory, subagent spawning, and team collaboration
- **Built-in Tools:** Shell, filesystem, web, MCP, cron, and message tools
- **Background Services:** Heartbeat health checks and cron-based scheduled tasks

### 🌐 Web Application Restructure

Complete rebuild of the Next.js frontend with new route groups:

**Workspace Routes (`(workspace)/`):**

| Page | Description |
|:---|:---|
| **Home** (`/`) | Main chat interface with tool-augmented conversation |
| **Guide** (`/guide`) | Interactive learning guide with session history, progress tracking, and completion summaries |
| **Playground** (`/playground`) | Unified deep capability UI (deep_solve, deep_question, deep_research, math_animator) |
| **Co-Writer** (`/co-writer`) | AI-assisted collaborative writing with edit and narrator agents |
| **Agents** (`/agents`) | TutorBot management — create, configure, and chat with custom bots |

**Utility Routes (`(utility)/`):**

| Page | Description |
|:---|:---|
| **Knowledge** (`/knowledge`) | Knowledge base management with LlamaIndex pipeline |
| **Memory** (`/memory`) | User memory and preference management |
| **Settings** (`/settings`) | Unified configuration for LLM, Embedding, TTS, and Search services |

### 🏭 Service Infrastructure Rebuild

Refactored services into clearer domains:

```
deeptutor/services/
├── config/       # Environment store, model catalog, provider runtime
├── llm/          # Multi-provider LLM: factory, registry, traffic control, telemetry
├── embedding/    # Adapter-based: OpenAI-compatible, Cohere, Jina, Ollama
├── rag/          # LlamaIndex pipeline with component-based architecture
├── search/       # 10 web search providers with result consolidation
├── session/      # SQLite store, turn runtime, context builder
├── memory/       # User memory persistence
├── notebook/     # Notebook management
├── prompt/       # Bilingual prompt template manager (en/zh)
├── settings/     # Interface settings
├── setup/        # Application initialization
├── tutorbot/     # TutorBot management
└── path_service  # Centralized data path resolution
```

### 🔒 Security & Stability

- **Code Execution Safety:** AST-based import/call guards with configurable allowlists.
- **LLM Traffic Control:** Provider-level circuit breaker, error rate tracking, and retry mechanisms.
- **Startup Validation:** Capability-to-tool consistency checks at boot time.

### 🧪 Test Coverage

53+ new test files across all major layers: runtime (tool/capability registry, orchestrator), services (LLM provider/factory/routing/telemetry, RAG pipeline, embedding, search, session, memory, notebook, config), agents (chat, solve, question, math_animator), API (knowledge, memory, solve, WebSocket turn runtime), CLI, and tools (code executor safety).

---

## ⚠️ Breaking Changes

- **Package layout:** `src/` → `deeptutor/` + `deeptutor_cli/`. Old `src/` directory fully removed (140 files).
- **Package renamed:** `ai-tutor` → `deeptutor`, version `1.0.0`.
- **Runtime model:** Capability-native orchestration. `chat` is the default; deep modes selected explicitly via `run` command or WebSocket.
- **Web routes:** All pages reorganized under `(workspace)/` and `(utility)/`. Legacy pages (`/solver`, `/question`, `/research`, `/ideagen`, `/notebook`, `/history`) removed.
- **RAG pipeline:** Only LlamaIndex available. LightRAG and RAG-Anything temporarily removed.
- **Data layout:** Runtime data centered under `data/user/workspace/...`.
- **Dependencies:** Split into layered requirements: `cli.txt`, `server.txt`, `dev.txt`, `math-animator.txt`, and the channel dependency mirror.

---

## 📦 What's Changed

- Complete codebase rewrite with agent-native architecture (DeepTutor 2.0).
- Two-layer plugin model (Tools + Capabilities) with `ChatOrchestrator` coordinator.
- Standalone CLI package (`deeptutor_cli/`) with 11 sub-commands via Typer.
- Unified WebSocket endpoint with turn lifecycle and session streaming.
- 5 built-in capabilities and 7 LLM-callable tools with bilingual prompt hints.
- TutorBot multi-channel bot agent with 12 platform integrations.
- Rebuilt web app with workspace/utility route groups and new Playground, Co-Writer, Agents, and Guide pages.
- Service infrastructure rebuild: LLM provider registry, embedding adapters, SQLite session store, memory, notebook, and search consolidation.
- AST-based code execution safety, LLM traffic control, and provider telemetry.
- 53+ test files across runtime, services, agents, API, CLI, and tools.
- Updated Docker configuration and layered dependency management.

**Full Changelog**: https://github.com/HKUDS/DeepTutor/compare/v0.6.0...v1.0.0-beta1
