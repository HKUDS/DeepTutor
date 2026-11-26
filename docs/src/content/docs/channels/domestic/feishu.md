---
title: Feishu
description: Configure the Feishu / Lark channel for a Partner — Open Platform app setup, WebSocket long connection, and CardKit streaming cards.
quadrant: how-to
---

<img src="/channel-icons/feishu.svg" alt="" width="40" height="40" />

The `feishu` channel connects a Partner to a Feishu (飞书) or Lark custom app through the official `lark-oapi` SDK over a **WebSocket long connection**: DeepTutor dials out to Feishu's servers, so you need no public IP, no webhook URL, and no reverse proxy. The same channel serves both mainland Feishu (`open.feishu.cn`) and international Lark (`open.larksuite.com`) apps, which makes it the natural choice for a workplace tutor inside a Chinese organization.

The channel also supports **Streaming**: with the switch on, replies render as CardKit streaming cards that fill in with a live typewriter effect while the answer is generated.

![Feishu channel configuration](/screenshots/dev/partners-channel-feishu.png)

While the Partner is running, use the card's live status as the first check: it should move from **Connecting** to **Connected**; open logs only for detail after a failed state.

## Install requirements

Feishu support ships with the Partners extra; the underlying client is the official `lark-oapi` SDK — nothing extra to install.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Quick setup: scan to create

The channel card includes a credential onboarding flow that can create and bind an app without copying credentials by hand:

1. Open **Partners -> your partner -> Channels -> Feishu** and click **Scan to connect**.
2. Scan the QR code (or open the authorization link) with the Feishu/Lark account that should administer the app.
3. When the status becomes **Scan completed**, click **Apply**.
4. DeepTutor saves the new App ID and App Secret, detects `feishu` versus `lark`, enables the channel, and adds the scanning user's open id to **Allow From**. Applying a new scan replaces the current app binding while preserving the other channel settings.
5. Start the Partner, or reload its channels if it is already running.

Use the manual path below when your organization's app policy requires you to create and approve the app yourself.

## Manual setup: create an app on the Open Platform

1. Open the [Feishu Open Platform](https://open.feishu.cn/) (or the [Lark Open Platform](https://open.larksuite.com/) for international tenants), go to the **Developer Console**, and create a **Custom App** with a name, description, and icon.
2. On **Credentials & Basic Info**, copy the **App ID** (`cli_...`) and **App Secret** — they go into the channel card.
3. **Features -> Bot**: enable the bot capability and give the bot a display name and avatar.
4. **Events & Callbacks**: switch the subscription mode to **Long Connection** so events arrive over WebSocket instead of a webhook, then subscribe to the `im.message.receive_v1` event.
5. **Permissions & Scopes**: grant the messaging scopes — at minimum `im:message` (read and send as bot); add `im:resource` if images, files, and audio should flow through. The default acknowledgement calls the message-reaction create API, so also grant permission to add message reactions. If you enable **Streaming**, grant CardKit permissions to create cards and update card content/settings.
6. **Create a version and release it.** For internal apps this is an internal release plus admin approval. Until a version is released, the bot receives nothing — this is the single most common setup mistake.

If you enable event encryption on the platform (under Events & Callbacks), also note the **Encrypt Key** and **Verification Token**; they must be mirrored into the channel card.

## Configure the channel card

Open **Partners -> your partner -> Channels -> Feishu**.

Card fields for this channel are in the [channel schema](/channels/schema/#feishu).


DeepTutor picks the outbound message format automatically: short plain text goes out as a text message, link-only content as a rich-text post, and anything with headings, code blocks, lists, or tables as an interactive card. Feishu allows one table per card, so multi-table replies are split across several cards.

## After you save

1. Click **Save**, then turn **Enabled** on.
2. Start the partner (or restart it / use the reload action on the Channels panel if it is already running).
3. From an allowed account, open a DM with the bot in Feishu and send a short message.
4. Watch the partner logs: you should see the inbound event, and your message should receive the React Emoji reaction almost immediately.
5. Once you have confirmed the `ou_...` sender id in the logs, replace `*` in **Allow From** with real ids.

## Verify it is healthy

- The logs show `Feishu bot started with WebSocket long connection` and no repeated `Feishu WebSocket error` lines (the channel auto-reconnects every 5 seconds if the connection drops).
- Your test message gets the React Emoji reaction right away — that confirms both inbound events and outbound API credentials work.
- The reply arrives; with **Streaming** on, you see a card filling in live instead of a single final message.

## Troubleshooting

### The bot receives nothing

Three gates must all be open: the app version is **released** (not draft), the `im.message.receive_v1` event is subscribed, and the subscription mode is **Long Connection**. A missing release is the most common cause — re-check it first.

### Messages arrive but replies fail

Usually a missing scope. Make sure `im:message` is granted, plus `im:resource` for media and message-reaction permission for the default acknowledgement. With **Streaming** enabled, also verify CardKit create/update permissions. Then **release a new version** — scope changes only take effect after release. The exact API error code appears in the partner logs.

### Events fail after enabling encryption

If you configured an Encrypt Key on the platform, the same value must be in the channel card (along with the Verification Token), and vice versa. After rotating either value on the platform, update the card and restart the partner.

### Streaming cards never stream

**Streaming** requires **Send Progress** to be on. If CardKit card creation fails (look for `Failed to create Feishu streaming card` in the logs), the channel falls back to sending a regular card at the end of the turn — the reply still arrives, just without the typewriter effect.

## See also

- [Channel Matrix](/channels/schema/) — all channels at a glance
- [DingTalk](/channels/domestic/dingtalk/) — the other major Chinese workplace chat, similar no-webhook model
