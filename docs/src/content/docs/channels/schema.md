---
title: Channel Matrix
description: All built-in Partner channels, their connection model, required fields, and when to use each one.
quadrant: reference
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

- <img src="/channel-icons/weixin.svg" alt="" width="16" height="16" /> [WeChat](/channels/domestic/weixin/) — personal WeChat QR login and long-poll setup
- <img src="/channel-icons/wecom.svg" alt="" width="16" height="16" /> [WeCom](/channels/domestic/wecom/) — Enterprise WeChat AI Bot setup
- <img src="/channel-icons/qq.svg" alt="" width="16" height="16" /> [QQ / NapCat](/channels/domestic/qq/) — official QQ bot and personal QQ bridge paths
- <img src="/channel-icons/telegram.svg" alt="" width="16" height="16" /> [Telegram](/channels/international/telegram/) — BotFather registration, Bot API polling, live streaming
- <img src="/channel-icons/discord.svg" alt="" width="16" height="16" /> [Discord](/channels/international/discord/) — Developer Portal app, intents, Gateway WebSocket
- <img src="/channel-icons/slack.svg" alt="" width="16" height="16" /> [Slack](/channels/international/slack/) — Socket Mode app with bot + app tokens
- <img src="/channel-icons/feishu.svg" alt="" width="16" height="16" /> [Feishu / Lark](/channels/domestic/feishu/) — open-platform app and CardKit streaming cards
- <img src="/channel-icons/dingtalk.svg" alt="" width="16" height="16" /> [DingTalk](/channels/domestic/dingtalk/) — Stream Mode enterprise bot
- <img src="/channel-icons/matrix.svg" alt="" width="16" height="16" /> [Matrix](/channels/international/matrix/) — homeserver credentials and optional E2EE
- <img src="/channel-icons/zulip.svg" alt="" width="16" height="16" /> [Zulip](/channels/international/zulip/) — bot account and stream subscriptions
- <img src="/channel-icons/mattermost.svg" alt="" width="16" height="16" /> [Mattermost](/channels/international/mattermost/) — self-hosted server via bot token over the native v4 API
- <img src="/channel-icons/whatsapp.svg" alt="" width="16" height="16" /> [WhatsApp](/channels/international/whatsapp/) — bridge runtime setup
- <img src="/channel-icons/email.svg" alt="" width="16" height="16" /> [Email](/channels/international/email/) — IMAP polling and SMTP replies
- <img src="/channel-icons/mochat.svg" alt="" width="16" height="16" /> [Mochat](/channels/domestic/mochat/) — Socket.IO customer-service panel
- <img src="/channel-icons/msteams.svg" alt="" width="16" height="16" /> [Microsoft Teams](/channels/international/msteams/) — Bot Framework webhook listener

## Per-channel fields

These are the fields on each channel card. The card is rendered from `GET /api/partners/channels/schema`. Shared switches stay in the matrix above.

<a id="dingtalk"></a>

### DingTalk

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It delivers narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if users should not see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **Client Id** | The AppKey from Credentials & Basic Info (often starts with `ding...`). |
| **Client Secret** | The AppSecret from the same page. Stored as a secret and masked after save. |
| **Allow From** | One value per line. Use `*` for a first test, or DingTalk staff ids (the partner logs print the sender id with every inbound message). Empty denies everyone. |
<a id="feishu"></a>

### Feishu

| Field | What to enter |
| --- | --- |
| **Streaming** | Off by default. Streams the reply live into a CardKit card with a typewriter effect. Requires **Send Progress**: narration rounds stream as they happen. |
| **Send Progress** | Keep on while testing. It delivers narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if users should not see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **App Id** | The `cli_...` App ID from Credentials & Basic Info. |
| **App Secret** | The App Secret from the same page. Stored as a secret and masked after save. |
| **Domain** | `feishu` (default) for mainland Feishu apps; select `lark` for international Lark tenants so the SDK uses `open.larksuite.com`. The scan flow fills this automatically. |
| **Encrypt Key** | Only needed when event encryption is enabled on the platform. Leave blank otherwise. |
| **Verification Token** | The event Verification Token from the platform; used to verify event signatures. Leave blank if you did not configure one. |
| **Allow From** | One value per line. Use `*` for an open test bot, or `ou_...` open ids (copy them from the partner logs after a first message). Empty denies everyone. |
| **React Emoji** | The reaction the bot adds to every message it accepts, as an instant acknowledgement. Default `THUMBSUP`; other common types: `OK`, `EYES`, `DONE`, `OnIt`, `HEART`. |
| **Group Policy** | `mention` (default): in groups the bot only answers when @mentioned. `open`: it answers every group message. DMs always get a response. |
| **Reply In Thread** | On by default. Group replies stay in the triggering message's thread. Single chats always get a plain reply. |
| **Thinking Notice** | On by default. Posts a short thinking notice while the model reasons, and removes it when the answer starts. |
| **Stream Print Frequency Ms** | CardKit typewriter interval in milliseconds. Default `30`. `0` uses the platform default. |
| **Stream Print Step** | Characters revealed on each typewriter step. Default `6`. `0` uses the platform default. |
| **Stream Print Strategy** | `fast` (default) or `delay`. |
<a id="mochat"></a>

