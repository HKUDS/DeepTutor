---
title: Discord
description: Configure the Discord channel for a Partner — Developer Portal app, Gateway WebSocket, intents, and live-streamed replies.
quadrant: how-to
---

<img src="/channel-icons/discord.svg" alt="" width="40" height="40" />

The `discord` channel connects a Partner to a Discord bot over the **Gateway WebSocket** (API v10). DeepTutor speaks the gateway protocol directly — no `discord.py` dependency — and handles heartbeats and reconnects on its own. As with Telegram, there is no public IP or webhook requirement; the bot dials out to Discord.

**Streaming** is supported: with the switch on, the bot posts one message and keeps patching it through the REST API as the reply is generated, so the answer grows in place.

![Discord channel configuration](/screenshots/dev/partners-channel-discord.png)

While the Partner is running, use the card's live status as the first check: it should move from **Connecting** to **Connected**; open logs only for detail after a failed state.

## Install requirements

Discord support ships with the Partners extra; the gateway client is built on `websockets`, which is already included.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Create the Discord application

1. Open <https://discord.com/developers/applications> and click **New Application**; give it a name.
2. In the left sidebar, open **Bot**. Under **TOKEN**, click **Reset Token** and copy the value — this goes into the **Token** field.
3. Still on the **Bot** page, under **Privileged Gateway Intents**, enable **MESSAGE CONTENT INTENT**. Without it the bot receives messages with empty text. **Server Members Intent** is optional.
4. Invite the bot to your server: **OAuth2** -> **URL Generator**, check the `bot` scope, then check the permissions `Send Messages`, `Read Message History`, and `Attach Files`. Open the generated URL, pick a server, **Authorize**. The adapter does not add reactions or send embeds, so those permissions are not required.
5. To collect user ids for **Allow From**: Discord settings -> **Advanced** -> enable **Developer Mode**, then right-click any user -> **Copy User ID**.

## Configure the channel card

Open **Partners -> your partner -> Channels -> Discord**.

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

Replies longer than Discord's 2000-character limit are split into multiple messages automatically.

## After you save

1. Click **Save**, then turn **Enabled** on.
2. Start the partner (or restart it / use the reload action on the Channels panel if it is already running).
3. From an allowed account, DM the bot or @mention it in a server channel.
4. Watch the partner logs: you should see the gateway connect, the inbound message, and the reply delivery.
5. Once you have confirmed the sender id in the logs, replace `*` in **Allow From** with real ids.

## Verify it is healthy

- The logs show the gateway connected and heartbeating, with no reconnect loop.
- The bot appears **online** in your server's member list.
- A DM from an allowed account gets a reply, and an @mention in a server channel gets one too.

## Troubleshooting

### The gateway closes with `4014: Disallowed intent`

The **Intents** number requests a privileged intent that is not enabled in the Developer Portal. Most often it is Message Content: open your app -> **Bot** -> enable **MESSAGE CONTENT INTENT**, then restart the partner.

### The bot is online but never replies

Check two things:

1. **Allow From** — an empty list denies everyone. Use `*` to test, then your real user id.
2. **MESSAGE CONTENT INTENT** — without it, server messages arrive with empty `content`, so the bot has nothing to answer. Enable it in the portal.

### No replies in server channels, but DMs work

With **Group Policy** = `mention`, the message must actually @mention the bot. Also confirm the bot was invited with `Send Messages` and `Read Message History` permissions in that channel.

### Streaming is on but nothing streams

**Streaming** requires **Send Progress** — turn both on. Also note Discord rate-limits message edits, so the in-place updates arrive in chunks rather than character by character; that is expected.

## See also

- [Channel Matrix](/partners/channels/) — all channels at a glance
- [Telegram](/partners/telegram/) — simpler polling model, same streaming switch
- [Slack](/partners/slack/) — similar developer-portal feel, Socket Mode
