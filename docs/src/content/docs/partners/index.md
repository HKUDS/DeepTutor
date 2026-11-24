---
title: Partners & Channels
description: Operator guide for DeepTutor Partners, channel configuration, workspace layout, and IM delivery behavior.
---

Partners are persistent DeepTutor companions that can live in the web UI and in external IM apps. They are not a second bot engine. Every incoming message becomes a normal chat-agent turn scoped to that Partner:

```text
IM / Web message -> PartnerRunner -> ChatOrchestrator -> AgenticChatPipeline -> tools -> reply
```

![Partners library](/screenshots/dev/partners.png)

This page is the operator guide. For the product tour of what a Partner *is* — its soul, library, memory, and web Chat view — see [Explore → Partners](/explore/partners/). A Partner can also be [consulted through My Agents](/explore/subagents/) from a normal chat turn.

## What changed from TutorBot

| Old TutorBot | New Partner |
| --- | --- |
| Separate bot engine and `data/tutorbot/<id>/` workspace | Same Chat loop, scoped workspace under `data/partners/<id>/workspace/` |
| Bot-specific CLI commands such as `deeptutor bot ...` | `deeptutor partner list/create/start/stop` |
| Channels edited in bot YAML | Schema-driven channel cards in the Partners UI |
| Bot skills / memory handled separately | Assigned KBs, skills, notebooks, tools, and memory are mounted like normal chat context |

Old `/tutorbot/*` documentation URLs redirect to their `/partners/*` replacements so existing external links and bookmarks keep working.

## Ownership, assignment, and private histories

Any authenticated user can create a Partner and becomes its owner. The owner and any admin can manage its soul, library, channels, model, lifecycle, and deletion. An admin can also assign a Partner to other users; an assigned user can talk to it, but sees only its identity card rather than its configuration and credentials.

Configuration and copied library assets are shared, but relationship state is not. Each authenticated non-admin user gets private conversation files and relationship memory under `users/<user_id>/`. During that user's turns, the Partner can also read the interacting user's own shared memory, while learned preferences are written to the private Partner-user relationship memory. Two people using the same Partner therefore do not see each other's threads or learned preferences. Admin turns and unattributed channel traffic use the Partner's top-level session and memory scope as a compatibility fallback.

## Recommended setup flow

