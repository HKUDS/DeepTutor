---
title: Partners
description: Persistent IM-connected companions that run on the same chat agent loop as DeepTutor Chat — with their own soul, library, memory, and channels.
quadrant: how-to
---

Partners are persistent companions with their own identity, soul, model policy, library, memory, and channel configuration. They are not a separate bot engine: every inbound message — from the web or from an IM app — is routed through the **same** `ChatOrchestrator → AgenticChatPipeline` loop that powers [Home](/explore/chat-workspace/). A Partner is "a chat that has a personality and a phone number."

## Where it is

Open the account-level **Partners** entry in the left sidebar. The page lists the companions you own and any that an admin assigned to you, with their avatar, status, description, and connected channels. It also shows your Partner Groups and a **New partner** button.

![Partners library](/screenshots/dev/partners.png)

## Account companions and workspace resources

**Partners belongs to your account.** The same companions and Partner Groups appear as you switch workspaces. A Partner's identity, channels, and relationship history therefore do not disappear when you move from a course to a research project.

For resources, choose one of two arrangements in **Configure → Workspace**:

| Arrangement | What the Partner uses | When to choose it |
| --- | --- | --- |
| **Partner private workspace** | Its own library; assign knowledge bases, skills, and Favorites collections as copies | A stable specialist companion whose materials should evolve separately |
| **An existing workspace** | That workspace's current files, knowledge bases, skills, and Favorites collections; generated files go to its outputs folder | A project or course companion that should stay synchronized with your work |

The workspace picker lists workspaces belonging to the Partner's owner. Binding one does not transfer ownership or grant access to another user's resources. Resource choices and the owner's model/tool grants still constrain the turn. Changing the binding applies from the next message; it does not move previous conversations into Home.

In private mode, ordinary KBs, skills, and Favorites collections are copied when assigned. Editing the original later does not update the copy. Connected knowledge bases have no folder to copy, so supported connections retain a live source pointer instead. In bound mode, manage shared materials in that workspace's **Resources** and use **Learning** to study the same source collection; you do not also copy a private Library onto the Partner.

The Partner retains its own soul and relationship state in both modes. Channel runtime state lives under `data/partners/<id>/channels/<channel>/`. For an authenticated non-admin user, conversation history and relationship memory are private per user under `users/<user_id>/`; the Partner can also read that user's own shared memory. Admin and unattributed channel turns use the Partner's top-level history and memory as a fallback. Sharing materials does not merge these private relationships.

## Ownership and shared access

Partners are no longer admin-only resources. Any authenticated user can create one and becomes its owner; the owner and admins can configure its soul, library, channels, tools, models, and lifecycle. An admin can assign a Partner to other users, who may chat with it without seeing or changing its wiring.

That split matters when a Partner is shared: identity and knowledge assets stay consistent, while each human keeps private sessions and relationship memory. An external IM account can join the same private scope after the user links it with `/link <code>` in a direct message.

## Create a partner

Press **New partner** and complete the wizard:

1. **Identity** — name, avatar, description, and default reply language.
2. **Soul** — the partner's role and communication style. This becomes its `SOUL.md`.
3. **Mind** — model selection, enabled system tools, MCP tools, and delivery preferences.
4. **Library** — choose a private workspace and copy permitted assets, or bind an existing workspace for live shared resources. Private copying excludes Obsidian, MarginNote, and subagent bases.
5. **Review** — check identity, model, workspace, and selected assets, then create the Partner. Add channels afterwards; they are optional.

Everything chosen here stays editable afterwards from the partner detail page.

## Talk to a partner

Open a partner to land on its **Chat** tab — a full conversation view that behaves like the main workspace, but as that companion. The tabs across the top are **Chat**, **Configure**, **Channels**, and **Archive**.


Because a partner has memory, it builds up a picture of you over time. Ask it "what do you know about me?" and you'll see a `Recalling memory` step — the partner reads its own memory layers before answering in its soul. The **Configure** tab covers identity, soul, mind, and library. **Archive** is soft: Resume reopens the exact session key, Branch copies its full history and archives the source, and only Delete removes a conversation permanently.

## Partner Groups

A **Partner Group** brings two or more Partners into one shared conversation. Choose the member roster, discussion mode, and shared-memory mode, then address everyone or @mention selected members. Each Partner answers in its own seat, so their views remain distinct even when they reason over the same public discussion.

Groups have their own conversation sessions and durable history. If one seat fails, that member can be retried independently without rerunning completed answers. Groups appear below the individual Partner cards on the Partners page; create at least two accessible Partners before forming one.

## Channels

Channels are delivery adapters around the same partner brain. The **Channels** tab lists every supported app down the left; pick one to configure its credentials and behavior on the right, then **Save** and enable it. The page polls the running Partner and reports whether each adapter is connected, connecting, listening, waiting for a scan, missing configuration, unavailable, failed, or simply stopped.

![A Partner’s channel configuration](/screenshots/dev/partners-channels.png)

Most channel cards share a few switches:

| Field | Meaning |
| --- | --- |
| **Enabled** | Start this channel for the partner. Leave off while you collect credentials. |
| **Send Progress** | Deliver narration/progress for long-running turns. Useful where a silent 60-second wait feels broken. |
| **Send Tool Hints** | Deliver one-line tool-call hints such as `rag(query=…)`. Turn off for quieter production channels. |
| **Allow From** | Allowlist of user ids, group ids, emails, or `*` (one per line). Empty usually denies all; `*` opens the channel. |

The rest of each card is channel-specific (base URLs, tokens, polling). For the full list of apps and per-channel setup steps, see the [**Channel Matrix**](/partners/channels/) — start with [**WeChat**](/partners/weixin/), [**WeCom**](/partners/wecom/), or [**QQ / NapCat**](/partners/qq/).

For QR-backed channels, setup stays in the browser. WeChat/WeCom onboarding and a WhatsApp bridge can publish a server-generated code into the card; scan or refresh it there, then watch the same panel move from **Waiting for scan** to a connected state. Use logs only when the status detail does not already explain the failure.


## Partners as consultable agents

A partner can also be **connected as an agent** and consulted from a normal chat turn — DeepTutor sends your question into the partner's own session and folds its answer back. See [My Agents](/explore/subagents/).

## CLI mirror

```bash
deeptutor partner list
deeptutor partner create math-tutor --soul "Socratic math tutor"
deeptutor partner start math-tutor
deeptutor partner stop math-tutor
```

The CLI is handy for smoke tests, but the web UI is the recommended place to configure channels — it masks secrets, shows each channel's schema inline, and exposes live setup/runtime state.

## See also

- [Home](/explore/chat-workspace/) — the same loop, without a personality or channels
- [My Agents](/explore/subagents/) — consult a partner from chat
- [Partners & Channels](/partners/) — the full channel setup guides
- [Memory](/explore/memory/) — how a partner's memory relates to yours
