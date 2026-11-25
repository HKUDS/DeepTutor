---
title: 国内 IM
description: 内置的国内聊天渠道各自适合什么样的伙伴。
quadrant: explanation
---

这些渠道投递的是同一个伙伴。差别在于谁持有账号，以及连接怎么维持。

| 渠道 | 连接 | 适合 |
| --- | --- | --- |
| [个人微信](/zh-cn/channels/domestic/weixin/) | 扫码登录和 HTTP 长轮询 | 个人微信助手。需要有人扫码。 |
| [企业微信](/zh-cn/channels/domestic/wecom/) | 企业微信 AI Bot WebSocket | 企业微信 |
| [QQ / NapCat](/zh-cn/channels/domestic/qq/) | 官方机器人 WebSocket，或经 NapCat 的个人号 | 官方 QQ 机器人，或你有意桥接的个人 QQ |
| [飞书 / Lark](/zh-cn/channels/domestic/feishu/) | 开放平台 WebSocket 和 CardKit 卡片 | 飞书或 Lark 企业会话 |
| [钉钉](/zh-cn/channels/domestic/dingtalk/) | Stream Mode | 钉钉企业会话，不需要公网回调地址 |
| [Mochat](/zh-cn/channels/domestic/mochat/) | Socket.IO，失败时退回 HTTP 轮询 | 客服面板 |

先让一个渠道答上话，再加下一个。共用开关和每张卡片的字段在[渠道 schema](/zh-cn/channels/schema/)。