1. Create the Partner in **Partners -> New partner**.
2. Fill **Identity** and **Soul** before enabling any channel. The first IM reply uses this soul.
3. In **Mind**, pick a model and keep optional tools minimal while testing.
4. In **Library**, choose a private copied library or bind an existing owner workspace for live resources. Test one small KB or skill first. See [resource modes](/explore/partners/#account-companions-and-workspace-resources).
5. In **Channels**, enable exactly one channel and start with a private/local test.
6. Keep `send_progress` and `send_tool_hints` on during debugging, then quiet them down for production.
7. Replace `allow_from: ["*"]` with explicit sender ids before opening a channel to real users.

![A Partner’s channel configuration](/screenshots/dev/partners-channels.png)

## Partner Groups

The Partners page also supports first-class **Partner Groups**. Create a group from two or more Partners, choose its member roster, discussion mode, and shared-memory mode, then hold a shared discussion in which every selected Partner keeps its own role and reasoning.

Groups keep separate conversation sessions and durable history. A turn can address all members or selected members, and every member's response occupies its own seat. If one seat fails, it can be retried independently without rerunning the Partners that already answered.

## Channel entry points

| Channel | Use when | Page |
| --- | --- | --- |
| <img src="/channel-icons/weixin.svg" alt="" width="16" height="16" /> WeChat (`weixin`) | Personal WeChat via QR-code login and HTTP long-poll | [WeChat](/partners/weixin/) |
| <img src="/channel-icons/wecom.svg" alt="" width="16" height="16" /> WeCom (`wecom`) | Enterprise WeChat / WeChat Work AI Bot platform | [WeCom](/partners/wecom/) |
| <img src="/channel-icons/qq.svg" alt="" width="16" height="16" /> QQ (`qq`) | Official Tencent QQ bot account via botpy | [QQ / NapCat](/partners/qq/) |
| <img src="/channel-icons/napcat.svg" alt="" width="16" height="16" /> NapCat (`napcat`) | Personal QQ account through OneBot v11 / NapCat | [QQ / NapCat](/partners/qq/) |
| <img src="/channel-icons/telegram.svg" alt="" width="16" height="16" /> Telegram (`telegram`) | Fastest setup — BotFather token, no public IP | [Telegram](/partners/telegram/) |
| <img src="/channel-icons/discord.svg" alt="" width="16" height="16" /> Discord (`discord`) | Discord servers and DMs via Gateway WebSocket | [Discord](/partners/discord/) |
| <img src="/channel-icons/slack.svg" alt="" width="16" height="16" /> Slack (`slack`) | Slack teams over Socket Mode, threaded replies | [Slack](/partners/slack/) |
| <img src="/channel-icons/feishu.svg" alt="" width="16" height="16" /> Feishu (`feishu`) | Feishu / Lark with CardKit streaming cards | [Feishu](/partners/feishu/) |
| <img src="/channel-icons/dingtalk.svg" alt="" width="16" height="16" /> DingTalk (`dingtalk`) | DingTalk enterprise bot over Stream Mode | [DingTalk](/partners/dingtalk/) |
| <img src="/channel-icons/matrix.svg" alt="" width="16" height="16" /> Matrix (`matrix`) | Decentralized rooms, optional E2EE | [Matrix](/partners/matrix/) |
| <img src="/channel-icons/zulip.svg" alt="" width="16" height="16" /> Zulip (`zulip`) | Stream + topic structured team chat | [Zulip](/partners/zulip/) |
| <img src="/channel-icons/mattermost.svg" alt="" width="16" height="16" /> Mattermost (`mattermost`) | Self-hosted Mattermost via native v4 WebSocket | [Mattermost](/partners/mattermost/) |
| <img src="/channel-icons/whatsapp.svg" alt="" width="16" height="16" /> WhatsApp (`whatsapp`) | WhatsApp through a bridge runtime | [WhatsApp](/partners/whatsapp/) |
| <img src="/channel-icons/email.svg" alt="" width="16" height="16" /> Email (`email`) | Async inbox workflows over IMAP/SMTP | [Email](/partners/email/) |
| <img src="/channel-icons/mochat.svg" alt="" width="16" height="16" /> Mochat (`mochat`) | Customer-service style chat panels | [Mochat](/partners/mochat/) |
| <img src="/channel-icons/msteams.svg" alt="" width="16" height="16" /> Microsoft Teams (`msteams`) | Teams via Bot Framework webhook listener | [Microsoft Teams](/partners/msteams/) |

For a side-by-side comparison of connection models, required fields, and delivery switches, see the [Channel Matrix](/partners/channels/).

## Runtime state

```text
data/partners/<partner_id>/
├── config.yaml                  # Partner identity, model, channels, tools
├── sessions/                    # Shared/unattributed conversations
│   ├── <session_key>.jsonl      # One append-only file per conversation
│   └── _index.json              # Archive metadata, created when needed
├── channels/
│   └── <channel>/...            # QR tokens, cursors, conversation refs
├── users/<user_id>/             # Private state for an authenticated user
│   ├── sessions/<session_key>.jsonl
│   └── workspace/memory/
└── workspace/
    ├── knowledge_bases/         # Copied assigned KBs
    └── user/
        ├── workspace/SOUL.md
        ├── workspace/skills/<name>/SKILL.md
        ├── workspace/notebook/
        └── workspace/memory/
```

This tree shows the private-library arrangement. A Partner bound to an existing owner workspace uses that workspace's current resources and outputs folder instead. Soul, channel state, sessions, and relationship memory remain Partner state. Partners and Partner Groups belong to the account, so their cards remain available across workspace switches.

## Conversation commands

Partner chats share these slash commands:

- `/help` — show the available commands.
- `/new` — archive the current conversation and start fresh; `/branch` archives it and continues in a copy; `/stop` halts a running reply.
- `/sessions` — list conversation ids; `/resume <session-id>` reopens an archived one and `/delete <session-id>` permanently removes one.
- `/status` — Partner, session, model, and tool status; `/history [n]` shows recent messages.
- `/tool [on|off <name>|reset]` — inspect or change enabled tools.
- `/model [number|model name]` — owner or admin lists or switches the model, in a DM.
- `/link <code>` — in an external DM, link that chat account to the DeepTutor user who generated the code in the web app.

## Web UI vs CLI

Use the Web UI for channel configuration because it renders the live schema from `/api/partners/channels/schema` and masks secret-looking fields. Use the CLI for lifecycle checks:

```bash
deeptutor partner list
deeptutor partner start math-tutor
deeptutor partner stop math-tutor
```
