---
title: Mattermost
description: 为 Partner 配置 Mattermost channel —— bot 账号 access token、原生 v4 WebSocket + REST、线程回复、自托管 TLS。
quadrant: how-to
---

<img src="/channel-icons/mattermost.svg" alt="" width="40" height="40" />

`mattermost` channel 通过 Mattermost 的**原生 v4 API** 把 Partner 接到一台自托管的 **Mattermost** 服务器上 —— 事件走 WebSocket（`/api/v4/websocket`），发送走 REST（`/api/v4`）。DeepTutor 直接实现 Mattermost 协议 —— 不依赖 `mattermostdriver`，底层和 Discord 一样是 `httpx` + `websockets` —— 所以自托管部署得到的是一等公民集成，而不是借道 Mattermost 的 Slack 兼容层。

一个 **bot access token** 就授权了全部操作，不像 Slack 还要再管一个连接用的 token。Mattermost 原生支持 Markdown，回复不需要任何格式转换；卡片上也没有 **Streaming** 开关 —— 回复以完整消息送达，过程 narration 在 **Send Progress** 开启时单独投递。

![Mattermost 渠道配置](/screenshots/dev/partners-channel-mattermost.png)

Partner 运行时先看卡片实时状态：它应从 **Connecting** 进入 **Connected**；只有失败状态需要更多细节时再查日志。

## 安装依赖

Mattermost channel 随 Partners extra 一起安装；它的传输基于 `httpx` 和 `websockets`，已经包含在内 —— 没有额外的 SDK 要装。

```bash
python scripts/install_extras.py partners
# 或发布包支持 partners extras 时：
pip install "deeptutor[partners]"
```

## 创建 bot 账号

1. 以 Mattermost **System Admin** 身份启用 bot 账号：**System Console -> Integrations -> Bot Accounts -> Enable Bot Account Creation** 设为 **true**。
2. 打开 **Integrations -> Bot Accounts -> Add Bot Account**。填一个用户名（显示名和描述可选），点 **Create**。
3. Mattermost 只会**显示一次** bot 的 **access token** —— 当场复制下来，这就是 **Bot Token**。丢了的话给这个 bot 重新生成 token，不要拿个人 token 凑数。
4. 把 bot 加进它要服务的 team 和 channel：在频道里 `/invite @你的bot`，或从频道成员面板添加。bot 只能收到自己已加入的频道的消息。
5. 收集 **Allow From** 要用的 id：每个发送者的 Mattermost **user id** 可以在 System Console 用户列表里看到（partner 日志在首条消息时也会打印出来）。用户名用于 `@mention` 识别，但 **Allow From** 匹配的是 user id。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Mattermost**。

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会实时投递过程 narration。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Server Url** | 你的 Mattermost 基础 URL，例如 `https://mattermost.example.com`。scheme 可省略（默认 `https`），WebSocket URL 会自动推导出来 —— 不要在后面加 `/api/v4`。 |
| **Bot Token** | **Integrations -> Bot Accounts** 里 bot 账号的 access token。按密钥存储，保存后会打码显示。 |
| **Allow From** | 一行一个值。开放测试 bot 可填 `*`，正式用填 Mattermost user id。空列表拒绝所有人。 |
| **Group Policy** | `mention`（默认）：频道里只有被 @ 时才答。`open`：已加入的频道里每条消息都答。私聊永远会回复。 |
| **Reply In Thread** | 开（默认）：bot 在以触发 post 为根的线程里回复。线程后续消息仍会先经过 **Group Policy**；默认 `mention` 策略下，每条后续消息都要 @ bot。关：回复直接发到频道。 |
| **Verify Ssl** | 开（默认）。仅当自托管服务器用的是自签名证书或内部 CA 签发的证书时才关掉。 |

超过 Mattermost 单条上限（约 16k 字符）的回复会自动拆成多条消息；支持最大 50 MB 的文件附件。

## 保存之后

1. 点 **Save**，再把 **Enabled** 打开。
2. 启动 partner（已经在跑的话重启它，或在 Channels 面板用 reload）。
3. 用允许的账号私聊 bot，或在 bot 已加入的频道里 @ 它。
4. 看 partner 日志：应该能看到 bot 身份解析（`@你的bot`）、WebSocket 连接、入站 post 和回复投递。
5. 在日志里确认 sender id 之后，把 **Allow From** 里的 `*` 换成真实 id。

## 如何确认健康

- 日志显示 `Mattermost bot identity: @你的bot` 和 `Mattermost WebSocket connected`，没有反复重连。
- bot 账号在你的 Mattermost team 里显示为活跃。
- 允许的账号私聊能收到回复，在已加入的频道里 @ 它也能收到（默认 **Group Policy** = `mention`）。

## 常见问题

### WebSocket 连不上，或 token 被拒

channel 在连接前会调用 `/api/v4/users/me` 校验 **Bot Token**，所以坏 token 会很快报错。这里返回 `401` 说明 token 错了或被吊销 —— 去 **Integrations -> Bot Accounts** 重新生成一个。另外确认 **Server Url** 是基础服务器 URL、后面不带 `/api/v4`（这个路径会自动补上）。

### 自托管服务器上的 TLS / 证书错误

自签名或内部 CA 的证书过不了校验。要么把 CA 装到 DeepTutor 主机上，要么把这个 channel 的 **Verify Ssl** 关掉 —— 在受信任的私有网络里可以接受。

### bot 在频道里不回复，私聊正常

查两个地方：

1. **Group Policy** = `mention` 时，消息必须真的 @ 到 bot，而且 bot 必须是该频道成员（`/invite @你的bot`）。
2. **Allow From** —— 空列表拒绝所有人。先用 `*` 测试，再换成真实的 Mattermost user id。

### 回复落到线程里、没 @ 的后续消息被忽略

**Reply In Thread** 只决定 bot 把回答发到哪里，不会绕过 mention filtering。**Group Policy** = `mention` 时，线程里的每条后续消息仍要 @ bot；如果希望已加入频道的所有消息都可触发回复，把策略改成 `open`。只有想走扁平频道回复时，才需要关闭 **Reply In Thread**。

## 相关页面

- [Channel Matrix](/zh-cn/partners/channels/) —— 所有 channel 一览
- [Slack](/zh-cn/partners/slack/) —— Mattermost 原生 API 所替代的团队聊天 channel
- [Discord](/zh-cn/partners/discord/) —— 同样的直连 WebSocket + REST 传输
