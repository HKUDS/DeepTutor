---
title: Settings
description: The control plane for DeepTutor — appearance, network, workspace, models, parsing, video learning, agents, memory, and updates.
---

Settings is the operational control plane for DeepTutor. Most sections use a **draft-and-apply** model: you edit a draft, test it, then **Apply** — so a bad provider change never takes down a working setup. Values persist to `data/user/settings/*.json` (and a couple of YAML files) in your account.

## Where it is

Open **Settings** at the bottom of the left sidebar. Its searchable navigator opens independent pages, grouped into Personal, Learning & conversation, Models & services, Features & integrations, System, and Archived. **General** holds the two language toggles; **Runtime status** holds backend health, resident memory, and the **Readiness** matrix grading capabilities as blocker, warning, or suggestion. Optional unconfigured capabilities are not faults. **Usage statistics** shows model usage and conversation activity; **Archived chats** lets you search, restore, or delete archived conversations. Sidebar feature and history order remains a per-machine preference: drag to reorder or fold features into **More**.

![Settings and its section navigator](/screenshots/dev/settings.png)

| Section | What it controls |
| --- | --- |
| **Appearance** | Theme, learning text, and code-block appearance. |
| **Network** | The backend API base the frontend proxy uses, ports, and CORS. |
| **Workspace** | System, general, and custom workspaces, root folders, and storage migration. |
| **Models** | Providers, Language models, Task models, Embedding, Search, Voice, and Multimodal generation. |
| **Knowledge Base** | The document parsing engine. |
| **Chat** | Video Learning, tools, per-capability parameters, starting points, and attachment limits. |
| **Partners & Agents** | The ten local agent harnesses you can call from chat. |
| **Memory** | Chunking, budgets, dedup, and reference policies for the consolidator. |
| **About** | Running version, installation type, release channel, update checks, and the safe update path. |

## Choose the right scope

Use **Settings** to configure the application, services, and workspace policy. Use [Personalization](/explore/personalization/) to manage reusable personas, skills, agents, and service connections. Use the working workspace's **Home**, **Learning**, and **Resources** for conversations, study, and materials. Partners has its own account-level shelf.

Personal preferences accompany the account across workspace switches. Deployment settings such as provider infrastructure, local harness execution, and application installation may require an administrator. Changing a workspace's resource selection does not change either type of ownership.

## Workspace resources and instructions

Open **Settings → Workspace** to create or manage a workspace. Give it a useful name, configure its root folder when needed, and add instructions that describe the project or course. Those instructions accompany work in that workspace; a reusable persona remains a separate account preset.

For an existing workspace, open **Assigned resources**. Skills, MCP services, and knowledge bases each have an independent choice:

| Mode | Effect |
| --- | --- |
| **Inherit available resources** | Preserve the account's existing access rules and include newly available resources automatically |
| **Only selected resources** | Allow the checked entries only; checking none allows none of that category |

Save the selection, return to Home, and check its resource picker. Assignments are references: removing an assignment preserves the original library resource. The **Manage library** link opens the relevant catalog for editing the resource itself. If an item is marked unavailable, repair the connection, installation, or source; leaving a stale reference selected does not restore it.

The workspace policy is an upper bound. Selecting skills or MCP services in a conversation can narrow it further; clearing a conversation selection restores inheritance from the workspace. On a shared deployment, per-user grants are applied as well. The policy never reveals another account's files or credentials.

A Partner can bind an owner workspace to share its current materials. Manage those materials in the workspace's Resources; configure the Partner's identity, channels, and model from Partners. See [Partners](/explore/partners/).

## Appearance

