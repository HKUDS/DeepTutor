---
title: DingTalk（钉钉）
description: 为 Partner 配置钉钉渠道——企业内部应用、Stream Mode 连接、无需公网回调。
quadrant: how-to
---

<img src="/channel-icons/dingtalk.svg" alt="" width="40" height="40" />

`dingtalk` channel 通过官方 `dingtalk-stream` SDK 的 **Stream Mode** 把 Partner 接到钉钉企业机器人上：收消息走 DeepTutor 主动发起的出站连接，不需要公网 IP，也不需要 HTTP 回调地址；回复走钉钉 HTTP API，以 markdown 消息发出，私聊和群聊都支持。如果你的组织用钉钉，整个接入只需要两个凭证——Client ID 和 Client Secret。

![钉钉渠道配置](/screenshots/dev/partners-channel-dingtalk.png)

Partner 运行时先看卡片实时状态：它应从 **Connecting** 进入 **Connected**；只有失败状态需要更多细节时再查日志。

## 安装依赖

钉钉支持已包含在 Partners extra 里，底层是官方 `dingtalk-stream` SDK，不需要额外安装任何东西。

```bash
python scripts/install_extras.py partners
# 或发布包支持 extras 时：
pip install "deeptutor[partners]"
```

## 在开放平台创建企业内部应用

1. 用有开发权限的账号登录[钉钉开放平台](https://open.dingtalk.com/)。
2. 进入**应用开发**，创建一个**企业内部应用**，填好名称、描述、图标。
3. 在应用里添加**机器人**能力（应用能力 -> 机器人），配置机器人的名称和头像。
4. 在机器人的消息接收设置里，把接收模式选为 **Stream 模式**（不是 HTTP 回调）——免公网地址全靠它。
5. 在**凭证与基础信息**页复制 **Client ID**（AppKey）和 **Client Secret**（AppSecret），待会儿填进 channel card。
6. **发布应用版本。** 草稿状态的机器人收不到任何 Stream 消息。发布后设置好可用范围，再在钉钉里把机器人加上（通讯录里搜索，或拉进群）。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> DingTalk**。

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 实时发过来。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Client Id** | 凭证与基础信息页的 AppKey（一般 `ding...` 开头）。 |
| **Client Secret** | 同页的 AppSecret。按 secret 存储，保存后会打码。 |
| **Allow From** | 一行一个值。测试可填 `*` 表示开放；正式用换成钉钉 staff id（每条入站消息的 sender id 都会打在 partner 日志里）。空列表会拒绝所有人。 |

回复以 markdown 消息发出，标题、列表、链接在钉钉里都能正常渲染。语音消息也能处理：钉钉自带的语音转文字结果会以纯文本转给 partner。

## 保存之后

1. 点 **Save**，把 **Enabled** 打开。
2. 启动 partner（已在运行的话重启，或在 Channels 面板上用 reload）。
3. 用允许的账号在钉钉里找到机器人，私聊发一条短消息——或在它所在的群里 @ 它。
4. 看 partner 日志：能看到 `Received DingTalk message from <name> (<id>)`，随后是回复投递。
5. 在日志里确认 sender id 之后，把 **Allow From** 里的 `*` 换成真实 id。

## 如何确认健康

- 日志出现 `DingTalk bot started with Stream Mode`，且没有反复刷 `Reconnecting DingTalk stream in 5 seconds...`。
- 允许的账号私聊一条短消息，能收到 markdown 回复。
- 在群里 @ 机器人，回答会路由回那个群。

## 常见问题

### Stream 连接反复重连

掉线后 channel 每 5 秒自动重试，偶尔一条重连日志无伤大雅；连成一串刷屏就是凭证错了或网络到不了钉钉的服务端——先重查 **Client Id** / **Client Secret**。

### `Failed to get DingTalk access token`

发消息要用同一对凭证换 access token。出这个错基本就是 **Client Secret** 在平台上被轮换过——去凭证与基础信息页抄最新的值，重新保存。

### 连上了但收不到消息

平台侧查三件事：应用版本**已发布**（草稿收不到）、消息接收模式是 **Stream 模式**、机器人确实够得着——在可用范围内，并且已经加进你测试用的会话。

### 机器人从不回复

几乎都是 **Allow From** 的问题。空列表会拒绝所有人——包括你自己。先填 `*` 测一轮，再换成日志里打印的 staff id。

## 相关页面

- [Channel Matrix](/zh-cn/partners/channels/) — 所有 channel 一览
- [Feishu](/zh-cn/partners/feishu/) — 另一大国内办公 IM，同样免 webhook
