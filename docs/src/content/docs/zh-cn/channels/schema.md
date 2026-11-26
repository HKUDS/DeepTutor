---
title: 渠道矩阵
description: 所有内置 Partner channels 的连接模型、关键字段和适用场景。
quadrant: reference
---

Partner channels 是同一个 Partner brain 外面的投递适配器。它不会创建第二套 agent runtime：一条 IM 入站事件会变成作用域内的 chat turn，最终回复再通过 channel 发回去。

大多数配置建议在 Web UI 完成：**Partners -> 你的 partner -> Channels** 会从 `/api/partners/channels/schema` 渲染实时 schema，自动 mask secret 字段，轮询 `/channels/status`，并允许你 reload channels，而不需要手写 YAML。

![伙伴渠道配置](/screenshots/dev/partners-channels.png)

## 内置渠道

| 渠道 | Key | 连接模型 | 适合场景 | 核心字段 |
| --- | --- | --- | --- | --- |
| <img src="/channel-icons/weixin.svg" alt="" width="16" height="16" /> WeChat | `weixin` | HTTP long-poll + 扫码登录 | 个人微信助手 | `allow_from`；可选 `token`、`state_dir`、`route_tag`、`poll_timeout` |
| <img src="/channel-icons/wecom.svg" alt="" width="16" height="16" /> WeCom | `wecom` | 企业微信 AI Bot WebSocket | 企业微信 / WeChat Work | `bot_id`、`secret`、`allow_from` |
| <img src="/channel-icons/qq.svg" alt="" width="16" height="16" /> QQ | `qq` | 腾讯 botpy WebSocket | 官方 QQ Bot 部署 | `app_id`、`secret`、`allow_from`、`msg_format` |
| <img src="/channel-icons/napcat.svg" alt="" width="16" height="16" /> QQ (NapCat) | `napcat` | OneBot v11 WebSocket | 通过 NapCat 接个人 QQ | `ws_url`、可选 `access_token`、`allow_from`、`group_policy` |
| <img src="/channel-icons/telegram.svg" alt="" width="16" height="16" /> Telegram | `telegram` | Bot API polling | 简单个人/群 bot | `token`、`allow_from` |
| <img src="/channel-icons/discord.svg" alt="" width="16" height="16" /> Discord | `discord` | Gateway WebSocket | Discord server 和 DM | `token`、`allow_from`、群策略字段 |
| <img src="/channel-icons/slack.svg" alt="" width="16" height="16" /> Slack | `slack` | Socket Mode | Slack team、DM、threaded channel help | `bot_token`、`app_token`、`allow_from`、`group_policy` |
| <img src="/channel-icons/feishu.svg" alt="" width="16" height="16" /> Feishu / Lark | `feishu` | Lark SDK WebSocket | 飞书 / Lark 企业聊天 | `app_id`、`app_secret`，以及 verification/encryption 字段 |
| <img src="/channel-icons/dingtalk.svg" alt="" width="16" height="16" /> DingTalk | `dingtalk` | Stream Mode | 钉钉企业聊天 | `client_id`、`client_secret`、`allow_from` |
| <img src="/channel-icons/matrix.svg" alt="" width="16" height="16" /> Matrix | `matrix` | Matrix sync loop | 去中心化房间，可选 E2EE | `homeserver`、用户凭证或 `access_token`、`allow_from`、`group_policy` |
| <img src="/channel-icons/zulip.svg" alt="" width="16" height="16" /> Zulip | `zulip` | Event queue | stream + topic 工作流 | `email`、`api_key`、`site`、`allow_from`、`group_policy` |
| <img src="/channel-icons/mattermost.svg" alt="" width="16" height="16" /> Mattermost | `mattermost` | 原生 v4 WebSocket + REST | 自托管开源团队聊天 | `server_url`、`bot_token`、`allow_from`、可选 `group_policy`、`reply_in_thread`、`verify_ssl` |
| <img src="/channel-icons/whatsapp.svg" alt="" width="16" height="16" /> WhatsApp | `whatsapp` | Bridge WebSocket | 通过桥接运行时接 WhatsApp | bridge URL/token、`allow_from` |
| <img src="/channel-icons/email.svg" alt="" width="16" height="16" /> Email | `email` | IMAP poll + SMTP send | 异步邮件答疑 / helpdesk | IMAP host/user/password、SMTP host/user/password、`allow_from` |
| <img src="/channel-icons/mochat.svg" alt="" width="16" height="16" /> Mochat | `mochat` | Socket.IO 或 HTTP polling | 客服式聊天面板 | `base_url` / socket URL、`claw_token`、`allow_from` |
| <img src="/channel-icons/msteams.svg" alt="" width="16" height="16" /> Microsoft Teams | `msteams` | 内置 HTTP webhook listener | Teams DM-first Bot Framework 集成 | `app_id`、`app_password`、`tenant_id`、host/port/path |

