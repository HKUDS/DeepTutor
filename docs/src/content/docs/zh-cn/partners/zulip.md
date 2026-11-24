---
title: Zulip
description: 为 Partner 配置 Zulip channel —— event-queue long polling，session 按 stream + topic 划分。
quadrant: how-to
---

<img src="/channel-icons/zulip.svg" alt="" width="40" height="40" />

`zulip` channel 把 Partner 接到 Zulip 的结构化团队聊天里。Zulip 把对话切分成 **stream** 和 **topic**，channel 保留了这套结构：每个 (stream, topic) 组合就是一个独立的 Partner session，每条作业讨论、每个支持 topic 都带着自己的上下文。私聊也支持，按发送者各自隔离。

![Zulip 渠道配置](/screenshots/dev/partners-channel-zulip.png)

Partner 运行时先看卡片实时状态：它应显示 event listener 已连接/运行；只有失败状态需要更多细节时再查日志。

## 安装依赖

Zulip 支持包含在 Partners extra 里 —— `zulip` 客户端包随之安装，别的不用装。

```bash
python scripts/install_extras.py partners
# 或发布包支持 partners extras 时：
pip install "deeptutor[partners]"
```

## 在 Zulip 里创建 bot

1. 在 Zulip 中点右上角齿轮图标 -> **Organization**（或 **Personal**）**settings** -> **Bots**。
2. 点 **Add a new bot**，类型选 **Generic bot**，起个名字。
3. Zulip 会生成一个 bot 邮箱，形如 `my-bot@yourorg.zulipchat.com` —— **Email** 字段填的就是它，不是人的邮箱。
4. 在同一页复制 bot 的 **API key**。
5. Generic bot 默认能收到私聊，但只有订阅了某个 stream 才能看到它。可以在 Zulip 的 bot 设置里订阅，也可以用下面的 **Subscribe Streams** 让 DeepTutor 代劳。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Zulip**。

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会投递过程 narration。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Site** | 你的 Zulip 服务器 URL，比如 `https://yourorg.zulipchat.com`。要带 scheme，realm 子域名要写对。 |
| **Email** | 创建页生成的 bot 邮箱 —— 不是你自己的。 |
| **Api Key** | bot 的 API key。按密钥存储。 |
| **Allow From** | 一行一个 Zulip 用户 id 或邮箱，两种写法都能匹配。开放测试可填 `*`。空列表拒绝所有人。 |
| **Group Policy** | 针对 stream 消息：`mention`（默认）只在 bot 被 @ 时回答，`open` 对已订阅 stream 的每条消息都答。私聊永远会回复。 |
| **Subscribe Streams** | stream 名，一行一个。channel 启动时会替 bot 订阅它们。 |
| **Timeout** | event-queue long-poll 超时秒数。默认 `60` 适用于大多数服务器。 |

## 保存之后

1. 点 **Save**，打开 **Enabled** 后再保存一次。
2. 启动 partner —— 从 UI 操作，或 `deeptutor partner start <partner-id>`。已经在跑就重启。
3. 私聊 bot，或在已订阅的 stream 里 @ 它。
4. 回复正常之后，把 **Allow From** 里的 `*` 换成真实用户 id 或邮箱。

数学公式不会在路上丢掉：channel 会把回复里标准的 `$...$` 和 `$$...$$` 转成 Zulip 原生的 KaTeX 格式。

## 如何确认健康

健康的 Zulip channel 有三个迹象：

- 日志显示 event queue 已注册、配置的 stream 已订阅；
- 私聊 bot 能收到回复；
- 在已订阅的 stream 里 @ 它，能在同一个 topic 里收到回复。

## 常见问题

### bot 看不到 stream 消息

通常是两种原因。bot 没订阅这个 stream —— 去 Zulip 的 bot 设置里加，或用 **Subscribe Streams**。或者 **Group Policy** 是 `mention` 而消息没有 @ 到 bot；@ 一下，或把策略改成 `open`。

### 启动时报鉴权错误

把三件套重新核对一遍：**Site** 必须是带正确 realm 子域名的完整 URL，**Email** 必须是 bot 的生成邮箱，**Api Key** 必须和这个 bot 对得上。在 Zulip 里重新生成 key 会让旧的失效，轮换后记得更新 card。

### 日志里出现 `BAD_EVENT_QUEUE_ID`

服务器重启或长时间空闲后 event queue 会过期。channel 会自动重新注册 —— 不用管。如果反复不停地出现，去检查 Zulip 服务器本身的健康状况。
