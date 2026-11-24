---
title: Telegram
description: Configure the Telegram channel for a Partner — BotFather registration, Bot API long polling, and live-streamed replies.
quadrant: how-to
---

<img src="/channel-icons/telegram.svg" alt="" width="40" height="40" />

The `telegram` channel connects a Partner to a Telegram bot through Bot API **long polling**: DeepTutor pulls updates from Telegram's servers in a long-lived loop, so you need no public IP, no webhook, and no reverse proxy. Registration through BotFather takes about a minute, which makes Telegram the fastest channel to wire up for a personal assistant or a small group bot.

The channel also supports **live streaming**: with the switch on, the bot sends one message and keeps editing it in place as the reply is generated.

![Telegram channel configuration](/screenshots/dev/partners-channel-telegram.png)

While the Partner is running, use the card's live status as the first check: it should report the polling listener as connected/running; open logs only for detail after a failed state.

## Install requirements

Telegram support ships with the Partners extra. The underlying client is `python-telegram-bot[socks]`, so SOCKS proxy support is already included — nothing extra to install.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Register a bot with BotFather

1. Open Telegram, search for `@BotFather`, and start a chat.
2. Send `/newbot`. BotFather asks for a display name (e.g. `Math Mentor`), then a username that must end in `bot` (e.g. `hku_math_mentor_bot`).
3. BotFather replies with an HTTP API token like `123456789:ABC-DEF1234ghIkl-...`. **Copy it** — this goes into the **Token** field.
4. Find your own user id: chat with `@userinfobot`, which replies with your numeric id. You will need it for **Allow From**.
5. For group use, disable Group Privacy so the bot can read group messages: `/mybots` -> select your bot -> **Bot Settings** -> **Group Privacy** -> **Turn off**.

## Configure the channel card

Open **Partners -> your partner -> Channels -> Telegram**.

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

Replies longer than Telegram's 4096-character limit are split into multiple messages automatically (DeepTutor splits at 4000 to stay clear of the cap).

## After you save

1. Click **Save**, then turn **Enabled** on.
2. Start the partner (or restart it / use the reload action on the Channels panel if it is already running).
3. From an allowed account, open `t.me/<your_bot_username>` and send a short message.
4. Watch the partner logs: you should see the inbound message and the reply delivery.
5. Once you have confirmed the sender id in the logs, replace `*` in **Allow From** with real ids.

## Verify it is healthy

- The logs show the Telegram channel polling without errors (in particular, no `Conflict` lines).
- A short DM from an allowed account gets a reply; with **Send Progress** on you also see narration messages during long turns.
- In a group, @mentioning the bot produces an answer (with the default `mention` policy).

## Troubleshooting

### The bot never replies

Almost always **Allow From**. An empty list denies everyone — including you. Put `*` in for a first test, then switch to your numeric id from `@userinfobot`.

### The bot ignores group messages

Two separate gates must both be open:

1. BotFather: `/mybots` -> your bot -> **Bot Settings** -> **Group Privacy** -> **Turn off** — otherwise Telegram never delivers plain group messages to the bot.
2. Check **Chat Policies** first, then **Group Policy**: `mention` requires an @mention or bot reply; `topics_only` auto-replies only in allowed topics.

### `Conflict: terminated by other getUpdates request`

The same token is being polled from two places at once — two partners with the same token, or another process still running. Telegram allows only one polling client per token; stop the duplicate.

### Telegram is blocked on this network

Fill in **Proxy** with a SOCKS or HTTP proxy URL (e.g. `socks5://127.0.0.1:1080`). SOCKS support is bundled with the partners extra, so no extra package is needed.

## See also

- [Channel Matrix](/partners/channels/) — all channels at a glance
- [Discord](/partners/discord/) — Gateway WebSocket model, similar streaming support
