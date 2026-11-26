---
title: Channel Matrix
description: All built-in Partner channels, their connection model, required fields, and when to use each one.
---

Partner channels are delivery adapters around the same Partner brain. They do not create a second agent runtime: an inbound IM event becomes a scoped chat turn, and the reply is delivered back through the channel.

Use the web UI for most configuration: **Partners -> your partner -> Channels** renders the live schema from `/api/partners/channels/schema`, masks secret fields, polls `/channels/status`, and lets you reload channels without rewriting YAML by hand.

![A Partner’s channel configuration](/screenshots/dev/partners-channels.png)

## Built-in channels

| Channel | Key | Connection model | Best for | Required core fields |
| --- | --- | --- | --- | --- |
| <img src="/channel-icons/weixin.svg" alt="" width="16" height="16" /> WeChat | `weixin` | HTTP long-poll + QR login | Personal WeChat assistant | `allow_from`; optional `token`, `state_dir`, `route_tag`, `poll_timeout` |
| <img src="/channel-icons/wecom.svg" alt="" width="16" height="16" /> WeCom | `wecom` | WeCom AI Bot WebSocket | Enterprise WeChat / WeChat Work | `bot_id`, `secret`, `allow_from` |
| <img src="/channel-icons/qq.svg" alt="" width="16" height="16" /> QQ | `qq` | Tencent botpy WebSocket | Official QQ bot deployments | `app_id`, `secret`, `allow_from`, `msg_format` |
| <img src="/channel-icons/napcat.svg" alt="" width="16" height="16" /> QQ (NapCat) | `napcat` | OneBot v11 WebSocket | Personal QQ via NapCat | `ws_url`, optional `access_token`, `allow_from`, `group_policy` |
| <img src="/channel-icons/telegram.svg" alt="" width="16" height="16" /> Telegram | `telegram` | Bot API polling | Simple personal or group bot | `token`, `allow_from` |
| <img src="/channel-icons/discord.svg" alt="" width="16" height="16" /> Discord | `discord` | Gateway WebSocket | Discord servers and DMs | `token`, `allow_from`, group policy fields |
| <img src="/channel-icons/slack.svg" alt="" width="16" height="16" /> Slack | `slack` | Socket Mode | Slack teams, DMs, threaded channel help | `bot_token`, `app_token`, `allow_from`, `group_policy` |
| <img src="/channel-icons/feishu.svg" alt="" width="16" height="16" /> Feishu / Lark | `feishu` | Lark SDK WebSocket | Feishu/Lark enterprise chat | `app_id`, `app_secret`, verification/encryption fields where used |
| <img src="/channel-icons/dingtalk.svg" alt="" width="16" height="16" /> DingTalk | `dingtalk` | Stream Mode | DingTalk enterprise chat | `client_id`, `client_secret`, `allow_from` |
| <img src="/channel-icons/matrix.svg" alt="" width="16" height="16" /> Matrix | `matrix` | Matrix sync loop | Decentralized rooms, optional E2EE setup | `homeserver`, user credentials or `access_token`, `allow_from`, `group_policy` |
| <img src="/channel-icons/zulip.svg" alt="" width="16" height="16" /> Zulip | `zulip` | Event queue | Stream + topic workflows | `email`, `api_key`, `site`, `allow_from`, `group_policy` |
| <img src="/channel-icons/mattermost.svg" alt="" width="16" height="16" /> Mattermost | `mattermost` | Native v4 WebSocket + REST | Self-hosted open-source team chat | `server_url`, `bot_token`, `allow_from`, optional `group_policy`, `reply_in_thread`, `verify_ssl` |
| <img src="/channel-icons/whatsapp.svg" alt="" width="16" height="16" /> WhatsApp | `whatsapp` | Bridge WebSocket | WhatsApp via a bridge runtime | bridge URL/token, `allow_from` |
| <img src="/channel-icons/email.svg" alt="" width="16" height="16" /> Email | `email` | IMAP poll + SMTP send | Async email tutoring/helpdesk | IMAP host/user/password, SMTP host/user/password, `allow_from` |
| <img src="/channel-icons/mochat.svg" alt="" width="16" height="16" /> Mochat | `mochat` | Socket.IO or HTTP polling | Customer-service style chat panel | `base_url` / socket URL, `claw_token`, `allow_from` |
| <img src="/channel-icons/msteams.svg" alt="" width="16" height="16" /> Microsoft Teams | `msteams` | Built-in HTTP webhook listener | Teams DM-first Bot Framework integration | `app_id`, `app_password`, `tenant_id`, host/port/path |

## Install requirements

Every built-in channel except Matrix is covered by the Partners extra:

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

This pulls in all channel SDKs — `python-telegram-bot`, `slack-sdk`, `lark-oapi`, `dingtalk-stream`, `qq-botpy`, `wecom-aibot-sdk`, `python-socketio`, and friends (the full list lives in `requirements/partners.txt`). Email needs nothing beyond the Python standard library. Matrix ships as its own extra because encrypted rooms need the native `libolm` library: run `python scripts/install_extras.py matrix` for plain rooms or `python scripts/install_extras.py matrix-e2e` for E2EE in a source checkout.

