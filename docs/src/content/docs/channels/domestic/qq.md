---
title: QQ / NapCat
description: "Configure Tencent QQ channels for Partners: official QQ bot accounts and personal QQ through NapCat / OneBot v11."
quadrant: how-to
---

<img src="/channel-icons/qq.svg" alt="" width="40" height="40" />

DeepTutor has two QQ-family channels:

| Channel | Use when | Config key |
| --- | --- | --- |
| **QQ** | You have an official Tencent QQ bot account and app credentials. | `qq` |
| **QQ (NapCat)** | You want to connect a personal QQ account through NapCat / OneBot v11. | `napcat` |

For either path, use the selected card's live state as the first check while the Partner runs. It distinguishes a connected listener from missing configuration or an unavailable dependency before you inspect logs.

## Official QQ bot (`qq`)

Install the Partners extra, then create a bot in the [QQ Bot Development Platform](https://bot.q.qq.com/). Enable the message types you need, such as C2C/direct and group messages.

![Official QQ bot channel configuration](/screenshots/dev/partners-channel-qq.png)

Configuration fields:

Card fields for this channel are in the [channel schema](/channels/schema/#qq).


Start with:

```bash
deeptutor partner start <partner-id>
```

## Personal QQ through NapCat (`napcat`)

NapCat exposes a personal QQ account through a OneBot v11 WebSocket endpoint. Run NapCat separately, then point DeepTutor at its WebSocket URL.

![NapCat channel configuration](/screenshots/dev/partners-channel-napcat.png)

Configuration fields:

Card fields for this channel are in the [channel schema](/channels/schema/#qq).


## Choosing between them

Use `qq` for stable official bot deployments and group compliance. Use `napcat` for a personal-account workflow when you control the local NapCat runtime and understand the risk of personal-account automation.

## Production notes

- Prefer `qq` for official deployments where approval, compliance, and stable app credentials matter.
- Prefer `napcat` only when you intentionally run and maintain a local personal-account bridge.
- For group chats, start with mention-only behavior (`group_policy: mention`) and loosen it only after measuring noise.
- Keep `max_image_bytes` conservative when the Partner runs on a small server.

## Troubleshooting

- **Official QQ auth failed** — verify `app_id`, `secret`, and enabled message intents in Tencent's platform.
- **NapCat connects but no messages** — check `ws_url`, `access_token`, and whether NapCat is emitting OneBot v11 message events.
- **Group is too noisy** — set `group_policy` to `mention` or a low probability such as `0.1`.
