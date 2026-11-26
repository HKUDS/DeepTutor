---
title: 海外 IM
description: 内置的海外渠道和异步渠道各自适合什么样的伙伴。
quadrant: explanation
---

这些渠道把同一个伙伴送到国内那一组之外。邮件放在这里，是因为它是异步收件箱，不是某个地区的即时通讯。

| 渠道 | 连接 | 适合 |
| --- | --- | --- |
| [Telegram](/zh-cn/channels/international/telegram/) | Bot API 长轮询 | 最短的配置：一个 BotFather token，不需要公网地址 |
| [Discord](/zh-cn/channels/international/discord/) | Gateway WebSocket | Discord 服务器或私信 |
| [Slack](/zh-cn/channels/international/slack/) | Socket Mode | Slack 工作区，包括线程 |
| [Microsoft Teams](/zh-cn/channels/international/msteams/) | Bot Framework webhook | Teams，需要一个公网消息端点 |
| [WhatsApp](/zh-cn/channels/international/whatsapp/) | 外部 bridge | 通过那个 bridge 运行时接入 WhatsApp |
| [Matrix](/zh-cn/channels/international/matrix/) | 对 homeserver 做 sync | 你选定的 homeserver 上的房间，加密可选 |
| [Zulip](/zh-cn/channels/international/zulip/) | 事件队列 | 按 stream 和 topic 组织的会话 |
| [Mattermost](/zh-cn/channels/international/mattermost/) | 原生 v4 WebSocket | 你自己托管的 Mattermost |
| [邮件](/zh-cn/channels/international/email/) | IMAP 轮询和 SMTP 回信 | 可以接受延迟回复的收件箱 |

共用开关和每张卡片的字段在[渠道 schema](/zh-cn/channels/schema/)。
