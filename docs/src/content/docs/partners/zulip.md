---
title: Zulip
description: Configure the Zulip channel for a Partner — event-queue long polling with stream + topic scoped sessions.
quadrant: how-to
---

<img src="/channel-icons/zulip.svg" alt="" width="40" height="40" />

The `zulip` channel connects a Partner to Zulip's structured team chat. Zulip splits conversations into **streams** and **topics**, and the channel keeps that structure: every (stream, topic) pair is its own Partner session, so each homework thread or support topic carries its own context. Direct messages work too, scoped per sender.

![Zulip channel configuration](/screenshots/dev/partners-channel-zulip.png)

While the Partner is running, use the card's live status as the first check: it should report the event listener as connected/running; open logs only for detail after a failed state.

## Install requirements

Zulip support is included with the Partners extra — the `zulip` client package comes with it, nothing else to install.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Create a bot in Zulip

1. In Zulip, click the gear icon (top right) -> **Organization** (or **Personal**) **settings** -> **Bots**.
2. Click **Add a new bot**, type **Generic bot**, and give it a name.
3. Zulip generates a bot email like `my-bot@yourorg.zulipchat.com` — this is what goes in the **Email** field, not a human address.
4. Copy the bot's **API key** from the same page.
5. Generic bots receive direct messages by default but see a stream only when subscribed. Subscribe via the bot's settings in Zulip, or let DeepTutor do it with **Subscribe Streams** below.

## Configure the channel card

Open **Partners -> your partner -> Channels -> Zulip**.

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

## After you save

1. Click **Save**, then turn on **Enabled** and save again.
2. Start the partner — from the UI, or `deeptutor partner start <partner-id>`. If it is already running, restart it.
3. Send the bot a direct message, or @-mention it in a subscribed stream.
4. Once replies flow, replace `*` in **Allow From** with real user ids or emails.

Math survives the trip: the channel converts standard `$...$` and `$$...$$` in replies into Zulip's native KaTeX format.

## Verify it is healthy

A healthy Zulip channel has three signs:

- the log shows the event queue registered and the configured streams subscribed;
- a direct message to the bot gets a reply;
- an @-mention in a subscribed stream gets a reply in the same topic.

## Troubleshooting

### The bot never sees stream messages

Two usual causes. The bot is not subscribed to the stream — add it via Zulip's bot settings or **Subscribe Streams**. Or **Group Policy** is `mention` and the message did not @-mention the bot; mention it, or switch the policy to `open`.

### Authentication errors at startup

Re-check the trio: **Site** must be the full URL with the right realm subdomain, **Email** must be the bot's generated address, and **Api Key** must match that bot. Regenerating the key in Zulip invalidates the old one, so update the card after rotating.

### `BAD_EVENT_QUEUE_ID` in the log

Event queues expire after a server restart or long idle. The channel re-registers automatically — no action needed. If it repeats constantly, check the Zulip server's health.
