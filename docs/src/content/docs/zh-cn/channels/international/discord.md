---
title: Discord
description: 为 Partner 配置 Discord channel —— Developer Portal 应用、Gateway WebSocket、intents、原地编辑的流式回复。
quadrant: how-to
---

<img src="/channel-icons/discord.svg" alt="" width="40" height="40" />

`discord` channel 通过 **Gateway WebSocket**（API v10）把 Partner 接到一个 Discord bot 上。DeepTutor 直接实现 gateway 协议 —— 不依赖 `discord.py` —— 心跳和重连都自己处理。和 Telegram 一样，不需要公网 IP 或 webhook；是 bot 主动拨出去连 Discord。

支持 **Streaming**：开关打开后，bot 只发一条消息，随着回复生成不断通过 REST API patch 它，让回答原地长出来。

![Discord 渠道配置](/screenshots/dev/partners-channel-discord.png)

Partner 运行时先看卡片实时状态：它应从 **Connecting** 进入 **Connected**；只有失败状态需要更多细节时再查日志。

## 安装依赖

Discord 支持随 Partners extra 一起安装；gateway 客户端基于 `websockets` 实现，已经包含在内。

```bash
python scripts/install_extras.py partners
# 或发布包支持 partners extras 时：
pip install "deeptutor[partners]"
```

## 创建 Discord 应用

1. 打开 <https://discord.com/developers/applications>，点 **New Application**，起个名字。
2. 左侧边栏进 **Bot**。在 **TOKEN** 下点 **Reset Token**，复制出来 —— 这就是要填进 **Token** 字段的值。
3. 还在 **Bot** 页，在 **Privileged Gateway Intents** 下启用 **MESSAGE CONTENT INTENT**。不开的话 bot 收到的消息正文是空的。**Server Members Intent** 可开可不开。
4. 把 bot 邀请进你的服务器：**OAuth2** -> **URL Generator**，勾上 `bot` scope，再勾权限 `Send Messages`、`Read Message History` 和 `Attach Files`。打开生成的 URL，选服务器，**Authorize**。适配器不会添加 reaction，也不会发送 embed，因此不需要对应权限。
5. 收集 **Allow From** 要用的用户 id：Discord 设置 -> **Advanced** -> 打开 **Developer Mode**，然后右键任意用户 -> **Copy User ID**。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Discord**。

这张卡片的字段见[渠道 schema](/zh-cn/channels/schema/#discord)。


超过 Discord 2000 字符上限的回复会自动拆成多条消息。

## 保存之后

1. 点 **Save**，再把 **Enabled** 打开。
2. 启动 partner（已经在跑的话重启它，或在 Channels 面板用 reload）。
3. 用允许的账号私聊 bot，或在服务器频道里 @ 它。
4. 看 partner 日志：应该能看到 gateway 连接、入站消息和回复投递。
5. 在日志里确认 sender id 之后，把 **Allow From** 里的 `*` 换成真实 id。

## 如何确认健康

- 日志显示 gateway 已连接、心跳正常，没有反复重连。
- bot 在服务器成员列表里显示 **online**。
- 允许的账号私聊能收到回复，服务器频道里 @ 它也能收到。

## 常见问题

### gateway 以 `4014: Disallowed intent` 断开

**Intents** 这个数字请求了某个未在 Developer Portal 启用的特权 intent。最常见的就是 Message Content：打开你的应用 -> **Bot** -> 启用 **MESSAGE CONTENT INTENT**，然后重启 partner。

### bot 在线但从来不回复

查两个地方：

1. **Allow From** —— 空列表拒绝所有人。先用 `*` 测试，再换成你的真实用户 id。
2. **MESSAGE CONTENT INTENT** —— 不开的话，服务器消息送达时 `content` 是空的，bot 无话可答。去 portal 里启用。

### 服务器频道里不回复，私聊正常

**Group Policy** = `mention` 时，消息必须真的 @ 到 bot。另外确认邀请 bot 时给了它在该频道的 `Send Messages` 和 `Read Message History` 权限。

### Streaming 开了但没有流式效果

**Streaming** 依赖 **Send Progress** —— 两个都要打开。另外 Discord 对消息编辑有频率限制，原地更新是一块一块到的，不会逐字蹦出来；这是正常现象。

## 相关页面

- [Channel Matrix](/zh-cn/channels/schema/) —— 所有 channel 一览
- [Telegram](/zh-cn/channels/international/telegram/) —— 更简单的 polling 模型，同一个流式开关
- [Slack](/zh-cn/channels/international/slack/) —— 类似的开发者后台配置体验，走 Socket Mode
