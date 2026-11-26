---
title: Mochat
description: 通过 Socket.IO（自动回退 HTTP 轮询）把 Partner 接入 Mochat 客服面板。
quadrant: how-to
---

<img src="/channel-icons/mochat.svg" alt="" width="40" height="40" />

`mochat` channel 把 Partner 接到 Mochat——一个客服式的聊天面板。它通过 **Socket.IO** 和你的 Mochat 实例通信，socket 连不上时自动回退到 **HTTP polling**，所以在挑剔的代理后面也能继续工作。适合想把 Partner 嵌进客服组件、而不是个人聊天软件的场景。

![Mochat 渠道配置](/screenshots/dev/partners-channel-mochat.png)

Partner 运行时先看卡片实时状态：它会显示 Socket.IO 已连接或 listener 已启动；只有失败时才用日志查看 transport 细节。

## 安装依赖

Mochat 支持包含在 Partners extra 里，会带上 `python-socketio` 和 `msgpack`。没有 `python-socketio` 时，channel 仍可在 polling 模式下工作。

```bash
python scripts/install_extras.py partners
# 或发布包支持 extras 时：
pip install "deeptutor[partners]"
```

## 获取 Claw Token

在 Mochat 管理后台创建一个 bot 账号，复制它的 **Claw Token**。没有它 channel 会拒绝启动（日志里是 `Mochat claw_token not configured`）。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Mochat**。

这张卡片的字段见[渠道 schema](/zh-cn/channels/schema/#mochat)。


### 进阶字段

这些用来调重试和群行为；首次部署用默认值就好。

这张卡片的字段见[渠道 schema](/zh-cn/channels/schema/#mochat)。


默认的 reply-delay 模式下，连珠炮式的 panel 消息会合并成一个 Partner turn：每来一条新消息计时器就重置，而直接 @ bot 会让缓冲立刻被处理。

## 保存之后

1. 打开 **Enabled**、填好 **Claw Token**，保存 card。
2. 从 UI 或 CLI 启动（或重启）partner。
3. 看日志：socket 连接成功，或 polling 回退警告——两种都能正常工作。
4. 在被监听的 session 或 panel 里发一条短消息。
5. 在日志里看到真实 user id 之后，把 **Allow From** 里的 `*` 换成明确的值。

```bash
deeptutor partner start <partner-id>
```

## 如何确认健康

健康的 Mochat channel 通常有三个迹象：

- 日志显示 Socket.IO 连接成功（或明确的 polling 回退，而不是认证错误）；
- `data/partners/<partner-id>/channels/mochat/session_cursors.json` 在持续写入——这是监听位点；
- 允许的用户发一条短消息后，Partner 能正常回复。

Docker 部署要持久化 `data/partners/`，让 cursor 在重启后还在。

## 常见问题

### Socket.IO 一直重连或根本连不上

对照你的 Mochat 部署检查 **Socket Url** / **Socket Path**。服务端不支持 msgpack 就打开 **Socket Disable Msgpack**。也可以干脆不管它：channel 会自己回退到 HTTP polling，用一点延迟换稳定。

### channel 一启动就退出

日志里是 `Mochat claw_token not configured`。填好 **Claw Token**，重启 partner。

### 订阅失败 / token 失效

`Mochat subscribePanels failed` 之类的日志通常意味着 Claw Token 无效、过期，或 bot 没在 Mochat 管理后台通过审批。重新生成 token，更新 card，重启。

### 连上了但收不到消息

确认 **Sessions** 或 **Panels** 确实填了内容（或 `*`），并且发送者能通过 **Allow From**。群 session 还要看是否配置了 mention 要求。
