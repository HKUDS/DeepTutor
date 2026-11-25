---
title: Chat
description: "Send one useful chat turn: pick the workspace, attach material, and read the result in Activity."
quadrant: how-to
---

Home is where a turn runs. This page is how to send a useful one. For how a turn plans, calls tools, and stops, see [How the agent loop works](/learning-workspace/agent-loop/).

## Where it is

Select your [workspace](/learning-workspace/workspaces/), then open **Home → Chat** (`/chat`). Home also contains the [Task Board](/learning-workspace/task-board/), [Learning notebook](/learning-workspace/notebook/) and [Calendar](/learning-workspace/calendar/). Chat, tasks and notebook pages follow the workspace; Calendar events are account level, with workspace study layers.

![Home and the conversation composer](/screenshots/dev/overview.png)

The window has three regions:

| Region | What it does |
| --- | --- |
| **Left sidebar** | The workspace menu sits above **Home**, **Learning** and **Resources**. **Partners** and **Personalization** are account-level areas. Conversations reopen with their learning context; Settings and workspace management are available from the workspace menu. Classic layout uses a different navigation arrangement. |
| **Composer** | The message box. Its **bottom-left** sets *what kind of turn* this is (capability) and adds references (`+`); its **bottom-right** exposes connected-agent, knowledge, persona, and model selectors. The microphone only transcribes the current message. |
| **Activity panel** (top-right toggle) | Tool calls, references, generated files, attachments, and previews for the current session, plus a quick way to open a URL or local file. |

With authentication enabled, signed-in users also see **My profile** in the sidebar. It shows the username (not editable here), role, and join date; use it to upload an avatar image or choose an icon and color, and to sign out.

The top-right icons above the thread let you **save useful content to Favorites**, **export the session as Markdown**, and **toggle the Activity panel**.

## Your first useful conversation

1. Select the workspace for your project and open a new Chat.
2. Add a PDF or a specific saved reference with the resource control; attach a knowledge base when you need retrieval across its library.
3. State the outcome and constraints: “Explain the sampling theorem using this lecture, then give me two questions. Let me try before showing answers.”
4. Follow tool progress in Activity and open cited sources or generated files when you need to inspect the evidence.
5. Save a useful result to [Favorites](/learning-workspace/favorites/), or develop your own explanation in the [Learning notebook](/learning-workspace/notebook/). Reopen the conversation from Resources → Chat History.

Selecting a connected agent is by default a persistent choice for the session; importing an old agent transcript is a reference. Likewise, an attached file supplies this turn's material by default, while workspace instructions and session preferences shape later turns. Check the visible chips before sending if a reply seems to be using the wrong sources or persona.

## Starting points

Under the empty composer, Explain, Solve, Practice, Plan, and Research offer editable starting prompts. A separate personalized suggestion draws on your memory and recent activities; **Suggest something else** replaces it. Choose either to fill the composer, then review before sending. **Customize page → Starting prompts** edits the reusable titles and requests.

**Settings → Conversation** sets how much history feeds them: raise the activity count for suggestions that range wider, lower it to keep them close to what you were just doing.


## Sticky context vs. one-time references

DeepTutor splits context into two kinds, and the composer keeps them in two different places — this is the single most important idea to learn here.

**Sticky session context** persists across turns until you change it: capability, workspace or course binding, tools, **knowledge bases**, **persona**, **model**, and Reading / Mastery state. The right side exposes the relevant selectors; an agent selected with the Agent chip or `@` stays attached by default, while the microphone only fills the current draft.

**References** live behind the **`+` button** on the left. They default to *this* turn only; use the reuse control to reuse a supported reference on every turn.


| `+` reference | What it pulls in |
| --- | --- |
| **Attach files** | A PDF, image, Office doc, Markdown, or data file for the agent to read. |
| **Chat History** | A past session as grounding context. |
| **My Agents** | An imported Claude Code / Codex / ChatGPT transcript to explore — see [My Agents](/customize/agents/). |
| **Books / Reading / Notebooks / Question Bank** | A compiled book, a reading section, a saved notebook, or practice questions from your [Resources](/learning-workspace/resources/). Filter questions by material or category; **Select all** keeps earlier selections. |
| **Memory** | A specific memory document, when you want the agent to work from a fact you can point at rather than whatever recall surfaces. |

Typing **`@`** in the main Chat composer filters the same connected-agent list as the Agent chip and keeps the selection attached by default. Follow-up surfaces without live-agent selection use `@` for their Space reference menu instead.

### Knowledge — ground answers in your library