### Mochat

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It sends narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if you do not want users to see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **Base Url** | Your Mochat instance. Default: `https://mochat.io`. |
| **Socket Url** | Optional separate Socket.IO endpoint. Blank means use **Base Url**. |
| **Socket Path** | Socket.IO mount path. Default: `/socket.io`. |
| **Socket Disable Msgpack** | Off by default (msgpack is used when available). Turn on to force JSON if your server has no msgpack parser. |
| **Socket Reconnect Delay Ms** | Initial reconnect delay. Default `1000`. |
| **Socket Max Reconnect Delay Ms** | Reconnect backoff cap. Default `10000`. |
| **Socket Connect Timeout Ms** | Connection timeout. Default `10000`. |
| **Refresh Interval Ms** | How often the channel refreshes its session/panel directory. Default `30000`. |
| **Watch Timeout Ms** | Long-poll timeout in HTTP fallback mode. Default `25000`. |
| **Claw Token** | Required. The bot token from your Mochat admin panel. |
| **Sessions** | Session ids to watch, one per line. `*` auto-discovers and subscribes new sessions. |
| **Panels** | Panel ids to watch, one per line. `*` auto-discovers panels. Leave both lists empty and the channel watches nothing. |
| **Allow From** | One value per line. Use `*` for an open test channel, or specific Mochat user ids. Empty denies access. |

| Field | Notes |
| --- | --- |
| **Watch Limit** | Max events fetched per poll. Default `100`. |
| **Retry Delay Ms** | Delay between failed HTTP retries. Default `500`. |
| **Max Retry Attempts** | Maximum Socket.IO reconnection attempts. `0` means reconnect forever. This field does not cap HTTP fallback loops. |
| **Agent User Id** | The bot's own Mochat user id. Used to ignore the bot's own messages and to detect @-mentions. |
| **Mention** | `require_in_groups` — require an @-mention before answering in group sessions. |
| **Groups** | Per-group overrides, keyed by group id: `{"<group-id>": {"require_mention": true}}`. |
| **Reply Delay Mode** | `non-mention` (default) buffers panel messages that do not mention the bot; any other value disables buffering. |
| **Reply Delay Ms** | Buffer window. Default `120000` (2 minutes). |
<a id="qq"></a>

### QQ / NapCat

| Field | Notes |
| --- | --- |
| `enabled` | Start the channel with the partner. |
| `app_id` | App ID from Tencent's bot platform. |
| `secret` | Bot secret. |
| `allow_from` | Allowed QQ user ids / openids. Empty denies access; use explicit ids for production. |
| `msg_format` | `plain` or `markdown`. Start with `plain` if clients render Markdown inconsistently. |

<a id="napcat"></a>

| Field | Notes |
| --- | --- |
| `enabled` | Start the channel with the partner. |
| `ws_url` | NapCat WebSocket endpoint, default `ws://127.0.0.1:3001`. |
| `access_token` | Optional OneBot access token. |
| `allow_from` | Allowed user ids. Use `*` only for local testing. |
| `group_policy` | `mention`, `open`, or a probability between `0` and `1`. Mentions/replies always respond. |
| `group_policy_overrides` | Per-group policy map, keyed by group id. |
| `welcome_new_members` | Whether to welcome new group members. |
| `max_image_bytes` | Hard cap for inbound image downloads. |
<a id="wecom"></a>

### WeCom (WeChat Work)

| Field | Notes |
| --- | --- |
| `enabled` | Start this channel when the partner starts. |
| `bot_id` | Bot ID from WeCom AI Bot platform. |
| `secret` | Secret from WeCom. Treat it as a credential. |
| `allow_from` | User ids allowed to talk to this partner. Empty denies access; `*` opens it where supported by the base channel policy. |
| `welcome_message` | Optional text sent when a user opens the chat. |
| `send_progress` / `send_tool_hints` | Delivery switches for narration and one-line tool calls. |
<a id="weixin"></a>

