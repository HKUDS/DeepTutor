---
title: My Agents
description: "My Agents — consult a named local harness, configured ACP agent, remote Hermes gateway, or a Partner from a chat turn, and import Claude Code, Codex, or ChatGPT conversations as named, resumable agents."
quadrant: how-to
---

**My Agents** turns other agents into context for DeepTutor. It does two distinct things: it lets you **consult a live agent** (a supported local harness or configured ACP agent, a remote Hermes gateway, or one of your Partners) from inside a chat turn, and it lets you **import Claude Code, Codex, or ChatGPT history** as named, searchable, resumable agents.

## Where it is

Open **My Agents** in the left sidebar. From a chat turn you can also reach the live agents two ways: the **Agent chip** in the composer toolbar (the robot icon), or by typing **`@`** in the message box.

![My Agents](/screenshots/dev/agents.png)

The page has two sections that mirror the two ideas.

## Account connections, workspace use

Open this library through **Personalization → My Agents**. Connections belong to the account and remain available as you move between workspaces. The workspace's **Home** is where you select one for a live consult; imported transcripts are reference material you choose for the task.

A connection is not the same as access to the working workspace's files. A local harness runs on the server machine with its configured working directory and host credentials; switching DeepTutor workspaces does not retarget that directory. Check it when connecting a project agent. A Partner uses its own configured resource mode and private session continuity, even when Home consults it from another workspace.

For a course project, you might keep lecture files in Resources, consult a coding agent from Home about a program, and return to Learning for structured practice. Include the specific question and permitted evidence the consult needs. Importing old agent history helps recover an earlier decision; running a connected agent obtains a fresh answer.

## Connected agents — consult a live agent

A **connected agent** is a real agent DeepTutor can talk to in real time. Press **Connect agent** and pick one of:

- an agent harness on this machine — **Claude Code**, **Codex**, **Grok CLI**, **Antigravity CLI**, **Kimi CLI**, **opencode**, **MiMo Code**, **Hermes Agent**, **OpenClaw**, **DeepSeek Harness**, or a configured **ACP** agent,
- a configured **remote Hermes gateway** (**Hermes Agent (remote)**), or
- one of your **Partners**.

When you consult a connected agent, DeepTutor does not paste a transcript — it actually *runs* the other agent and streams its work back. Under the hood a connected agent is a third kind of context source with one exclusive power: the chat loop's `consult_subagent` tool drives the agent over multiple rounds and shows its full run live in the Activity panel.

### Consulting from chat

Select the agent with the **Agent chip**, then set **Max rounds DeepTutor may ask** — the ceiling on how many back-and-forth rounds the consult may take.


Type **`@`** to filter the same connected agents; either selector persists until cleared or replaced.


### What a live consult looks like

Consult a **Claude Code** agent and it runs against its own working directory — reading files, grepping, and reasoning over the real repository. Its tool calls stream into the Activity panel while DeepTutor folds the conclusion back into your answer.

Consult a **Partner** and DeepTutor sends the question into that Partner's own session — so the Partner answers with its soul, its library, its private memory tools (`partner_search`, `partner_read`), and its skills (`read_skill`). One chat thread stays bound to one Partner session, so follow-ups continue the same conversation.

## Imported conversations — agents from your history

The second half of the page imports your existing **Claude Code, Codex, and ChatGPT conversations** and presents each source as a **named agent** you can search, open, keep chatting with, or reference from chat.

Press **Import conversations** to bring in history. For a local folder, name it and choose a scope: **Claude Code by project / working directory**, or **Codex by calendar date**; Refresh re-syncs that scope. A ChatGPT `conversations.json` export is a one-time snapshot that re-imports without duplicates. You decide which slice of history becomes DeepTutor context.


Imported agents show their source, conversation count, and last sync time. From there you can:

- **Open a conversation** to keep chatting with it inside DeepTutor.
- **Refresh** an agent to pull in new conversations from its selected dates or projects.
- **Reference** an imported conversation in any chat turn via **`+` → My Agents** — DeepTutor reads it as a third-party transcript (it stays "their" conversation, not DeepTutor's own voice).

## How the two halves differ

| | Connected agents | Imported conversations |
| --- | --- | --- |
| **What it is** | A live agent DeepTutor runs and talks to | A read-only history brought in as a named agent |
| **Source** | Ten named local harnesses (Claude Code / Codex / Grok / Antigravity / Kimi / opencode / MiMo / Hermes / OpenClaw / DeepSeek Harness), a configured ACP agent, remote Hermes, or a Partner | Past Claude Code / Codex sessions, or a ChatGPT export |
| **In chat** | Select via the Agent chip or `@`; runs stream live and the selection persists | Reference via `+` → My Agents, or open to continue |
| **Freshness** | Real-time, every consult | Snapshot; **Refresh** re-syncs selected dates or projects |

## See also

- [Home](/learning-workspace/chat/) — where you consult and reference agents
- [Partners](/channels/) — connect a Partner as a consultable agent
- [Memory](/learning-workspace/memory/) — how imported context is kept separable from DeepTutor's own voice