Theme, learning text, and code blocks. The two language toggles moved to the General settings page: **Interface language** covers navigation, settings, and status text only; **Model output language** sets the default language of chat and capability responses. Five themes ship in the box: **System** (follows your device), **Default** (clean pure-white with a blue accent), **Cream** (warm, paper-like, terracotta accent), **Dark** (Cream's warmth on near-black), and **Glass** (translucent purple panels on a deep gradient). Each tile previews the theme it applies. A **Code blocks** panel sets the syntax theme, line numbers, and wrapping.

![Appearance settings](/screenshots/dev/appearance.png)

## Models

The hub for every model and service: language models, a **task model** for automatic calls and Math Animator/Video Lesson repairs, embeddings, web search, voice (TTS/STT), and generation (image/video). Each service uses profiles and a model catalog; credential edits trigger discovery for bulk model import. LLM and Task profiles offer provider-supported API formats: default URLs follow the format, while custom URLs stay unchanged. Models use automatic capability detection or overrides for tools, images, JSON, and reasoning. The **Providers** page holds one vendor credential and links it into every service that vendor serves — one key, entered once. A voice model powers read-aloud and the composer mic; image/video models become chat tools. Use **Test** before **Apply** — a green test proves the profile can make a minimal call, not that the model suits every capability.

See [Chat Workspace → Configure what Chat can use](/explore/chat-workspace/#configure-what-chat-can-use) for the Models page in context, and [Providers](/get-started/providers/) for setup recipes.

## Knowledge Base

The **document parsing** engine that converts uploads into text for knowledge bases and question generation — Text-only, MinerU, Docling, Tika, markitdown, PyMuPDF4LLM, or LiteParse. Local model downloads are **off by default**. See [Knowledge Center → Document parsing](/explore/knowledge/#document-parsing).

## Chat

Five related controls have their own settings pages:

- **Video Learning** — choose the caption provider and configure a self-hosted Invidious browsing/API origin with a connection test. Reading uses native YouTube playback; changing these settings preserves materials and progress.
- **Tools** — the built-in tools the chat agent can invoke. **Experience-enhancement** tools (`brainstorm`, `web_search`, `paper_search`, `zotero_search`, `reason`, `geogebra_analysis`, and — once the model is configured — `imagegen` / `videogen`) are yours to toggle; the rest, including retrieval and workspace execution tools, are context-gated or capability-owned and mount only when the turn permits them.
- **Capabilities** — per-capability LLM parameters and runtime knobs (temperature, token budgets, loop limits) for Chat, Solve, Question, Research, Math animator, Visualize, and Co-writer.
- **Starting points** — how much recent activity feeds the three suggestions under an empty composer.
- **Attachments** — upload size caps and extracted-text budgets for chat attachments (admin-gated).

MCP servers are **not** here any more: each account installs its own from the MCP Services store at `/space/mcp` in Personalization, or adds a remote server by URL. See [MCP Services](/ecosystem/mcp/).

![Video Learning settings](/screenshots/dev/settings-video.png)

## Configure it from Chat

Most of this page can also be reached by asking. *"Switch the interface to Chinese and use a better PDF parser"* is a sentence, and the assistant will inspect the install, apply the change, and tell you what it costs you — instantly, after a restart, or after a re-index.

This is a normal chat turn with four tools added, so a configuration question in the middle of other work does not throw away your knowledge bases or your search tool. It activates on objective signals — you picked it, your message pairs an action word with a configuration object, or this is your first conversation on an install that still has a real gap — rather than on the model's sense that configuration might be relevant.

Three rules keep it from being reckless:

- **A new model or provider is probed before it is committed.** The probe runs against a candidate configuration that never reaches disk. Without that ordering, a bad value would be written first and verified second — and the very next turn, including the one that would undo the mistake, would run on a model that cannot be reached.
- **API keys never enter the model's context.** When a change needs a credential, the assistant opens the matching form in the composer and your browser posts the key straight to the server. No setting in the writable table can even represent a secret.
- **Every knob carries its scope and its effect.** Personal settings live in your own profile; deployment-wide ones are administrator-only. That is data, not prompt etiquette, which is why the answer reliably says whether you need to restart.

It can also do the slow jobs: installing a parsing engine or fetching its model weights, following the install log inside the single call rather than leaving you to poll. Only allow-listed engine ids — never an arbitrary package name or command.

## Partners & Agents

Configure the **local agent harnesses you can call on in chat** — Claude Code, Codex, Grok CLI, Antigravity CLI, Kimi CLI, opencode, MiMo Code, Hermes Agent, OpenClaw, and DeepSeek Harness, plus a remote Hermes connection. Each local block reports whether the command exists on this machine, offers model-list sync where supported, and exposes that harness's unattended-run parameters. See [My Agents](/explore/subagents/).

![Partners and agents settings](/screenshots/dev/settings-agents.png)

## Memory

Tunes the chunk-based consolidator: LLM-round budgets per L2 surface and L3 slot for **Update** and **Audit**, plus **Dedup** iterations. See [Memory → Tuning the consolidator](/explore/memory/#tuning-the-consolidator).

## About and updates

The sidebar version badge links to **About** and carries an update-state dot. About identifies the running version, install type, stable release channel, latest published release, and release notes. Checks are cached for 24 hours and can be disabled for offline or controlled deployments; DeepTutor never starts an install without confirmation.

Automatic **Update and restart** is offered only for a regular PyPI install inside the active virtual environment and when DeepTutor owns the launcher process. Active conversations must finish before the updater can start; it then hands off to a worker, upgrades the package, and reconnects to the same data directory. Source checkouts stay in Git, Docker deployments update their image, and unknown or direct-artifact installs receive a manual path instead.

![About and installation information](/screenshots/dev/settings-about.png)

## Deployment notes

- Project-root `.env` is intentionally ignored as application config.
- Runtime settings live under `data/user/settings/` unless you set `DEEPTUTOR_HOME` or `deeptutor start --home`.
- Docker browsers use the frontend origin; its proxy reaches the backend. Split deployments set that backend target in **Network**.

## See also

- [Providers](/get-started/providers/) — model and search setup recipes
- [DeepTutor Ecosystem](/ecosystem/) — Skills, MCP Services, and CLI Apps managed from Personalization
- [Docker](/get-started/docker/) — port and reverse-proxy notes
- [Memory](/explore/memory/) · [Knowledge Center](/explore/knowledge/) · [My Agents](/explore/subagents/)
