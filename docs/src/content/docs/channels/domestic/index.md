---
title: Domestic IM
description: Which built-in China-region chat channels fit which kind of partner.
quadrant: explanation
---

These channels deliver the same partner. They differ in who operates the account and how the connection is held.

| Channel | Connection | Fits |
| --- | --- | --- |
| [WeChat](/channels/domestic/weixin/) | QR login and HTTP long-poll | A personal WeChat assistant. A person has to scan. |
| [WeCom](/channels/domestic/wecom/) | WeCom AI Bot WebSocket | Enterprise WeChat / WeChat Work |
| [QQ / NapCat](/channels/domestic/qq/) | Official bot WebSocket, or a personal account through NapCat | An official QQ bot, or a personal QQ you intentionally bridge |
| [Feishu / Lark](/channels/domestic/feishu/) | Open Platform WebSocket and CardKit cards | Feishu or Lark enterprise chat |
| [DingTalk](/channels/domestic/dingtalk/) | Stream Mode | DingTalk enterprise chat, without a public callback URL |
| [Mochat](/channels/domestic/mochat/) | Socket.IO, with HTTP polling as fallback | A customer-support panel |

Use one channel until it answers, then add another. Shared switches and per-card fields are in the [channel schema](/channels/schema/).