The **database icon** opens the knowledge picker. Untouched conversations inherit ready workspace assignments or the default KB; explicit selections, including none, persist until changed. The agent retrieves from these bases when grounding is needed.

How it retrieves depends on the base's engine, and the difference is worth knowing when an answer surprises you. Most bases — LlamaIndex, GraphRAG, LightRAG, a linked index, a remote LightRAG Server, a Tencent IMA library — are served by the `rag` tool. **PageIndex OSS** and **PageIndex Cloud** are not: their retrieval is agentic, so a reading loop walks the local or hosted document tree instead, and those bases are deliberately absent from `rag`'s list. An **Obsidian** vault has no index at all and is routed to the Obsidian capability, which navigates the live files; a **MarginNote 4** library is the same shape, walked by its own tools.


### Persona — set the voice and stance

The **person icon** chooses a persona. `Default` is the plain assistant; built-ins like **peer**, **research-assistant**, and **teacher** change tone and pedagogy. Personas are managed under **Personalization → Personas** and can be reused by Partners.


### Model — switch per turn

The **model chip** picks which model runs this turn. Every model you configured in Settings appears here with its provider and context window, and the default is marked. Switch to a long-context model for big documents, or a cheaper/faster one for quick exchanges — mid-session, without losing your place.


## The Activity panel

The panel toggle (top-right) opens **Activity** — a live record of the tools, references, and files the current session has used — generated files listed above your uploads — plus an **Open** box to pull a URL or a local file into the in-app viewer.

![Conversation and its activity controls](/screenshots/dev/chat.png)

As a turn runs, each tool call collapses into a compact header (for example, `Done · 21s`) that you can expand to inspect inputs and outputs — so the thread stays readable while the full trace stays auditable.

## The content workspace

The **content workspace** is the folder bound to a conversation. Unbound sessions use the General workspace; you can create custom workspaces for separate projects. The System workspace holds shared skills and sanitized configuration snapshots; private runtime settings, API keys, databases, and memory stay outside conversational file access.

Manage roots, workspaces, and **Workspace instructions** in **Settings → Workspace**. Instructions apply from the next turn for supported capabilities, excluding Deep Research, Quiz, and Manim; capability rules and permissions still apply. Built-in and managed custom folders live under `<runtime-home>/data/user/workspaces` by default. The CLI also manages the legacy content-folder binding:

```bash
deeptutor workspace show
deeptutor workspace set /absolute/path/to/my-folder
deeptutor workspace reset
```

Reading is free; writing is not. Everything a turn creates — downloads, generated files, code output, rendered assets — lands under a turn-scoped `outputs/<capability>/<session>/<turn>/` directory. Execution is read-only everywhere else in the folder, and copying a generated file out of `outputs/` into the rest of your material takes an explicit **Allow once** confirmation naming that exact source and destination.

The model never sees an absolute path — only relative ones such as `outputs/report.docx`. When it calls `workspace_present`, the UI renders an authenticated, openable snapshot; the same relative path also works in an ordinary Markdown link or image. Changing the source file later does not change a snapshot already presented.

On Docker and server deployments the deployment folder constrains managed workspace storage — see [Docker](/get-started/docker/).

## On a phone

Below tablet width the workspace collapses to a single column with a slide-over sidebar, so the same thread is usable on a phone rather than rendering a three-pane desktop layout off the edge of the viewport.

## Practical examples

```text
Attach a KB + ask: "Explain chapter 4 and quiz me on the weak spots."
```

```text
Attach a PDF + ask: "Extract the assumptions and save the final summary to my notebook."
```

```bash
deeptutor run chat "Explain the Fourier transform" --kb signals
deeptutor chat --capability deep_research --kb papers
```

## See also

- [Immersive Reading](/learning-workspace/reading/) — the same loop, with documents or media open beside it
- [DeepTutor Ecosystem](/customize/) — Skills, MCP Services, and CLI Apps the agent can call
- [Partners](/channels/) — the same loop, running inside IM companions
- [My Agents](/customize/agents/) — consult Claude Code, Codex, or a Partner from a chat turn
- [Knowledge Center](/learning-workspace/knowledge/) — build the RAG libraries you attach here
- [Memory](/learning-workspace/memory/) — the personalization the loop reads and writes
- [Settings](/self-hosting/settings/) — models, tools, capabilities, and runtime control
- [How the agent loop works](/learning-workspace/agent-loop/)
- [Vision Solver](/learning-workspace/vision-solver/)
- [Research](/learning-workspace/research/)
- [Multimodal studio](/multimodal-studio/)
