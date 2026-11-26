---
title: Microsoft Teams
description: Configure the Microsoft Teams channel for a Partner — Azure Bot registration, public messaging endpoint, and inbound JWT validation.
quadrant: how-to
---

<img src="/channel-icons/msteams.svg" alt="" width="40" height="40" />

The `msteams` channel connects a Partner to Microsoft Teams through the **Bot Framework**. Unlike every other DeepTutor channel, it does not dial out: it runs a small **built-in HTTP server** (default `0.0.0.0:3978`, path `/api/messages`) and Microsoft's servers POST each message to it. That means you need a **publicly reachable HTTPS endpoint** — in production, put a reverse proxy (nginx, Caddy, a Cloudflare Tunnel) in front of the port and point the Azure Bot's messaging endpoint at it. For local testing, a tunnel like `ngrok http 3978` works fine.

**Give every enabled Teams Partner a unique bind port.** Each Partner starts its own HTTP server, so two running Teams channels cannot share the same host/port pair. Route each Partner's public messaging endpoint to its assigned port.

The current scope is DM-first: text in, text out. Group and channel messages are ignored, and attachments are not yet supported.

![Microsoft Teams channel configuration](/screenshots/dev/partners-channel-msteams.png)

While the Partner is running, use the card's live status first: **Listener running** confirms the webhook server is bound, while failed states identify a bind or configuration problem before logs.

## Install requirements

Teams support ships with the Partners extra. Inbound requests are verified with `PyJWT[crypto]`, which is already included — nothing extra to install.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Register a bot with Azure

1. In the [Azure Portal](https://portal.azure.com/), open **Microsoft Entra ID -> App registrations -> New registration**. Name it, pick the supported account types (single tenant is fine), and register. Copy the **Application (client) ID** — this becomes **App Id** — and the **Directory (tenant) ID** — this becomes **Tenant Id**.
2. In the registration, open **Certificates & secrets -> New client secret**. Copy the secret **Value** immediately (it is shown only once) — this becomes **App Password**.
3. Create an **Azure Bot** resource (search for "Azure Bot" in the marketplace). Under *Microsoft App ID*, choose **Use existing app registration** and paste your App Id. Match the bot's tenancy type to the registration: a single-tenant registration needs a single-tenant bot.
4. In the bot resource, go to **Settings -> Configuration** and set the **Messaging endpoint** to your public HTTPS address ending in the channel path, e.g. `https://bots.example.com/api/messages`.
5. Go to **Settings -> Channels** and add the **Microsoft Teams** channel.
6. To start chatting, use the **Open in Teams** link on the Teams channel line. For org-wide distribution, package a Teams app manifest that references the same App Id.

## Configure the channel card

Open **Partners -> your partner -> Channels -> Microsoft Teams**.

Card fields for this channel are in the [channel schema](/channels/schema/#msteams).


## After you save

1. Click **Save**, then turn **Enabled** on.
2. Start the partner (or restart it / use the reload action on the Channels panel if it is already running).
3. Check that the endpoint is reachable from outside: `curl -X POST https://your-domain/api/messages -H 'Content-Type: application/json' -d '{}'` should return **401** (the JWT check rejecting you) — a connection error means the proxy path is broken.
4. From an allowed account, open the bot in Teams (the **Open in Teams** link) and send a short DM.
5. Once you have confirmed the sender id in the logs, replace `*` in **Allow From** with real ids.

## Verify it is healthy

- The logs show `MSTeams webhook listening on http://0.0.0.0:3978/api/messages` at startup.
- An unauthenticated POST to the public endpoint returns 401, not a timeout — the proxy chain works and the JWT gate is up.
- A DM from an allowed account gets a reply, and `data/partners/<partner-id>/channels/msteams/msteams_conversations.json` appears — conversation references are being persisted.

## Troubleshooting

### Teams reports the message could not be sent

The messaging endpoint is unreachable. Confirm the endpoint URL ends with your **Path**, the certificate is valid HTTPS, and the reverse proxy forwards to **Host**:**Port**. The `curl` probe from the checklist above isolates this in one step.

### Every inbound request is rejected with 401

Inbound JWT validation is failing. The most common cause is an **App Id** mismatch between the channel card and the bot registration — the token's audience must equal the App Id. If you recently recreated the registration, update the card. Do not work around this by disabling **Validate Inbound Auth** outside local testing.

### Replies fail with a token error

The channel could receive but cannot authenticate to send. This is the tenant trap: a **single-tenant** registration with **Tenant Id** left blank makes DeepTutor request tokens from the multi-tenant endpoint, which Microsoft rejects. Set **Tenant Id** to the Directory (tenant) ID and save.

### The bot answers DMs but ignores group chats and channels

By design: the channel is currently DM-only. Non-personal conversations are dropped on arrival (and pruned from stored references when **Prune Non Personal Refs** is on).

## See also

- [Channel Matrix](/channels/schema/) — all channels at a glance
- [Slack](/channels/international/slack/) — the other big workplace platform, Socket Mode instead of a public endpoint
