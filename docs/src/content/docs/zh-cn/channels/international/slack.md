---
title: Slack
description: 为 Partner 配置 Slack channel —— Socket Mode 应用、bot 和 app 两个 token、线程回复与 DM 策略。
quadrant: how-to
---

<img src="/channel-icons/slack.svg" alt="" width="40" height="40" />

`slack` channel 通过 **Socket Mode** 把 Partner 接进 Slack workspace：bot 用 `slack-sdk` 向 Slack 开一条 WebSocket，所以不需要公网 URL、webhook 或反向代理。它是最面向团队的 channel —— 支持 DM、频道 @ 提及、线程回复，还会在触发消息上加一个确认 reaction。

这里涉及两个 token，很容易搞混：**Bot Token**（`xoxb-…`，来自 OAuth & Permissions）授权 API 调用，**App Token**（`xapp-…`，来自 Socket Mode）授权 WebSocket 连接。和 Telegram、Discord 不同，Slack 的 card 上没有 **Streaming** 开关 —— 回复以完整消息送达，开了 **Send Progress** 的话 narration 会作为单独的消息投递。

![Slack 渠道配置](/screenshots/dev/partners-channel-slack.png)

Partner 运行时先看卡片实时状态：它应从 **Connecting** 进入 **Connected**；只有失败状态需要更多细节时再查日志。

## 安装依赖

Slack 支持随 Partners extra 一起安装，其中已包含 `slack-sdk`（Socket Mode 客户端）和 `slackify-markdown`（Markdown -> Slack mrkdwn 转换）。不需要额外装任何东西。

```bash
python scripts/install_extras.py partners
# 或发布包支持 partners extras 时：
pip install "deeptutor[partners]"
```

## 创建 Slack 应用

1. 打开 <https://api.slack.com/apps> -> **Create New App** -> **From scratch**。起个名字，选你的 workspace。
2. 左侧边栏 -> **Socket Mode** -> 打开 **Enable Socket Mode**。按提示生成一个带 `connections:write` scope 的 App-Level Token 并复制 —— 这就是你的 **App Token**（`xapp-…`）。
3. 左侧边栏 -> **OAuth & Permissions** -> **Scopes** -> **Bot Token Scopes**，加上：`chat:write`、`chat:write.public`、`files:write`、`reactions:write`、`app_mentions:read`、`im:history`、`im:read`、`channels:history`（要支持私有频道再加 `groups:history`）。适配器用 `auth.test` 获取自己的 bot id，不会调用 users API，因此不需要 `users:read`。
4. 左侧边栏 -> **Event Subscriptions** -> **Subscribe to bot events**：`app_mention`、`message.im`；如果 bot 要在频道里听 @ 之外的消息，再加 `message.channels`。
5. 回到 **OAuth & Permissions**，点 **Install to Workspace** 并授权。复制 **Bot User OAuth Token**（`xoxb-…`）—— 这就是你的 **Bot Token**。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Slack**。

这张卡片的字段见[渠道 schema](/zh-cn/channels/schema/#slack)。


## 保存之后

1. 点 **Save**，再把 **Enabled** 打开。
2. 启动 partner（已经在跑的话重启它，或在 Channels 面板用 reload）。
3. 用允许的账号 DM bot，或 `/invite @your-bot` 进某个频道再 @ 它。
4. 看 partner 日志：应该能看到 Socket Mode 连接和入站事件。
5. 在日志里确认 sender id 之后，把 **Allow From** 里的 `*` 换成真实 id。

## 如何确认健康

- 日志显示 Socket Mode WebSocket 已连接，没有鉴权错误。
- 你的测试消息一两秒内就收到确认 reaction（默认 `eyes`）。
- 默认 **Reply In Thread** 开着时，回复出现在你消息下面的线程里。

## 常见问题

### Slack API 报 `invalid_auth` / `not_authed`

两个 token 填反了 —— `xoxb-…` 应该在 **Bot Token**，`xapp-…` 应该在 **App Token**。这是 Slack 配置里最常见的一个错误。

### socket 一直连不上

应用必须先**启用** Socket Mode，且 App-Level Token 必须带 `connections:write` scope。如果 token 是在启用 Socket Mode 之前生成的，重新生成一个。

### 频道消息不理，DM 正常

三道门都要查：

1. bot 必须被邀请进该频道：`/invite @your-bot`。
2. **Group Policy** = `mention` 时，消息必须 @ 到 bot。
3. **Event Subscriptions** 下必须订阅了 `app_mention` 这个 bot event（依赖频道普通消息的话，还要 `message.channels`）。

### 回复进了线程，没 @ 的后续消息没人理

**Reply In Thread** 只决定 bot 把回答发到哪里，不会绕过频道的 mention gate。**Group Policy** = `mention` 时，线程里的每条后续消息仍要 @ bot；如果希望线程里每条消息都可触发回复，把策略改成 `open`。只有想让回复平铺到频道时，才需要关闭 **Reply In Thread**。

## 相关页面

- [Channel Matrix](/zh-cn/channels/schema/) —— 所有 channel 一览
- [Discord](/zh-cn/channels/international/discord/) —— 类似的开发者后台配置，走 Gateway WebSocket