### WeChat (Personal Weixin)

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It sends narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if you do not want users to see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to login/start the channel. |
| **Allow From** | One value per line. Use `*` for an open test channel, or specific WeChat user ids once you know them. Empty denies access. |
| **Base Url** | Default: `https://ilinkai.weixin.qq.com`. Usually leave unchanged. |
| **Cdn Base Url** | Default: `https://novac2c.cdn.weixin.qq.com/c2c`. Used for media upload/download. |
| **Route Tag** | Optional Tencent route tag. Leave blank unless your deployment requires it. |
| **Token** | Optional bot token. Leave blank for QR-code login; the channel saves the token after a successful scan. |
| **State Dir** | Optional custom state directory. Blank means DeepTutor uses `data/partners/<id>/channels/weixin/` for `account.json`. |
| **Poll Timeout** | Long-poll timeout in seconds. `35` is the default and works for most networks. |
<a id="discord"></a>

### Discord

| Field | What to enter |
| --- | --- |
| **Streaming** | Off by default. Streams the reply live by editing the message in place as text arrives. Requires **Send Progress**: narration rounds stream as they happen. |
| **Send Progress** | Keep on while testing. It delivers narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if users should not see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **Token** | The bot token from the Developer Portal (**Bot** -> **Reset Token**). Stored as a secret and masked after save. |
| **Allow From** | One value per line. Use `*` for an open test bot, or Discord user ids (right-click -> Copy User ID with Developer Mode on). Empty denies everyone. |
| **Gateway Url** | Default `wss://gateway.discord.gg/?v=10&encoding=json`. Change it only if you proxy the gateway. |
| **Intents** | Gateway intent bitfield. The default `37377` covers Guilds, Guild Messages, Direct Messages, and Message Content. Any privileged intent in this number must also be enabled in the Developer Portal. |
| **Group Policy** | `mention` (default): in server channels the bot only answers when @mentioned. `open`: it answers every message in channels it can read. DMs always get a response. |
<a id="email"></a>

### Email

| Field | What to enter |
| --- | --- |
| **Send Progress** | Each progress update becomes a separate email. Fine for a first test; most deployments turn it off to keep inboxes quiet. |
| **Send Tool Hints** | Same caveat — one email per hint. Turn off outside debugging. |
| **Enabled** | Turn on when you are ready to start polling. |
| **Consent Granted** | Hard privacy gate. The channel refuses to read or send any mail until this is on. Enable it only after the mailbox owner has explicitly agreed to let DeepTutor process the inbox. |
| **Imap Host** | e.g. `imap.gmail.com`. |
| **Imap Port** | Default `993` (IMAP over SSL). |
| **Imap Username** | Usually the full address, e.g. `tutor@example.com`. |
| **Imap Password** | The App Password (Gmail/Outlook with 2FA) or account password (self-hosted). Stored as a secret. |
| **Imap Mailbox** | Default `INBOX`. Some providers spell folders differently — check webmail if polling finds nothing. |
| **Imap Use Ssl** | Keep on for port 993. |
| **Smtp Host** | e.g. `smtp.gmail.com`. |
| **Smtp Port** | Default `587` (STARTTLS). Use `465` together with **Smtp Use Ssl**. |
| **Smtp Username** | Usually the same as Imap Username. |
| **Smtp Password** | Usually the same App Password. Stored as a secret. |
| **Smtp Use Tls** | STARTTLS on port 587. Keep on unless you switch to implicit SSL below. |
| **Smtp Use Ssl** | Implicit SSL, typically port 465. Enable one of the two TLS options, not both. |
| **From Address** | Optional. Blank falls back to Smtp Username, then Imap Username. |
| **Auto Reply Enabled** | When off, the Partner stops replying automatically to inbound mail (proactive sends still work). Useful as a brake while testing. |
| **Poll Interval Seconds** | Default `30`. How often the inbox is checked; values below 5 are clamped to 5. |
| **Mark Seen** | Marks processed mail as read — this is the primary duplicate protection. Leave on. |
| **Max Body Chars** | Default `12000`. Longer bodies are truncated before reaching the Partner. |
| **Subject Prefix** | Default `Re: `. Prepended to reply subjects unless the subject already starts with `Re:`. |
| **Allow From** | One email address per line, lowercase. `*` for an open test channel. Empty denies everyone. |
<a id="matrix"></a>

