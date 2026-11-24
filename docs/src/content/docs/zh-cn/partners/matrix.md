---
title: Matrix
description: 为 Partner 配置 Matrix channel——任意 homeserver、long-poll sync、可选端到端加密。
quadrant: how-to
---

<img src="/channel-icons/matrix.svg" alt="" width="40" height="40" />

`matrix` channel 通过标准 client-server API 把 Partner 接入去中心化的 Matrix 房间。任何 homeserver 都行——matrix.org，或自建的 Synapse / Conduit / Dendrite——端到端加密是可选项，多数安装不必为 libolm 依赖买单。

![Matrix 渠道配置](/screenshots/dev/partners-channel-matrix.png)

Partner 运行时先看卡片实时状态：它会在查日志前区分 sync loop 已连接、缺少 Matrix 依赖或配置不完整。

## 安装依赖

Matrix **不在** Partners extra 里——它自带两个独立的 extras：

```bash
# plain Matrix (unencrypted rooms)
python scripts/install_extras.py matrix

# Matrix including end-to-end encrypted rooms
python scripts/install_extras.py matrix-e2e
```

- `[matrix]` 安装 `matrix-nio`、`mistune` 和 `nh3`。直聊和未加密房间用这个就够了。
- `[matrix-e2e]` 额外加上 `matrix-nio[e2e]`，它会拉取 `python-olm`——而后者需要先装好原生的 **libolm** 库：

```bash
# macOS
brew install libolm

# Debian / Ubuntu
sudo apt-get install libolm-dev
```

Docker/CI 等没有源码 checkout 的场景，同样的依赖集合镜像在 `requirements/matrix.txt` 和 `requirements/matrix-e2e.txt`。

完全不装 extras 的话，channel 会在 import 时直接报 `Matrix dependencies not installed`。

## 创建 bot 账号并获取 access token

Partner 需要一个自己的 Matrix 账号，任何 homeserver 都行——测试用 matrix.org 就可以。

1. 创建账号：Element web app -> 你的 homeserver -> Create Account（自建 Synapse 也可以用 `register_new_matrix_user`）。
2. 获取 access token，两种方式任选：
   - **Element**：用 bot 账号登录，**Settings -> Help & About -> Advanced -> Access Token**，展开并复制。
   - **REST API**：

```bash
curl -X POST https://matrix.org/_matrix/client/r0/login \
  -H "Content-Type: application/json" \
  -d '{"type": "m.login.password", "user": "my-bot", "password": "your-password"}'
# the response contains "access_token": "syt_..."
```

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Matrix**。

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 发到房间里。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Homeserver** | 默认 `https://matrix.org`。自建就填自己服务器的 URL。 |
| **Access Token** | 从 Element 或 login API 拿到的 token。以 secret 方式存储。 |
| **User Id** | bot 的完整 Matrix id，如 `@my-bot:matrix.org`。也用于识别 @ 提及。 |
| **Device Id** | 可选但建议填：随便选一个稳定的字符串并保持不变。留空的话，重启可能会重放最近的消息。 |
| **E2Ee Enabled** | 装好 `[matrix-e2e]` extra 和 libolm 之后再打开。没装的话 bot 解不开加密房间。 |
| **Sync Stop Grace Seconds** | 默认 `2`。关停时给进行中的 sync 多少秒收尾。基本不用改。 |
| **Max Media Bytes** | 默认 `20971520`（20 MB）。附件上传/下载的大小上限。 |
| **Allow From** | 一行一个 Matrix user id，如 `@frank:matrix.org`。测试可填 `*` 表示开放。空列表拒绝所有人——包括房间邀请。 |
| **Group Policy** | 多人房间的策略：`open`（默认）回复所有消息，`mention` 只在 bot 被 @ 时回复，`allowlist` 只回复下面列出的房间。1:1 直聊总是会回复。 |
| **Group Allow From** | 房间 id（`!abc123:matrix.org`），一行一个。只在 `allowlist` 策略下生效。 |
| **Allow Room Mentions** | 在 `mention` 策略下，`@room` 群发提醒算不算提及 bot。默认关闭。 |

## 保存之后

1. 点 **Save**，打开 **Enabled**，再保存一次。
2. 启动 partner——从 UI，或 `deeptutor partner start <partner-id>`。已在运行就重启。
3. 在任意 Matrix 客户端邀请 bot：`/invite @my-bot:matrix.org`。bot 只接受能通过 **Allow From** 的人发出的邀请——列表为空时它永远不会进房。
4. 在房间里发一条短消息，看回复。
5. 跑通之后，把 **Allow From** 里的 `*` 换成真实 user id。

回复里的 Markdown 会渲染成 Matrix HTML，所以表格和代码块在 Element 等客户端里都能正常显示。

## 如何确认健康

健康的 Matrix channel 通常有三个迹象：

- 日志显示 sync loop 在跑，没有反复出现的 sync 错误；
- 允许的发送者发出邀请后，bot 几秒内就进房；
- 在房间里发一条短消息，Partner 能正常回复。

注意隐私边界：E2EE 保护的是 Matrix 客户端到 bot 之间的传输，消息正文仍然会以明文到达你配置的 LLM provider。在意这一点的话，给这个 channel 配本地模型。

## 常见问题

### bot 进了加密房间但从不回复

**E2Ee Enabled** 开了但没装 `[matrix-e2e]` extra（或 libolm），或者房间加密了它却是关的。先装 libolm，再 `python scripts/install_extras.py matrix-e2e`，打开开关，重启 partner。

### `M_UNKNOWN_TOKEN`

access token 失效了——通常是 bot 在别的客户端被登出，或服务端重置。通过 Element 或 login API 重新拿一个 token，更新到 card 上。

### 第一次 sync 特别慢

历史很长的账号初次 sync 批量很大；这是正常的，每个 device 只会发生一次。设置一个稳定的 **Device Id**，之后重启就能增量续传，不用从头来过。

### bot 不理我的邀请

邀请人必须能通过 **Allow From**。把你自己的 Matrix user id 加进去（测试期间也可以用 `*`），保存后重新邀请。