## 安装依赖

除 Matrix 外，所有内置 channel 都包含在 Partners extra 里：

```bash
python scripts/install_extras.py partners
# 或发布包支持 extras 时：
pip install "deeptutor[partners]"
```

这一条命令会装齐全部 channel SDK——`python-telegram-bot`、`slack-sdk`、`lark-oapi`、`dingtalk-stream`、`qq-botpy`、`wecom-aibot-sdk`、`python-socketio` 等（完整清单见 `requirements/partners.txt`）。Email 只用 Python 标准库，不需要额外的包。Matrix 单独成 extra，因为加密房间依赖原生 `libolm` 库：源码中普通房间运行 `python scripts/install_extras.py matrix`，加密房间运行 `python scripts/install_extras.py matrix-e2e`。

如果服务器上缺某个 channel 的依赖，Channels 面板会把它置灰并显示 import 错误（如 `No module named 'lark_oapi'`）。已安装卡片会区分 **Connected**、**Connecting**、**Listener running**、**Waiting for scan**、**Configuration required**、**Connection failed** 与 **Not connected**。按提示补依赖或配置，再重启/reload Partner。

修改模块或依赖前先停止 DeepTutor。从源码仓库根目录运行安装助手，用同一个数据目录重启，再检查 `deeptutor module list` 与 Channels 状态。wheel 环境使用对应版本支持的 extras，不要在源码安装上叠加功能 wheel。

## 共享投递开关

大多数 channels 都继承同一组 delivery controls：

| 字段 | 含义 |
| --- | --- |
| `enabled` | Partner 是否启动这个 channel。 |
| `send_progress` | 长 turn 期间是否投递 narration/progress。 |
| `send_tool_hints` | 是否投递一行工具调用提示。调试时有用，生产环境可能太吵。 |
| `streaming` | 仅 Telegram、Discord、Feishu：回复实时流式输出，靠原地编辑消息逐步长出（Feishu 走 CardKit 流式卡片）。需要 `send_progress` 开启。默认关闭。 |
| `allow_from` | 用户/会话 allowlist。`*` 适合测试；部署时更建议明确 id。 |

## 配置流程

1. 先在 Web UI 创建并测试 Partner，不要一开始就开 IM channel。
2. 第一次只启用一个 channel。
3. 调试阶段保持 `send_progress` 和 `send_tool_hints` 开启。
4. `allow_from: ["*"]` 只用于本地/私有测试。
5. 先确认实时卡片进入 connected/listening 状态，再发一条短消息并把 `*` 换成真实 sender ids；只有状态详情不够时才查日志。
6. 第一个 channel 稳定后，再添加其它 channels。

## 怎么选

- 个人微信用 **WeChat**，需要人工扫码和持久化 state。
- 企业/团队部署用 **WeCom**、**Feishu**、**DingTalk**、**Slack** 或 **Teams**。
- 官方 QQ Bot 用 **QQ**；只有在明确操作个人 QQ bridge 时才用 **NapCat**。
- 异步 inbox 工作流用 **Email**。
- 需要 room/topic 结构时，用 **Matrix** 或 **Zulip**。
- 想要自己运维的自托管开源团队聊天，用 **Mattermost**。