If a channel's dependency is missing on the server, the Channels panel greys that channel out and shows the import error (for example `No module named 'lark_oapi'`). Installed cards distinguish **Connected**, **Connecting**, **Listener running**, **Waiting for scan**, **Configuration required**, **Connection failed**, and **Not connected**. Install a missing package or fix the displayed setup action, then restart/reload the Partner.

Stop DeepTutor before changing installed modules or dependencies. Run the source helper from the repository root, restart with the same data directory, then check `deeptutor module list` and the Channels status. Wheel-based installations should use the extras supported by their matching release; do not install feature wheels over a source checkout.

## Shared delivery switches

Most channels inherit the same delivery controls:

| Field | Meaning |
| --- | --- |
| `enabled` | Whether the Partner should start this channel. |
| `send_progress` | Deliver narration/progress updates during long turns. |
| `send_tool_hints` | Deliver one-line tool-call hints. Useful while debugging, noisy in production. |
| `streaming` | Telegram, Discord, and Feishu only: stream the reply live by editing the message in place as text arrives (Feishu uses CardKit streaming cards). Requires `send_progress`. Off by default. |
| `allow_from` | User/chat allowlist. `*` is convenient for tests; explicit ids are safer for deployment. |

## Configuration workflow

1. Create and test the Partner in the web UI before enabling any IM channel.
2. Enable only one channel first.
3. Keep `send_progress` and `send_tool_hints` on while debugging.
4. Start with `allow_from: ["*"]` only in local/private tests.
5. Confirm the live card reaches a connected/listening state, send a short message, then replace `*` with real sender ids; inspect logs only if the status detail is insufficient.
6. Add more channels only after the first channel is stable.

## Choosing a channel

- Use **WeChat** for personal WeChat. It requires a human QR-code scan and persisted state.
- Use **WeCom**, **Feishu**, **DingTalk**, **Slack**, or **Teams** for enterprise/team deployments.
- Use **QQ** for official Tencent bot accounts; use **NapCat** only when you intentionally operate a personal QQ bridge.
- Use **Email** when asynchronous replies are acceptable and users prefer inbox workflows.
- Use **Matrix** or **Zulip** when room/topic structure matters more than consumer IM convenience.
- Use **Mattermost** for a self-hosted, open-source team chat you run yourself.

## Where state lives

Channel state is stored below the Partner's `channels/` directory, for example:

```text
data/partners/<partner_id>/channels/weixin/account.json
data/partners/<partner_id>/channels/msteams/msteams_conversations.json
```

Persist the whole `data/partners/` tree in Docker or production hosts. Losing channel state can force new QR scans or conversation-reference collection.

## Detailed pages

Every built-in channel has a dedicated page with platform-side registration steps, a field-by-field walkthrough of the channel card, and troubleshooting:

- <img src="/channel-icons/weixin.svg" alt="" width="16" height="16" /> [WeChat](/partners/weixin/) — personal WeChat QR login and long-poll setup
- <img src="/channel-icons/wecom.svg" alt="" width="16" height="16" /> [WeCom](/partners/wecom/) — Enterprise WeChat AI Bot setup
- <img src="/channel-icons/qq.svg" alt="" width="16" height="16" /> [QQ / NapCat](/partners/qq/) — official QQ bot and personal QQ bridge paths
- <img src="/channel-icons/telegram.svg" alt="" width="16" height="16" /> [Telegram](/partners/telegram/) — BotFather registration, Bot API polling, live streaming
- <img src="/channel-icons/discord.svg" alt="" width="16" height="16" /> [Discord](/partners/discord/) — Developer Portal app, intents, Gateway WebSocket
- <img src="/channel-icons/slack.svg" alt="" width="16" height="16" /> [Slack](/partners/slack/) — Socket Mode app with bot + app tokens
- <img src="/channel-icons/feishu.svg" alt="" width="16" height="16" /> [Feishu / Lark](/partners/feishu/) — open-platform app and CardKit streaming cards
- <img src="/channel-icons/dingtalk.svg" alt="" width="16" height="16" /> [DingTalk](/partners/dingtalk/) — Stream Mode enterprise bot
- <img src="/channel-icons/matrix.svg" alt="" width="16" height="16" /> [Matrix](/partners/matrix/) — homeserver credentials and optional E2EE
- <img src="/channel-icons/zulip.svg" alt="" width="16" height="16" /> [Zulip](/partners/zulip/) — bot account and stream subscriptions
- <img src="/channel-icons/mattermost.svg" alt="" width="16" height="16" /> [Mattermost](/partners/mattermost/) — self-hosted server via bot token over the native v4 API
- <img src="/channel-icons/whatsapp.svg" alt="" width="16" height="16" /> [WhatsApp](/partners/whatsapp/) — bridge runtime setup
- <img src="/channel-icons/email.svg" alt="" width="16" height="16" /> [Email](/partners/email/) — IMAP polling and SMTP replies
- <img src="/channel-icons/mochat.svg" alt="" width="16" height="16" /> [Mochat](/partners/mochat/) — Socket.IO customer-service panel
- <img src="/channel-icons/msteams.svg" alt="" width="16" height="16" /> [Microsoft Teams](/partners/msteams/) — Bot Framework webhook listener
