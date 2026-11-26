---
title: WeCom (WeChat Work)
description: Configure Enterprise WeChat / WeCom AI Bot delivery for a Partner.
quadrant: how-to
---

<img src="/channel-icons/wecom.svg" alt="" width="40" height="40" />

Use `wecom` for Enterprise WeChat / WeChat Work. It connects through the WeCom AI Bot WebSocket long connection and is different from personal [WeChat (`weixin`)](/channels/domestic/weixin/).

![WeCom channel configuration](/screenshots/dev/partners-channel-wecom.png)

The card owns both setup and runtime feedback: complete QR onboarding there, then treat **Connected** as the primary check and use logs only for additional protocol detail.

## Requirements

- A WeCom organization with admin access.
- The `wecom-aibot-sdk` Python package. Install via the Partners extra or directly if needed.

```bash
python scripts/install_extras.py partners
python -c "import wecom_aibot_sdk; print('ok')"
```

## Quick setup: scan to connect

The WeCom channel card can obtain and save the bot credentials through QR onboarding:

1. Open **Partners -> your partner -> Channels -> WeCom** and click **Scan to connect**.
2. Scan the QR code with an authorized WeCom account, or open the authorization link shown beside it.
3. Wait for **Scan completed**, then click **Apply**. DeepTutor writes the returned Bot ID and Secret, enables the channel, and reloads it when the Partner is already running.
4. The scan flow keeps an existing **Allow From** list; when none exists, it uses `*`. Restrict that allowlist immediately if the bot is reachable by more users than intended.

Use the manual Bot ID / Secret path below when QR onboarding is not suitable for your organization.

## Manual setup: create the bot in WeCom

1. Sign in to <https://work.weixin.qq.com/>.
2. Open **Applications & Mini Programs -> AI Bot Platform**.
3. Create an **AI Bot** application.
4. Configure name, description, visible departments/users, and any required approval settings.
5. Copy **Bot ID** and **Secret**.

## Configure DeepTutor

Open **Partners -> your partner -> Channels -> WeCom** and fill:

Card fields for this channel are in the [channel schema](/channels/schema/#wecom).


## Access control and visibility

WeCom has two layers of access control:

1. WeCom application visibility controls who can open the AI Bot inside the organization.
2. DeepTutor `allow_from` controls which sender ids are allowed into the Partner runtime.

During first setup, keep the WeCom visible range small and set `allow_from` explicitly once you know the sender ids from logs.

## Start and test

```bash
deeptutor partner start <partner-id>
```

The server log should show a WeCom WebSocket connection and authentication. Then open the AI Bot in WeCom and send a short message.

## Troubleshooting

- **`ImportError: wecom_aibot_sdk`** — install `wecom-aibot-sdk` or the Partners extra in the same environment running DeepTutor.
- **Connects but no reply** — check `allow_from`, department visibility, and whether the sender is allowed to use the AI Bot application.
- **Disconnects** — transient disconnects auto-reconnect. If it stays offline, verify Bot ID / Secret and outbound network access to WeCom.