## 状态存在哪里

Channel state 存在 Partner 的 `channels/` 目录下，例如：

```text
data/partners/<partner_id>/channels/weixin/account.json
data/partners/<partner_id>/channels/msteams/msteams_conversations.json
```

Docker 或生产部署要持久化整个 `data/partners/`。丢失 channel state 可能导致重新扫码，或重新收集 conversation reference。

## 详细页面

每个内置 channel 都有专属配置页：平台侧申请步骤、对着截图逐字段讲解 channel card、配完后的验证流程和故障排查：

- <img src="/channel-icons/weixin.svg" alt="" width="16" height="16" /> [WeChat](/zh-cn/channels/domestic/weixin/) —— 个人微信扫码登录和 long-poll 配置
- <img src="/channel-icons/wecom.svg" alt="" width="16" height="16" /> [WeCom](/zh-cn/channels/domestic/wecom/) —— 企业微信 AI Bot 配置
- <img src="/channel-icons/qq.svg" alt="" width="16" height="16" /> [QQ / NapCat](/zh-cn/channels/domestic/qq/) —— 官方 QQ bot 和个人 QQ bridge 两条路径
- <img src="/channel-icons/telegram.svg" alt="" width="16" height="16" /> [Telegram](/zh-cn/channels/international/telegram/) —— BotFather 注册、Bot API 轮询、流式回复
- <img src="/channel-icons/discord.svg" alt="" width="16" height="16" /> [Discord](/zh-cn/channels/international/discord/) —— Developer Portal 应用、intents、Gateway WebSocket
- <img src="/channel-icons/slack.svg" alt="" width="16" height="16" /> [Slack](/zh-cn/channels/international/slack/) —— Socket Mode 应用（bot + app 双 token）
- <img src="/channel-icons/feishu.svg" alt="" width="16" height="16" /> [Feishu / Lark](/zh-cn/channels/domestic/feishu/) —— 开放平台应用和 CardKit 流式卡片
- <img src="/channel-icons/dingtalk.svg" alt="" width="16" height="16" /> [DingTalk](/zh-cn/channels/domestic/dingtalk/) —— Stream Mode 企业机器人
- <img src="/channel-icons/matrix.svg" alt="" width="16" height="16" /> [Matrix](/zh-cn/channels/international/matrix/) —— homeserver 凭证和可选 E2EE
- <img src="/channel-icons/zulip.svg" alt="" width="16" height="16" /> [Zulip](/zh-cn/channels/international/zulip/) —— bot 账号和 stream 订阅
- <img src="/channel-icons/mattermost.svg" alt="" width="16" height="16" /> [Mattermost](/zh-cn/channels/international/mattermost/) —— 自托管服务器，bot token 走原生 v4 API
- <img src="/channel-icons/whatsapp.svg" alt="" width="16" height="16" /> [WhatsApp](/zh-cn/channels/international/whatsapp/) —— bridge 运行时配置
- <img src="/channel-icons/email.svg" alt="" width="16" height="16" /> [Email](/zh-cn/channels/international/email/) —— IMAP 收件轮询和 SMTP 回信
- <img src="/channel-icons/mochat.svg" alt="" width="16" height="16" /> [Mochat](/zh-cn/channels/domestic/mochat/) —— Socket.IO 客服面板
- <img src="/channel-icons/msteams.svg" alt="" width="16" height="16" /> [Microsoft Teams](/zh-cn/channels/international/msteams/) —— Bot Framework webhook 监听

## 各渠道字段

下面是每张渠道卡片上的字段。卡片由 `GET /api/partners/channels/schema` 渲染。共用开关仍在上面的矩阵里。

<a id="dingtalk"></a>

