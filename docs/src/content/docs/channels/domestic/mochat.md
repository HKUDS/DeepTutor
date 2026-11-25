---
title: Mochat
description: Connect a Partner to a Mochat customer-support panel over Socket.IO with automatic HTTP polling fallback.
quadrant: how-to
---

<img src="/channel-icons/mochat.svg" alt="" width="40" height="40" />

The `mochat` channel connects a Partner to Mochat, a customer-support style chat panel. It talks to your Mochat instance over **Socket.IO** and falls back to **HTTP polling** automatically when the socket cannot connect, so the channel keeps working behind picky proxies. Useful when you want a Partner embedded in a support widget rather than a personal messenger.

![Mochat channel configuration](/screenshots/dev/partners-channel-mochat.png)

While the Partner is running, use the card's live status first: it reports whether Socket.IO connected or the listener is active; open logs only for transport detail after a failed state.

## Install requirements

Mochat support is included with the Partners extra, which carries `python-socketio` and `msgpack`. Without `python-socketio` the channel still works in polling mode.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Get a Claw Token

In your Mochat admin panel, create a bot account and copy its **Claw Token**. The channel refuses to start without it (`Mochat claw_token not configured` in the log).

## Configure the channel card

Open **Partners -> your partner -> Channels -> Mochat**.

Card fields for this channel are in the [channel schema](/channels/schema/#mochat).


### Advanced fields

These tune retries and group behavior; the defaults are fine for a first deployment.

Card fields for this channel are in the [channel schema](/channels/schema/#mochat).


With the default reply-delay mode, rapid-fire panel messages are batched into one Partner turn: each new message restarts the timer, and a direct @-mention flushes the buffer immediately.

## After you save

1. Save the card with **Enabled** on and **Claw Token** filled.
2. Start (or restart) the partner from the UI or CLI.
3. Check the log: a socket connection, or a polling-fallback warning — both are workable.
4. Send a short message in a watched session or panel.
5. Once you see real user ids in the logs, replace `*` in **Allow From** with explicit values.

```bash
deeptutor partner start <partner-id>
```

## Verify it is healthy

A healthy Mochat channel has three signs:

- the log shows a Socket.IO connection (or an explicit polling fallback, not an auth error);
- `data/partners/<partner-id>/channels/mochat/session_cursors.json` is being written — this is the watch position;
- a short message from an allowed user produces a Partner reply.

For Docker, persist `data/partners/` so cursors survive restarts.

## Troubleshooting

### Socket.IO keeps reconnecting or never connects

Check **Socket Url** / **Socket Path** against your Mochat deployment. If the server cannot speak msgpack, turn on **Socket Disable Msgpack**. You can also just let it run: the channel falls back to HTTP polling on its own, trading a little latency for robustness.

### Channel exits immediately

The log says `Mochat claw_token not configured`. Fill **Claw Token** and restart the partner.

### Subscriptions fail / token stopped working

Log lines like `Mochat subscribePanels failed` usually mean the Claw Token is invalid, expired, or the bot was not approved in the Mochat admin panel. Regenerate the token, update the card, and restart.

### Connected, but no messages come in

Check that **Sessions** or **Panels** actually lists something (or `*`), and that the sender passes **Allow From**. In group sessions, also check whether a mention requirement is configured.
