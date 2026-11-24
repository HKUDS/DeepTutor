---
title: Telegram
description: 为 Partner 配置 Telegram channel —— BotFather 注册、Bot API long polling、原地编辑的流式回复。
quadrant: how-to
---

<img src="/channel-icons/telegram.svg" alt="" width="40" height="40" />

`telegram` channel 通过 Bot API **long polling** 把 Partner 接到一个 Telegram bot 上：DeepTutor 用一个长连接循环主动从 Telegram 服务器拉取更新，所以不需要公网 IP、不需要 webhook、也不需要反向代理。在 BotFather 注册大约一分钟就能搞定 —— 想做个人助理或小群 bot，Telegram 是接入最快的 channel。

这个 channel 还支持 **live streaming**：开关打开后，bot 只发一条消息，随着回复生成不断原地编辑这条消息。

![Telegram 渠道配置](/screenshots/dev/partners-channel-telegram.png)

Partner 运行时先看卡片实时状态：它应显示 polling listener 已连接/运行；只有失败状态需要更多细节时再查日志。

## 安装依赖

Telegram 支持随 Partners extra 一起安装。底层客户端是 `python-telegram-bot[socks]`，SOCKS 代理支持已经内置 —— 不需要额外装任何东西。

```bash
python scripts/install_extras.py partners
# 或发布包支持 partners extras 时：
pip install "deeptutor[partners]"
```

## 在 BotFather 注册 bot

1. 打开 Telegram，搜索 `@BotFather`，开始对话。
2. 发送 `/newbot`。BotFather 会先问显示名称（比如 `Math Mentor`），再问 username，必须以 `bot` 结尾（比如 `hku_math_mentor_bot`）。
3. BotFather 回复一个 HTTP API token，形如 `123456789:ABC-DEF1234ghIkl-...`。**复制好** —— 这就是要填进 **Token** 字段的值。
4. 查自己的用户 id：和 `@userinfobot` 对话，它会回复你的数字 id。填 **Allow From** 时会用到。
5. 要在群里用，需要关闭 Group Privacy，bot 才能读到群消息：`/mybots` -> 选你的 bot -> **Bot Settings** -> **Group Privacy** -> **Turn off**。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Telegram**。

| 字段 | 怎么填 |
| --- | --- |
| **Streaming** | 默认关闭。打开后回复实时流式输出：文本一边生成，一边原地编辑那条 Telegram 消息。依赖 **Send Progress**：narration 轮次也会随生成实时流出。 |
| **Send Progress** | 测试时建议开启。长任务会实时投递过程 narration。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Token** | BotFather 给的 HTTP API token。按密钥存储，保存后会打码显示。 |
| **Allow From** | 一行一个值。开放测试 bot 可填 `*`，正式用填 `@userinfobot` 查到的数字用户 id（username 也能匹配）。空列表拒绝所有人。 |
| **Proxy** | 可选代理 URL，Telegram 不可达的网络环境用，比如 `socks5://127.0.0.1:1080` 或 `http://proxy:8080`。直连就留空。 |
| **Reply To Message** | 打开后，bot 的回答会引用触发它的那条消息。热闹的群里很有用，私聊里就显得多余。 |
| **Group Policy** | 群组的回退策略：`mention`（默认）需 @ 或回复 bot；`open` 每条都答。私聊跳过群策略，但仍受 **Allow From** 限制。 |
| **Chat Policies** | 按 `chat_id` 覆盖：`open`、`mention` 或 `topics_only`。后者在 `allowed_topics` 中自动答，其他话题需 @ 或回复 bot；首个匹配规则生效。 |
| **Connection Pool Size** | Bot API 客户端的 HTTP 连接池大小。单个 bot 用默认 `16` 就够。 |
| **Pool Timeout** | 等待空闲连接的秒数。默认 `15`。 |
| **Stream Edit Interval** | 流式输出时两次原地编辑之间的最小间隔秒数。默认 `0.6`；如果 Telegram 报 flood-control 错误就调大。 |

超过 Telegram 4096 字符上限的回复会自动拆成多条消息（DeepTutor 在 4000 处拆分，留出安全余量）。

## 保存之后

1. 点 **Save**，再把 **Enabled** 打开。
2. 启动 partner（已经在跑的话重启它，或在 Channels 面板用 reload）。
3. 用允许的账号打开 `t.me/<your_bot_username>`，发一条短消息。
4. 看 partner 日志：应该能看到入站消息和回复投递。
5. 在日志里确认 sender id 之后，把 **Allow From** 里的 `*` 换成真实 id。

## 如何确认健康

- 日志显示 Telegram channel 在正常 polling，没有报错（尤其没有 `Conflict` 行）。
- 允许的账号发一条短私聊能收到回复；开了 **Send Progress** 的话，长任务期间还能看到 narration 消息。
- 默认 `mention` 策略下，在群里 @ 一下 bot 能得到回答。

## 常见问题

### bot 从来不回复

几乎都是 **Allow From** 的问题。空列表拒绝所有人 —— 包括你自己。先填 `*` 测一下，再换成 `@userinfobot` 查到的数字 id。

### bot 不理群消息

两道门都得打开：

1. BotFather 那边：`/mybots` -> 你的 bot -> **Bot Settings** -> **Group Privacy** -> **Turn off** —— 不关的话 Telegram 根本不会把普通群消息投给 bot。
2. 先查 **Chat Policies**，再查 **Group Policy**：`mention` 需 @ 或回复 bot；`topics_only` 仅在允许的话题中自动答。

### `Conflict: terminated by other getUpdates request`

同一个 token 被两个地方同时 polling —— 要么两个 partner 配了同一个 token，要么还有别的进程没停。Telegram 每个 token 只允许一个 polling 客户端；把重复的那个停掉。

### 当前网络连不上 Telegram

在 **Proxy** 里填一个 SOCKS 或 HTTP 代理 URL（比如 `socks5://127.0.0.1:1080`）。SOCKS 支持已经随 partners extra 装好，不需要额外装包。

## 相关页面

- [Channel Matrix](/zh-cn/partners/channels/) —— 所有 channel 一览
- [Discord](/zh-cn/partners/discord/) —— Gateway WebSocket 模型，同样支持流式输出