### DingTalk（钉钉）

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 实时发过来。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Client Id** | 凭证与基础信息页的 AppKey（一般 `ding...` 开头）。 |
| **Client Secret** | 同页的 AppSecret。按 secret 存储，保存后会打码。 |
| **Allow From** | 一行一个值。测试可填 `*` 表示开放；正式用换成钉钉 staff id（每条入站消息的 sender id 都会打在 partner 日志里）。空列表会拒绝所有人。 |
<a id="feishu"></a>

### Feishu（飞书）

| 字段 | 怎么填 |
| --- | --- |
| **Streaming** | 默认关闭。打开后回复用 CardKit 流式卡片实时打字渲染。依赖 **Send Progress**：过程 narration 也会逐轮流式输出。 |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 实时发过来。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **App Id** | 凭证与基础信息页的 App ID，`cli_...` 开头。 |
| **App Secret** | 同页的 App Secret。按 secret 存储，保存后会打码。 |
| **Domain** | 国内飞书应用用默认的 `feishu`；国际版 Lark tenant 要选 `lark`，这样 SDK 才会使用 `open.larksuite.com`。扫码流程会自动填写。 |
| **Encrypt Key** | 只有在平台开启了事件加密时才需要填，否则留空。 |
| **Verification Token** | 平台的事件 Verification Token，用于事件签名校验。没配置就留空。 |
| **Allow From** | 一行一个值。测试可填 `*` 表示开放；正式用换成 `ou_...` open id（发一条消息后从 partner 日志里抄）。空列表会拒绝所有人。 |
| **React Emoji** | 机器人收到消息后立刻回应的表情，相当于"已读"确认。默认 `THUMBSUP`；常用的还有 `OK`、`EYES`、`DONE`、`OnIt`、`HEART`。 |
| **Group Policy** | `mention`（默认）：群里只有被 @ 才回答。`open`：群里每条消息都回答。私聊永远会回复。 |
| **Reply In Thread** | 默认开启。群回复留在触发消息的话题里。单聊始终是普通回复。 |
| **Thinking Notice** | 默认开启。模型思考时发一条短暂提示，回答开始后删掉。 |
| **Stream Print Frequency Ms** | CardKit 打字机间隔，单位毫秒。默认 `30`。`0` 使用平台默认值。 |
| **Stream Print Step** | 每一步打出的字符数。默认 `6`。`0` 使用平台默认值。 |
| **Stream Print Strategy** | `fast`（默认）或 `delay`。 |
<a id="mochat"></a>

### Mochat

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 发出去。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Base Url** | 你的 Mochat 实例。默认 `https://mochat.io`。 |
| **Socket Url** | 可选的独立 Socket.IO endpoint。留空表示用 **Base Url**。 |
| **Socket Path** | Socket.IO 挂载路径。默认 `/socket.io`。 |
| **Socket Disable Msgpack** | 默认关闭（可用时优先 msgpack）。服务端没有 msgpack parser 时打开，强制走 JSON。 |
| **Socket Reconnect Delay Ms** | 初始重连延迟。默认 `1000`。 |
| **Socket Max Reconnect Delay Ms** | 重连退避上限。默认 `10000`。 |
| **Socket Connect Timeout Ms** | 连接超时。默认 `10000`。 |
| **Refresh Interval Ms** | channel 刷新 session/panel 目录的频率。默认 `30000`。 |
| **Watch Timeout Ms** | HTTP 回退模式下的 long-poll 超时。默认 `25000`。 |
| **Claw Token** | 必填。Mochat 管理后台拿到的 bot token。 |
| **Sessions** | 要监听的 session id，一行一个。`*` 表示自动发现并订阅新 session。 |
| **Panels** | 要监听的 panel id，一行一个。`*` 表示自动发现 panel。两个列表都留空时 channel 什么都不监听。 |
| **Allow From** | 一行一个值。测试可填 `*` 表示开放，或填具体的 Mochat user id。空列表拒绝访问。 |

