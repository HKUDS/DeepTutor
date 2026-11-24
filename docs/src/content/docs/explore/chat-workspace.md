---
title: Chat
description: "The default DeepTutor agent loop — capabilities, session context, reusable references, tools, the Activity panel, and the models behind it all."
quadrant: how-to
---

Home is the heart of DeepTutor. It is not a plain message box: it is the **default agent loop** that can call tools, read your sources, search knowledge bases, write notes, generate images, consult other agents, ask you clarifying questions, and switch into deeper capabilities — all inside one thread.

## Where it is

Select your [workspace](/explore/workspaces/), then open **Home → Chat** (`/chat`). Home also contains the [Task Board](/explore/task-board/), [Learning notebook](/explore/co-writer/) and [Calendar](/explore/calendar/). Chat, tasks and notebook pages follow the workspace; Calendar events are account level, with workspace study layers.

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
5. Save a useful result to [Favorites](/explore/favorites/), or develop your own explanation in the [Learning notebook](/explore/co-writer/). Reopen the conversation from Resources → Chat History.

Selecting a connected agent is by default a persistent choice for the session; importing an old agent transcript is a reference. Likewise, an attached file supplies this turn's material by default, while workspace instructions and session preferences shape later turns. Check the visible chips before sending if a reply seems to be using the wrong sources or persona.

## Starting points

Under the empty composer, Explain, Solve, Practice, Plan, and Research offer editable starting prompts. A separate personalized suggestion draws on your memory and recent activities; **Suggest something else** replaces it. Choose either to fill the composer, then review before sending. **Customize page → Starting prompts** edits the reusable titles and requests.

**Settings → Conversation** sets how much history feeds them: raise the activity count for suggestions that range wider, lower it to keep them close to what you were just doing.


## The agent loop (how it thinks)

DeepTutor Chat runs a single agent loop, so one message can take several internal rounds before you see an answer:

1. The model reads your message and the mounted context, then either answers directly or plans a tool call.
2. If tools are needed, DeepTutor dispatches them and appends the observations (you can watch this in the Activity panel).
3. The model continues with better evidence — reading a source, querying a KB, running code, fetching a URL.
4. A final, tool-free message ends the turn.

`ask_user` is special: instead of guessing, the agent can **pause the turn**, ask you a structured clarifying question, and resume once you answer.

## Choosing a capability

The selector at the bottom-left of the composer (the Modern layout labels the default **Auto**; Classic calls it **Chat**) decides which capability handles the turn. Capabilities share orchestration and session context; some reuse Chat's loop, while others run a purpose-built pipeline.

The capability menu offers dedicated modes including **Ask Questions**, **Quiz**, **Visualize**, and **Video Lesson**; **Research** and **Solve** sit behind the *More Capabilities* flyout. **Mastery Path** and **Immersive Reading** are learning activities under **Learning**, alongside Books and Practice. The grouping is presentation only, not a statement about how any mode runs internally.

| Capability | Use it for |
| --- | --- |
| **Chat** | Flexible conversation with any tool — open-ended Q&A, lightweight tool use, the everyday default. |
| **Ask Questions** | Start with a context-aware clarification card, then complete the original request using your answers. |
| **Quiz** | Auto-validated question generation: practice sets, mimic-an-exam workflows, quizzes from your sources. |
| **Visualize** | Charts, diagrams, interactive HTML, SVG, Mermaid, and Manim — selected from an extensible visualizer catalog. |
| **Video Lesson** | Generate a browser-played lesson with captions and optional narration from the configured Text-to-Speech provider or Edge; the backend needs Node.js 22+ and npm. |
| **Immersive Reading** (learning activity) | Documents, audio, and video with source-grounded tutoring; media transcripts use timestamps. |
| **Research** (under *More Capabilities*) | Comprehensive multi-agent research: subtopic decomposition, RAG / web / arXiv retrieval, cited reports. |
| **Solve** (under *More Capabilities*) | Multi-step reasoning and problem solving with verification and worked solutions. |


Video learning now opens in **Immersive Reading** collections, alongside documents and audio. YouTube playback uses the native player; Settings selects caption sources and configures optional Invidious browsing. The companion cites transcript timestamps and cannot see video frames. Without a transcript, playback remains available. Reopening a legacy Watching session migrates retained material and notes into Reading; if material is missing, the conversation remains available as Chat.


Visualize now reads its render modes from a catalog. SVG, Mermaid, Mermaid mind maps, Chart.js, interactive HTML, Manim animation, and Manim storyboard are core types; GeoGebra is a bundled optional install. You can also import a visualizer ZIP containing `visualizer.json` and browser assets. Imported renderers run in a sandboxed iframe, contain no backend Python, and can be enabled, disabled, or removed per user.


### Little Tutor — follow up on a selection

Select text in a conversation and open **Little Tutor** to start an independent, source-grounded sidebar thread. It stays nested under the source conversation and keeps its own focused context without global memory or general-purpose tools, so a close reading does not derail the main thread.

