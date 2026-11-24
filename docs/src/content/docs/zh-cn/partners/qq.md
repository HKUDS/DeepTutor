---
title: QQ / NapCat
description: 为 Partner 配置腾讯 QQ 渠道：官方 QQ Bot 与 NapCat / OneBot v11 个人 QQ。
quadrant: how-to
---

<img src="/channel-icons/qq.svg" alt="" width="40" height="40" />

DeepTutor 有两个 QQ 系渠道：

| 渠道 | 适用场景 | 配置 key |
| --- | --- | --- |
| **QQ** | 你有腾讯官方 QQ Bot 账号和应用凭证。 | `qq` |
| **QQ (NapCat)** | 你想通过 NapCat / OneBot v11 接入个人 QQ。 | `napcat` |

无论走哪条路径，Partner 运行时都先看所选卡片的实时状态。它会在查日志前区分 listener 已连接、缺少配置或依赖不可用。

## 官方 QQ Bot（`qq`）

先安装 Partners extra，然后在 [QQ Bot 开发平台](https://bot.q.qq.com/) 创建 bot。按需要开启 C2C/direct 和群消息等消息类型。

![官方 QQ Bot 渠道配置](/screenshots/dev/partners-channel-qq.png)

配置字段：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否随 partner 启动该渠道。 |
| `app_id` | 腾讯 bot 平台里的 App ID。 |
| `secret` | Bot secret。 |
| `allow_from` | 允许访问的 QQ user ids / openids。空列表拒绝访问；生产环境建议明确 id。 |
| `msg_format` | `plain` 或 `markdown`。不同 QQ 客户端 Markdown 表现不一，不确定时先用 `plain`。 |

启动：

```bash
deeptutor partner start <partner-id>
```

## 通过 NapCat 接入个人 QQ（`napcat`）

NapCat 会把个人 QQ 暴露成 OneBot v11 WebSocket endpoint。你需要单独运行 NapCat，然后把 DeepTutor 指向它的 WebSocket URL。

![NapCat 渠道配置](/screenshots/dev/partners-channel-napcat.png)

配置字段：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否随 partner 启动该渠道。 |
| `ws_url` | NapCat WebSocket endpoint，默认 `ws://127.0.0.1:3001`。 |
| `access_token` | 可选 OneBot access token。 |
| `allow_from` | 允许访问的用户 id。`*` 只建议本地测试使用。 |
| `group_policy` | `mention`、`open`，或 `0` 到 `1` 的概率。被 @ 或回复时总会响应。 |
| `group_policy_overrides` | 按群 id 覆盖 group policy 的 map。 |
| `welcome_new_members` | 是否欢迎新群成员。 |
| `max_image_bytes` | 入站图片下载大小上限。 |

## 怎么选

正式部署、合规群机器人优先用 `qq`。如果你需要个人 QQ 工作流，并且能控制本地 NapCat 运行时、理解个人账号自动化风险，再用 `napcat`。

## 生产环境建议

- 正式部署、需要审批和稳定应用凭证时，优先用 `qq`。
- 只有在你明确要维护本地个人账号桥接时，才用 `napcat`。
- 群聊先从 mention-only 行为开始（`group_policy: mention`），确认噪音可控后再放宽。
- 小服务器上运行 Partner 时，`max_image_bytes` 保守一些。

## 常见问题

- **官方 QQ auth failed** —— 检查 `app_id`、`secret` 和腾讯平台启用的消息 intents。
- **NapCat 连接了但没有消息** —— 检查 `ws_url`、`access_token`，以及 NapCat 是否在发 OneBot v11 message events。
- **群里太吵** —— 把 `group_policy` 设为 `mention`，或较低概率如 `0.1`。