| 字段 | 怎么填 |
| --- | --- |
| **Watch Limit** | 单次 poll 最多拉取的事件数。默认 `100`。 |
| **Retry Delay Ms** | HTTP 重试失败之间的延迟。默认 `500`。 |
| **Max Retry Attempts** | Socket.IO 重连次数上限。`0` 表示一直重连；这个字段不会限制 HTTP fallback loop。 |
| **Agent User Id** | bot 自己的 Mochat user id。用于忽略 bot 自己的消息和识别 @ 提及。 |
| **Mention** | `require_in_groups` —— 群 session 里必须被 @ 才回复。 |
| **Groups** | 按 group id 的逐群覆盖：`{"<group-id>": {"require_mention": true}}`。 |
| **Reply Delay Mode** | `non-mention`（默认）会缓冲没有提及 bot 的 panel 消息；填其他值则关闭缓冲。 |
| **Reply Delay Ms** | 缓冲窗口。默认 `120000`（2 分钟）。 |
<a id="qq"></a>

### QQ / NapCat

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否随 partner 启动该渠道。 |
| `app_id` | 腾讯 bot 平台里的 App ID。 |
| `secret` | Bot secret。 |
| `allow_from` | 允许访问的 QQ user ids / openids。空列表拒绝访问；生产环境建议明确 id。 |
| `msg_format` | `plain` 或 `markdown`。不同 QQ 客户端 Markdown 表现不一，不确定时先用 `plain`。 |

<a id="napcat"></a>

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
<a id="wecom"></a>

### WeCom（企业微信）

| 字段 | 说明 |
| --- | --- |
| `enabled` | partner 启动时是否启动该渠道。 |
| `bot_id` | 企业微信 AI Bot 平台里的 Bot ID。 |
| `secret` | 企业微信 Secret，按凭证处理。 |
| `allow_from` | 允许访问的用户 id。空列表拒绝访问；基础 channel policy 支持时，`*` 表示开放。 |
| `welcome_message` | 用户打开会话时发送的可选欢迎语。 |
| `send_progress` / `send_tool_hints` | 是否投递过程 narration 和一行工具调用提示。 |
<a id="weixin"></a>

### WeChat（个人微信）

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 发到微信。 |
| **Send Tool Hints** | 调试时建议开启；如果不想让用户看到一行工具调用，生产环境可关闭。 |
| **Enabled** | 准备登录/启动时再打开。 |
| **Allow From** | 一行一个值。测试可填 `*` 表示开放；上线后换成具体微信用户 id。空列表通常表示拒绝所有人。 |
| **Base Url** | 默认 `https://ilinkai.weixin.qq.com`，一般不用改。 |
| **Cdn Base Url** | 默认 `https://novac2c.cdn.weixin.qq.com/c2c`，用于媒体上传/下载。 |
| **Route Tag** | 可选腾讯路由标签。没有特殊部署要求就留空。 |
| **Token** | 可选 bot token。扫码登录时留空；扫码成功后 channel 会保存 token。 |
| **State Dir** | 可选状态目录。留空时使用 `data/partners/<id>/channels/weixin/` 存 `account.json`。 |
| **Poll Timeout** | long-poll 超时时间，单位秒。默认 `35`，多数网络可用。 |
<a id="discord"></a>

### Discord

| 字段 | 怎么填 |
| --- | --- |
| **Streaming** | 默认关闭。打开后回复实时流式输出：文本一边生成，一边原地编辑消息。依赖 **Send Progress**：narration 轮次也会随生成实时流出。 |
| **Send Progress** | 测试时建议开启。长任务会实时投递过程 narration。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Token** | Developer Portal 里的 bot token（**Bot** -> **Reset Token**）。按密钥存储，保存后会打码显示。 |
| **Allow From** | 一行一个值。开放测试 bot 可填 `*`，正式用填 Discord 用户 id（开 Developer Mode 后右键 -> Copy User ID）。空列表拒绝所有人。 |
| **Gateway Url** | 默认 `wss://gateway.discord.gg/?v=10&encoding=json`。除非你要代理 gateway，否则别改。 |
| **Intents** | Gateway intent 位字段。默认 `37377` 覆盖 Guilds、Guild Messages、Direct Messages 和 Message Content。这个数字里包含的特权 intent，必须同时在 Developer Portal 里启用。 |
| **Group Policy** | `mention`（默认）：服务器频道里只有被 @ 时才答。`open`：能读到的频道里每条消息都答。私聊永远会回复。 |
<a id="email"></a>