### Matrix

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It sends narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if you do not want users to see one-line tool calls. |
| **Enabled** | Turn on when you are ready to start the channel. |
| **Homeserver** | Default `https://matrix.org`. Use your own server's URL if self-hosted. |
| **Access Token** | The token from Element or the login API. Stored as a secret. |
| **User Id** | The bot's full Matrix id, e.g. `@my-bot:matrix.org`. Also used to detect mentions. |
| **Device Id** | Optional but recommended: pick any stable string and keep it. If blank, a restart may replay recent messages. |
| **E2Ee Enabled** | Turn on only after installing the `[matrix-e2e]` extra plus libolm. Without them the bot cannot decrypt encrypted rooms. |
| **Sync Stop Grace Seconds** | Default `2`. How long an in-flight sync may finish during shutdown. Rarely changed. |
| **Max Media Bytes** | Default `20971520` (20 MB). Size cap for attachment uploads and downloads. |
| **Allow From** | One Matrix user id per line, e.g. `@frank:matrix.org`. `*` for an open test channel. Empty denies everyone — including room invites. |
| **Group Policy** | For multi-person rooms: `open` (default) answers every message, `mention` answers only when the bot is mentioned, `allowlist` answers only in rooms listed below. Direct 1:1 chats are always answered. |
| **Group Allow From** | Room ids (`!abc123:matrix.org`), one per line. Only used with the `allowlist` policy. |
| **Allow Room Mentions** | Whether an `@room` ping counts as mentioning the bot under the `mention` policy. Off by default. |
<a id="mattermost"></a>

### Mattermost

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It delivers narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if users should not see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **Server Url** | Your Mattermost base URL, e.g. `https://mattermost.example.com`. The scheme is optional (defaults to `https`) and the WebSocket URL is derived automatically — do not append `/api/v4`. |
| **Bot Token** | The bot account's access token from **Integrations -> Bot Accounts**. Stored as a secret and masked after save. |
| **Allow From** | One value per line. Use `*` for an open test bot, or Mattermost user ids. Empty denies everyone. |
| **Group Policy** | `mention` (default): in channels the bot only answers when @mentioned. `open`: it answers every message in channels it has joined. Direct messages always get a reply. |
| **Reply In Thread** | On (default): the bot answers in a thread rooted at the triggering post. Thread follow-ups still pass **Group Policy** first, so with the default `mention` policy they must @mention the bot. Off: replies go straight into the channel. |
| **Verify Ssl** | On (default). Turn off only for a self-hosted server whose TLS certificate is self-signed or issued by an internal CA. |
<a id="msteams"></a>

