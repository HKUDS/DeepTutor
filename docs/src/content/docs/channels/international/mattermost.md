---
title: Mattermost
description: Configure the Mattermost channel for a Partner — bot account access token, native v4 WebSocket + REST, thread replies, and self-hosted TLS.
quadrant: how-to
---

<img src="/channel-icons/mattermost.svg" alt="" width="40" height="40" />

The `mattermost` channel connects a Partner to a self-hosted **Mattermost** server over its **native v4 API** — a WebSocket (`/api/v4/websocket`) for incoming events and the REST API (`/api/v4`) for sending. DeepTutor speaks the Mattermost protocol directly — no `mattermostdriver` dependency, built on the same `httpx` + `websockets` stack as Discord — so a self-hosted deployment gets a first-class integration instead of routing through Mattermost's Slack-compatibility shim.

A single **bot access token** authorizes everything; there is no second connection token to juggle as with Slack. Mattermost renders Markdown natively, so replies need no format conversion, and the card has no **Streaming** switch — replies arrive as complete messages, with narration delivered separately when **Send Progress** is on.

![Mattermost channel configuration](/screenshots/dev/partners-channel-mattermost.png)

While the Partner is running, use the card's live status as the first check: it should move from **Connecting** to **Connected**; open logs only for detail after a failed state.

## Install requirements

The Mattermost channel ships with the Partners extra. Its transport is built on `httpx` and `websockets`, which are already included — there is no extra SDK to install.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Create the bot account

1. As a Mattermost **System Admin**, enable bot accounts: **System Console -> Integrations -> Bot Accounts -> Enable Bot Account Creation** = **true**.
2. Open **Integrations -> Bot Accounts -> Add Bot Account**. Give it a username (and optionally a display name and description), then **Create**.
3. Mattermost shows the bot's **access token once** — copy it now. This is the **Bot Token**. If you lose it, create a new token for the bot rather than reusing a personal one.
4. Add the bot to the teams and channels it should serve: in a channel, `/invite @your-bot`, or add it from the channel members panel. A bot only receives messages from channels it has joined.
5. To collect ids for **Allow From**: each sender's Mattermost **user id** is shown in the System Console user list (and the partner logs print it on the first message). Usernames drive `@mention` detection, but **Allow From** matches the user id.

## Configure the channel card

Open **Partners -> your partner -> Channels -> Mattermost**.

Card fields for this channel are in the [channel schema](/channels/schema/#mattermost).


Replies longer than Mattermost's post limit (~16k characters) are split into multiple messages automatically; file attachments up to 50 MB are supported.

## After you save

1. Click **Save**, then turn **Enabled** on.
2. Start the partner (or restart it / use the reload action on the Channels panel if it is already running).
3. From an allowed account, DM the bot or @mention it in a channel it has joined.
4. Watch the partner logs: you should see the bot identity resolve (`@your-bot`), the WebSocket connect, the inbound post, and the reply delivery.
5. Once you have confirmed the sender id in the logs, replace `*` in **Allow From** with real ids.

## Verify it is healthy

- The logs show `Mattermost bot identity: @your-bot` and `Mattermost WebSocket connected`, with no reconnect loop.
- The bot account shows as active in your Mattermost team.
- A DM from an allowed account gets a reply, and an @mention in a joined channel gets one too (with the default **Group Policy** = `mention`).

## Troubleshooting

### The WebSocket never connects, or the token is rejected

The channel validates the **Bot Token** by calling `/api/v4/users/me` before it connects, so a bad token fails fast. A `401` means the token is wrong or was revoked — generate a fresh one under **Integrations -> Bot Accounts**. Also confirm **Server Url** is the base server URL with no `/api/v4` suffix (that path is added for you).

### TLS / certificate errors on a self-hosted server

A self-signed or internal-CA certificate fails verification. Either install the CA on the DeepTutor host, or turn **Verify Ssl** off for that channel — acceptable on a trusted private network.

### The bot ignores channel messages, but DMs work

Two gates to check:

1. With **Group Policy** = `mention`, your message must actually @mention the bot, and the bot must be a member of that channel (`/invite @your-bot`).
2. **Allow From** — an empty list denies everyone. Use `*` to test, then the real Mattermost user ids.

### Replies land in a thread and unmentioned follow-ups get ignored

**Reply In Thread** controls the destination of the bot's answer; it does not bypass mention filtering. With **Group Policy** = `mention`, @mention the bot in every thread follow-up, or switch to `open` if all messages in joined channels should be eligible. Turn **Reply In Thread** off only for flat channel replies.

## See also

- [Channel Matrix](/channels/schema/) — all channels at a glance
- [Slack](/channels/international/slack/) — the team-chat channel Mattermost's native API replaces
- [Discord](/channels/international/discord/) — the same direct WebSocket + REST transport