### Email

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 每条过程更新都是一封单独的邮件。第一次测试可以开；多数部署会关掉，免得邮箱被刷屏。 |
| **Send Tool Hints** | 同样的问题——一条 hint 一封邮件。调试之外建议关闭。 |
| **Enabled** | 准备开始轮询时再打开。 |
| **Consent Granted** | 硬性隐私闸门。没打开之前 channel 拒绝读写任何邮件。务必在邮箱所有者明确同意让 DeepTutor 处理收件箱之后再开。 |
| **Imap Host** | 如 `imap.gmail.com`。 |
| **Imap Port** | 默认 `993`（IMAP over SSL）。 |
| **Imap Username** | 通常是完整邮箱地址，如 `tutor@example.com`。 |
| **Imap Password** | App Password（Gmail/Outlook 开 2FA 时）或账号密码（自建服务）。以 secret 方式存储。 |
| **Imap Mailbox** | 默认 `INBOX`。有些服务商的文件夹名拼法不一样——轮询收不到邮件时去 webmail 里确认一下。 |
| **Imap Use Ssl** | 端口 993 时保持开启。 |
| **Smtp Host** | 如 `smtp.gmail.com`。 |
| **Smtp Port** | 默认 `587`（STARTTLS）。配合 **Smtp Use Ssl** 时用 `465`。 |
| **Smtp Username** | 通常和 Imap Username 一样。 |
| **Smtp Password** | 通常是同一个 App Password。以 secret 方式存储。 |
| **Smtp Use Tls** | 端口 587 上的 STARTTLS。除非换用下面的隐式 SSL，否则保持开启。 |
| **Smtp Use Ssl** | 隐式 SSL，一般配端口 465。两个 TLS 选项二选一，不要同时开。 |
| **From Address** | 可选。留空时回退到 Smtp Username，再回退到 Imap Username。 |
| **Auto Reply Enabled** | 关闭后 Partner 不再自动回复入站邮件（主动发送不受影响）。测试时可以当刹车用。 |
| **Poll Interval Seconds** | 默认 `30`。检查收件箱的频率；小于 5 的值会被钳到 5。 |
| **Mark Seen** | 把处理过的邮件标为已读——这是最主要的去重保护。保持开启。 |
| **Max Body Chars** | 默认 `12000`。超长正文会在进入 Partner 之前被截断。 |
| **Subject Prefix** | 默认 `Re: `。回信主题会加上这个前缀，除非原主题已经以 `Re:` 开头。 |
| **Allow From** | 一行一个邮箱地址，全小写。测试可填 `*` 表示开放。空列表拒绝所有人。 |
<a id="matrix"></a>

### Matrix

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
<a id="mattermost"></a>

### Mattermost

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
<a id="msteams"></a>