### Microsoft Teams

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It delivers narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if users should not see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **App Id** | The Application (client) ID of the app registration. Also used as the expected audience when validating inbound JWTs. |
| **App Password** | The client secret value. Stored as a secret and masked after save. |
| **Tenant Id** | The Directory (tenant) ID. Required for single-tenant registrations; leave blank only for multi-tenant bots. |
| **Host** | Bind address for the built-in HTTP server. Default `0.0.0.0` listens on all interfaces; use `127.0.0.1` if a local reverse proxy is the only client. |
| **Port** | Listening port. Default `3978`, the Bot Framework convention. It must be unique among all enabled Teams Partners running on the same host. |
| **Path** | URL path for inbound activities. Default `/api/messages`; it must match the tail of the messaging endpoint. |
| **Allow From** | One value per line. Use `*` for a first test, or Microsoft Entra object ids — the partner logs print the id of any denied sender. Empty denies everyone. |
| **Reply In Thread** | When on (default), replies attach to the triggering message instead of starting a new one. |
| **Mention Only Response** | The text sent back when a message contains nothing but the bot @mention. |
| **Validate Inbound Auth** | Keep on. Verifies the Bot Framework JWT on every request (RS256 against Microsoft's published keys, audience = App Id). Turning it off lets anyone who finds the URL talk to your partner as any user — local testing only. |
| **Ref Ttl Days** | Days an idle conversation reference is kept before pruning. Default `30`. |
| **Prune Web Chat Refs** | Drops Bot Framework Web Chat conversations from the stored references (Web Chat is not supported). |
| **Prune Non Personal Refs** | Drops group/channel conversation references; the channel is DM-only for now. |
| **Ref Touch Interval S** | Minimum seconds between timestamp refreshes on an active conversation reference. Default `300`. |
| **Trusted Service Url Hosts** | Allowlist of Bot Framework hosts the channel accepts and replies to. The default covers the public, GCC, and DoD Teams clouds — extend it only if Microsoft routes you elsewhere. |
<a id="slack"></a>

### Slack

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It delivers narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if users should not see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **Mode** | `socket` is the only supported mode. Leave it unchanged. |
| **Webhook Path** | Reserved for a future webhook mode; unused while **Mode** is `socket`. Leave the default `/slack/events`. |
| **Bot Token** | The `xoxb-…` token from **OAuth & Permissions**. Stored as a secret and masked after save. |
| **App Token** | The `xapp-…` App-Level Token from **Socket Mode** (needs `connections:write`). Also a secret. Do not swap it with the Bot Token. |
| **User Token Read Only** | Keep the default (on). |
| **Reply In Thread** | On (default): the bot answers in a thread under the triggering message. Follow-ups in that thread still pass **Group Policy** first, so with the default `mention` policy they must @mention the bot. Off: replies go straight into the channel. |
| **React Emoji** | Emoji name (no colons) the bot adds to your message as a receipt acknowledgement. Default `eyes`. |
| **Allow From** | One value per line. Use `*` for an open test bot, or Slack user ids (`U…`). Empty denies everyone. |
| **Group Policy** | `mention` (default): in channels the bot only answers @mentions. `open`: it answers every message in channels it is in. `allowlist`: only channels listed in **Group Allow From**. |
| **Group Allow From** | Channel ids (`C…`), one per line. Used when **Group Policy** is `allowlist`. |
| **Dm** | DM sub-policy: **Enabled** toggles DMs as a whole; **Policy** `open` answers any DM, `allowlist` restricts DMs to the ids in its own **Allow From** list. |
<a id="telegram"></a>

### Telegram

| Field | What to enter |
| --- | --- |
| **Streaming** | Off by default. Streams the reply live by editing the Telegram message in place as text arrives. Requires **Send Progress**: narration rounds stream as they happen. |
| **Send Progress** | Keep on while testing. It delivers narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if users should not see one-line tool calls. |
| **Enabled** | Turn on only when you are ready to start the channel. |
| **Token** | The HTTP API token from BotFather. Stored as a secret and masked after save. |
| **Allow From** | One value per line. Use `*` for an open test bot, or numeric user ids from `@userinfobot` (usernames also match). Empty denies everyone. |
| **Proxy** | Optional proxy URL for networks where Telegram is unreachable, e.g. `socks5://127.0.0.1:1080` or `http://proxy:8080`. Leave blank for a direct connection. |
| **Reply To Message** | When on, the bot's answers quote the message that triggered them. Useful in busy groups, redundant in DMs. |
| **Group Policy** | Fallback for groups: `mention` (default) requires an @mention or bot reply; `open` answers every message. DMs bypass group policies; **Allow From** still applies. |
| **Chat Policies** | Per-chat overrides keyed by `chat_id`: `open`, `mention`, or `topics_only`. The latter auto-replies in `allowed_topics`; elsewhere an @mention or bot reply is required. First matching rule wins. |
| **Connection Pool Size** | HTTP connection pool for the Bot API client. Default `16` is fine for one bot. |
| **Pool Timeout** | Seconds to wait for a free pooled connection. Default `15`. |
| **Stream Edit Interval** | Minimum seconds between in-place edits while streaming. Default `0.6`; raise it if Telegram answers with flood-control errors. |
<a id="whatsapp"></a>

### WhatsApp

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It sends narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if you do not want users to see one-line tool calls. |
| **Enabled** | Turn on only when the bridge is running and you are ready to start the channel. |
| **Bridge Url** | WebSocket URL of the bridge. Default: `ws://localhost:3001`. |
| **Bridge Token** | Optional shared secret. Set it only if your bridge checks the `auth` message. |
| **Allow From** | One value per line. Use `*` for an open test channel, or specific sender ids (the part before `@` in WhatsApp ids — usually the phone number). Empty denies access. |
<a id="zulip"></a>

### Zulip

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It sends narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if you do not want users to see one-line tool calls. |
| **Enabled** | Turn on when you are ready to start the channel. |
| **Site** | Your Zulip server URL, e.g. `https://yourorg.zulipchat.com`. Include the scheme and the correct realm subdomain. |
| **Email** | The bot's generated email from the creation page — not your own. |
| **Api Key** | The bot's API key. Stored as a secret. |
| **Allow From** | One Zulip user id or email per line — either form matches. `*` for an open test channel. Empty denies everyone. |
| **Group Policy** | For stream messages: `mention` (default) answers only when the bot is @-mentioned, `open` answers every message in subscribed streams. Direct messages are always answered. |
| **Subscribe Streams** | Stream names, one per line. The channel subscribes the bot to them at startup. |
| **Timeout** | Event-queue long-poll timeout in seconds. Default `60` works for most servers. |
