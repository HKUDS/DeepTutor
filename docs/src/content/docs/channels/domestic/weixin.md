---
title: WeChat (Personal Weixin)
description: Configure the personal WeChat channel for a Partner using QR-code login and HTTP long polling.
quadrant: how-to
---

<img src="/channel-icons/weixin.svg" alt="" width="40" height="40" />

The `weixin` channel connects a Partner to a personal WeChat account through the iLink long-poll API. It is different from **WeCom**: use this page for normal personal WeChat, and [WeCom](/channels/domestic/wecom/) for Enterprise WeChat / WeChat Work.

![WeChat channel configuration](/screenshots/dev/partners-channel-weixin.png)

The card owns both setup and runtime feedback: generate and scan the QR code there, then watch **Waiting for scan** become **Connected** without relying on a terminal QR.

## Install requirements

Personal WeChat support is included with the Partners extra. Browser QR rendering also uses `qrcode`.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Configure the channel card

Open **Partners -> your partner -> Channels -> WeChat**.

Card fields for this channel are in the [channel schema](/channels/schema/#weixin).


## Login flow

1. Leave the Partner stopped, open its WeChat channel card, and keep **Token** empty.
2. Press **Scan to connect**; the QR code is drawn in the browser.
3. Scan the code with WeChat and confirm on your phone. This onboarding step only writes the bot token (and any returned base URL) into the channel configuration; it does not start the Partner or begin long polling.
4. Make sure **Enabled** is on, then start the Partner from the UI or CLI. The channel loads the saved token and begins long polling.
5. Send a short message from an allowed account. Starting a token-less channel can still print a terminal QR code as a fallback, but browser onboarding before startup is the recommended flow.

```bash
deeptutor partner start <partner-id>
```

If the code expires, press **New code** (or restart the partner) and scan the refreshed one. The implementation refreshes expired QR codes a few times, but it cannot complete login without a human scan.

## Verify it is healthy

A healthy WeChat channel has three signs:

- the scan reports the bot token was saved, and an account state exists;
- `data/partners/<partner-id>/channels/weixin/account.json` exists in the mounted `data/` tree;
- a short message from an allowed sender produces a Partner reply.

For Docker, make sure `data/partners/` is persisted. Otherwise every container restart can require a fresh scan.

## Access control

`Allow From` is enforced before messages enter the partner brain. During the first test, `*` is fine. For production, replace it with specific user ids after you observe inbound sender ids in logs.

## Troubleshooting

### The channel starts but asks for QR login every time

Check whether `State Dir` points to a writable location. If blank, DeepTutor writes under the Partner's `channels/weixin/` directory. If that directory is not persisted in Docker, the token disappears on restart.

### Messages arrive but replies fail

WeChat replies require a recent `context_token` from inbound messages. If the account has been idle for too long, send a fresh inbound message and let DeepTutor refresh the context before replying.

### Too many progress messages

Disable **Send Progress** or **Send Tool Hints** on the channel card. This does not change the partner's reasoning; it only changes what is delivered to WeChat.