### Microsoft Teams

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 实时发过来。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **App Id** | App registration 的 Application (client) ID。同时也是校验入站 JWT 时要求的 audience。 |
| **App Password** | client secret 的 Value。按 secret 存储，保存后会打码。 |
| **Tenant Id** | Directory (tenant) ID。单租户注册必填；只有多租户 bot 才能留空。 |
| **Host** | 内置 HTTP 服务器的监听地址。默认 `0.0.0.0` 监听所有网卡；如果只有本机的反向代理来访问，可以收紧到 `127.0.0.1`。 |
| **Port** | 监听端口。默认 `3978`，Bot Framework 的惯例端口。同一主机上所有已启用的 Teams Partners 必须各用一个不同端口。 |
| **Path** | 接收消息的 URL 路径。默认 `/api/messages`，必须和 messaging endpoint 的结尾一致。 |
| **Allow From** | 一行一个值。测试可填 `*`；正式用换成 Microsoft Entra object id——被拒的 sender id 会打在 partner 日志里。空列表会拒绝所有人。 |
| **Reply In Thread** | 开启（默认）时，回复会挂在触发它的那条消息下面，而不是另起一条。 |
| **Mention Only Response** | 消息里除了 @ 机器人什么都没有时，机器人回的那句话。 |
| **Validate Inbound Auth** | 保持开启。每个入站请求都校验 Bot Framework JWT（用微软公开的密钥做 RS256 验签，audience 必须等于 App Id）。关掉它意味着任何拿到 URL 的人都能冒充任意用户跟 partner 说话——只限本地测试。 |
| **Ref Ttl Days** | 闲置的 conversation reference 保留多少天后清理。默认 `30`。 |
| **Prune Web Chat Refs** | 把 Bot Framework Web Chat 的会话从存储里剔除（Web Chat 不支持）。 |
| **Prune Non Personal Refs** | 把群聊/频道的会话 reference 剔除；channel 目前只做私聊。 |
| **Ref Touch Interval S** | 活跃会话 reference 的时间戳刷新最小间隔（秒）。默认 `300`。 |
| **Trusted Service Url Hosts** | 接受并回复的 Bot Framework 服务域名白名单。默认覆盖公有云和 GCC/DoD 政务云——除非微软把你路由去了别处，否则不用动。 |
<a id="slack"></a>

### Slack

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会实时投递过程 narration。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | 准备启动 channel 时再打开。 |
| **Mode** | 目前只支持 `socket`，保持不动。 |
| **Webhook Path** | 为将来的 webhook 模式预留；**Mode** 是 `socket` 时用不上。留默认 `/slack/events` 即可。 |
| **Bot Token** | **OAuth & Permissions** 里的 `xoxb-…` token。按密钥存储，保存后会打码显示。 |
| **App Token** | **Socket Mode** 里的 `xapp-…` App-Level Token（需要 `connections:write`）。同样是密钥。别和 Bot Token 填反了。 |
| **User Token Read Only** | 保持默认（开）。 |
| **Reply In Thread** | 开（默认）：bot 在触发消息下面的线程里回答。线程内的后续消息仍会先经过 **Group Policy**；默认 `mention` 策略下，每条后续消息都要 @ bot。关：回复直接发进频道。 |
| **React Emoji** | bot 加在你消息上、表示"收到"的 emoji 名（不带冒号）。默认 `eyes`。 |
| **Allow From** | 一行一个值。开放测试 bot 可填 `*`，正式用填 Slack 用户 id（`U…`）。空列表拒绝所有人。 |
| **Group Policy** | `mention`（默认）：频道里只回答 @ 提及。`open`：所在频道每条消息都答。`allowlist`：只响应 **Group Allow From** 里列出的频道。 |
| **Group Allow From** | 频道 id（`C…`），一行一个。**Group Policy** 是 `allowlist` 时生效。 |
| **Dm** | DM 子策略：**Enabled** 整体开关 DM；**Policy** 取 `open` 时任何 DM 都答，取 `allowlist` 时只放行它自己那份 **Allow From** 列表里的 id。 |
<a id="telegram"></a>

### Telegram

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
<a id="whatsapp"></a>

### WhatsApp

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 发到 WhatsApp。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | bridge 跑起来、准备启动 channel 时再打开。 |
| **Bridge Url** | bridge 的 WebSocket 地址，默认 `ws://localhost:3001`。 |
| **Bridge Token** | 可选共享密钥。只有你的 bridge 校验 `auth` 消息时才需要填。 |
| **Allow From** | 一行一个值。测试可填 `*` 表示开放；上线后换成具体 sender id（WhatsApp id 里 `@` 前面那段，通常是手机号）。空列表拒绝所有人。 |
<a id="zulip"></a>

### Zulip

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