## Sticky context vs. one-time references

DeepTutor splits context into two kinds, and the composer keeps them in two different places — this is the single most important idea to learn here.

**Sticky session context** persists across turns until you change it: capability, workspace or course binding, tools, **knowledge bases**, **persona**, **model**, and Reading / Mastery state. The right side exposes the relevant selectors; an agent selected with the Agent chip or `@` stays attached by default, while the microphone only fills the current draft.

**References** live behind the **`+` button** on the left. They default to *this* turn only; use the reuse control to reuse a supported reference on every turn.


| `+` reference | What it pulls in |
| --- | --- |
| **Attach files** | A PDF, image, Office doc, Markdown, or data file for the agent to read. |
| **Chat History** | A past session as grounding context. |
| **My Agents** | An imported Claude Code / Codex / ChatGPT transcript to explore — see [My Agents](/explore/subagents/). |
| **Books / Reading / Notebooks / Question Bank** | A compiled book, a reading section, a saved notebook, or practice questions from your [Resources](/explore/space/). Filter questions by material or category; **Select all** keeps earlier selections. |
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

## Knowing how full the window is

A chip in the composer reports how much of the model's context window this turn actually used and what is filling it — prompt blocks, tool schemas, the message list. It is measured from the assembled prompt rather than re-derived afterwards, so the readout cannot drift from what was sent. Open it to see the breakdown before deciding whether to switch to a longer-context model or start a fresh session.

Long conversations also grow a rail of ticks in the transcript's left gutter, one per question you asked, for jumping back without scrolling.

## Tools — including generation

Tools come in three kinds, and the split is about who decides.

**You decide** for the experience-enhancement tools in **Settings → Tools**: `brainstorm`, `web_search`, `paper_search`, `zotero_search`, `reason`, and `geogebra_analysis` — plus `imagegen` and `videogen` once you configure the matching generation model.

**Context decides** for the rest, which mount automatically when they are useful and are locked on from the composer's point of view: `rag`, `kb_files`, `knowledge_frontier`, `read_source`, `read_memory`, `write_memory`, `read_skill`, `list_favorites`, `save_favorite`, `question_bank`, `web_fetch`, `github`, `preprint`, `research_audit`, `research_lit`, `learning_status`, `learning_update`, `ask_user`, `load_tools`, `cron`, `mastery_topics`, `mastery_sessions`, `mastery_open_session`, `mastery_new_session`, and the single code path `exec` (python, c, cpp, or shell). A capability adds its own on top: the eight reading tools, the mastery tutoring tools, `consult_subagent`, and so on. A third group answers to neither: the workspace baseline includes file tools plus `write_note` and `search_notes`, while `workspace_export` needs your approval to move a file out of `outputs/`. (Partners are the exception: a companion can be denied context-gated tools individually — see [Partners](/explore/partners/).)

### Scheduling something for later

`cron` lets a turn schedule work instead of doing it now: **at** a time, **every** N seconds, or on a **cron expression** with a timezone. When the job is due, its message runs as a new instruction **in this same conversation** and the reply lands here — so "quiz me on this chapter every weekday at 9" is a sentence, not a setup screen. The same tool lists this conversation's jobs and cancels one. For a Partner, a due job rides back out through the IM channel the partner is connected to.

Configure an **Image Generation** (or Video Generation) model in Settings and it becomes a chat tool too — ask in plain language and the agent calls it, then previews the result inline with a downloadable file.

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

## Configure what Chat can use

Everything in the composer toolbar resolves to configuration in **Settings**.

**Settings → Models & services** is where the models live: LLM, Task Models, Embedding, Search, Text-to-Speech, Speech-to-Text, Image Generation, and Video Generation. **Task Models** handles titles, suggestions, and reading helpers, with overrides per task; TTS powers read-aloud, STT powers the microphone, and image/video models become chat tools.

![Provider connections in Settings](/screenshots/dev/providers.png)

Separate **Settings** pages provide five controls: **Video Learning** (caption sources and optional Invidious browsing settings), **Tools**, **Capabilities** (per-capability LLM parameters and runtime knobs), **Starting points**, and **Attachments** (upload caps and extraction budgets). MCP services and CLI Apps live in account-level Personalization; see [DeepTutor Ecosystem](/ecosystem/).


See [Settings](/explore/settings/) for the full control plane.

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

- [Immersive Reading](/explore/reading/) — the same loop, with documents or media open beside it
- [DeepTutor Ecosystem](/ecosystem/) — Skills, MCP Services, and CLI Apps the agent can call
- [Partners](/explore/partners/) — the same loop, running inside IM companions
- [My Agents](/explore/subagents/) — consult Claude Code, Codex, or a Partner from a chat turn
- [Knowledge Center](/explore/knowledge/) — build the RAG libraries you attach here
- [Memory](/explore/memory/) — the personalization the loop reads and writes
- [Settings](/explore/settings/) — models, tools, capabilities, and runtime control
