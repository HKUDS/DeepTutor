---
title: DingTalk
description: Configure the DingTalk channel for a Partner — internal app setup, Stream Mode connection, no public callback URL.
quadrant: how-to
---

<img src="/channel-icons/dingtalk.svg" alt="" width="40" height="40" />

The `dingtalk` channel connects a Partner to a DingTalk (钉钉) enterprise robot through the official `dingtalk-stream` SDK in **Stream Mode**: DeepTutor opens an outbound connection to DingTalk's servers to receive messages, so you need no public IP and no HTTP callback URL. Replies go back through DingTalk's HTTP API as markdown messages, in both DMs and group chats. If your organization lives on DingTalk, this is a two-credential setup — Client ID and Client Secret — and you are done.

![DingTalk channel configuration](/screenshots/dev/partners-channel-dingtalk.png)

While the Partner is running, use the card's live status as the first check: it should move from **Connecting** to **Connected**; open logs only for detail after a failed state.

## Install requirements

DingTalk support ships with the Partners extra; the underlying client is the official `dingtalk-stream` SDK — nothing extra to install.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Create an internal app on the Open Platform

1. Sign in to the [DingTalk Open Platform](https://open.dingtalk.com/) with an account that has developer access to your organization.
2. Go to **Application Development**, create an **Internal Application** (企业内部应用), and fill in the name, description, and icon.
3. In the app, add the **Robot** capability (应用能力 -> 机器人) and configure its display name and avatar.
4. In the robot's message settings, set the message receiving mode to **Stream Mode** instead of HTTP callback — this is what lets DeepTutor connect without a public URL.
5. On **Credentials & Basic Info**, copy the **Client ID** (AppKey) and **Client Secret** (AppSecret) — they go into the channel card.
6. **Release the app version.** A robot in draft state never receives Stream messages. After release, set the availability scope and add the robot in DingTalk (search for it in contacts, or add it to a group).

## Configure the channel card

Open **Partners -> your partner -> Channels -> DingTalk**.

Card fields for this channel are in the [channel schema](/channels/schema/#dingtalk).


Replies are sent as markdown messages, so headings, lists, and links render natively in DingTalk. Voice messages are handled too: DingTalk's built-in speech-to-text result is forwarded to the partner as plain text.

## After you save

1. Click **Save**, then turn **Enabled** on.
2. Start the partner (or restart it / use the reload action on the Channels panel if it is already running).
3. From an allowed account, find the robot in DingTalk and send it a short DM — or @mention it in a group it has been added to.
4. Watch the partner logs: you should see `Received DingTalk message from <name> (<id>)` followed by the reply delivery.
5. Once you have confirmed the sender id in the logs, replace `*` in **Allow From** with real ids.

## Verify it is healthy

- The logs show `DingTalk bot started with Stream Mode` and no recurring `Reconnecting DingTalk stream in 5 seconds...` lines.
- A short DM from an allowed account gets a markdown reply.
- In a group, @mentioning the robot produces an answer routed back to that group.

## Troubleshooting

### The stream keeps reconnecting

The channel retries every 5 seconds on disconnect, so an occasional reconnect line is harmless. A tight loop of them means the credentials are wrong or the network blocks DingTalk's endpoints — re-check **Client Id** / **Client Secret** first.

### `Failed to get DingTalk access token`

Replies need an access token fetched with the same credential pair. This error almost always means the **Client Secret** was rotated on the platform — copy the current value from Credentials & Basic Info and save again.

### Connected but no messages arrive

Three things to check on the platform side: the app version is **released** (drafts receive nothing), the message receiving mode is **Stream Mode**, and the robot is actually reachable — inside the availability scope and added to the conversation you are testing from.

### The bot never replies

Almost always **Allow From**. An empty list denies everyone — including you. Put `*` in for a first test, then switch to the staff id printed in the logs.

## See also

- [Channel Matrix](/channels/schema/) — all channels at a glance
- [Feishu](/channels/domestic/feishu/) — the other major Chinese workplace chat, same no-webhook model
