---
title: Feishu（飞书）
description: 为 Partner 配置飞书 / Lark 渠道——开放平台建应用、WebSocket 长连接、CardKit 流式卡片。
quadrant: how-to
---

<img src="/channel-icons/feishu.svg" alt="" width="40" height="40" />

`feishu` channel 通过官方 `lark-oapi` SDK 的 **WebSocket 长连接** 把 Partner 接到飞书（或国际版 Lark）自建应用上：连接由 DeepTutor 主动发起，不需要公网 IP、不需要 webhook 回调、不需要反向代理。国内飞书（`open.feishu.cn`）和国际版 Lark（`open.larksuite.com`）用的是同一个 channel，是在国内组织里跑工作助手的首选。

这个 channel 还支持 **Streaming**：开关打开后，回复会以 CardKit 流式卡片的形式实时打字渲染，边生成边显示。

![飞书渠道配置](/screenshots/dev/partners-channel-feishu.png)

Partner 运行时先看卡片实时状态：它应从 **Connecting** 进入 **Connected**；只有失败状态需要更多细节时再查日志。

## 安装依赖

飞书支持已包含在 Partners extra 里，底层是官方 `lark-oapi` SDK，不需要额外安装任何东西。

```bash
python scripts/install_extras.py partners
# 或发布包支持 extras 时：
pip install "deeptutor[partners]"
```

## 快速配置：扫码创建

channel card 内置了凭据 onboarding，不需要手工复制凭据也能创建并绑定应用：

1. 打开 **Partners -> 你的 partner -> Channels -> Feishu**，点击 **Scan to connect**。
2. 用负责管理该应用的飞书/Lark 账号扫码，也可以打开页面给出的授权链接。
3. 状态变成 **Scan completed** 后，点击 **Apply**。
4. DeepTutor 会保存新应用的 App ID 与 App Secret，自动识别 `feishu` 或 `lark`，启用 channel，并把扫码用户的 open id 加进 **Allow From**。重新扫码并 Apply 会替换当前应用绑定，其余 channel 设置会保留。
5. 启动 Partner；如果已经在运行，就 reload channels。

如果组织策略要求自行创建和审批应用，请使用下面的手动流程。

## 手动配置：在开放平台创建应用

1. 打开[飞书开放平台](https://open.feishu.cn/)（国际版用 [Lark 开放平台](https://open.larksuite.com/)），进入开发者后台，创建一个**自建应用**，填好名称、描述、图标。
2. 在**凭证与基础信息**页复制 **App ID**（`cli_...`）和 **App Secret**，待会儿填进 channel card。
3. **应用能力 -> 机器人**：开通机器人能力，设置机器人的名称和头像。
4. **事件与回调**：把订阅方式切换为**长连接**（事件走 WebSocket 而不是 webhook），然后订阅 `im.message.receive_v1` 事件。
5. **权限管理**：开通消息相关权限——至少 `im:message`（以机器人身份收发消息）；想让图片、文件、语音也能进来，再加 `im:resource`。默认的确认表情会调用创建消息 reaction 的 API，因此还要授予添加消息 reaction 的权限。启用 **Streaming** 时，还要授予 CardKit 创建卡片及更新卡片内容/设置的权限。
6. **创建版本并发布。** 自建应用走企业内发布加管理员审批。版本不发布，机器人什么都收不到——这是最常见的配置失误。

如果你在平台上开启了事件加密（事件与回调里的加密设置），记下 **Encrypt Key** 和 **Verification Token**，它们需要同步填进 channel card。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Feishu**。

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

出站消息格式由 DeepTutor 自动挑选：短的纯文本直接发文本消息，只带链接的发富文本 post，含标题、代码块、列表、表格的发交互卡片。飞书每张卡片只允许一个表格，多表格回复会自动拆成几张卡片。

## 保存之后

1. 点 **Save**，把 **Enabled** 打开。
2. 启动 partner（已在运行的话重启，或在 Channels 面板上用 reload）。
3. 用允许的账号在飞书里私聊机器人，发一条短消息。
4. 看 partner 日志：能看到入站事件，并且你发的消息几乎立刻被加上 React Emoji 表情回应。
5. 在日志里确认 `ou_...` sender id 之后，把 **Allow From** 里的 `*` 换成真实 id。

## 如何确认健康

- 日志出现 `Feishu bot started with WebSocket long connection`，且没有反复刷 `Feishu WebSocket error`（掉线后 channel 每 5 秒自动重连）。
- 测试消息立刻收到 React Emoji 回应——说明入站事件和出站 API 凭证都通了。
- 回复正常送达；开了 **Streaming** 的话，能看到卡片实时打字，而不是最后一次性出一条。

## 常见问题

### 机器人什么都收不到

三道门必须全开：应用版本**已发布**（不是草稿）、订阅了 `im.message.receive_v1` 事件、订阅方式是**长连接**。版本没发布是最常见的原因，先查它。

### 收得到消息但回复失败

多半是权限没开。确认 `im:message` 已开通，收发媒体还要 `im:resource`，默认确认表情还需要添加消息 reaction 的权限；启用 **Streaming** 时也要检查 CardKit 创建/更新权限。然后**重新发布一个版本**——权限变更只在发布后生效。具体 API 错误码会打在 partner 日志里。

### 开启加密后事件全部失败

平台上配了 Encrypt Key，channel card 里就必须填同一个值（连同 Verification Token），反过来也一样。在平台上轮换过任何一个值，都要更新 card 并重启 partner。

### Streaming 卡片不打字

**Streaming** 依赖 **Send Progress**，必须一起开。如果 CardKit 卡片创建失败（日志里搜 `Failed to create Feishu streaming card`），channel 会退回到回合结束后发一张普通卡片——回复还在，只是没有打字效果。

## 相关页面

- [Channel Matrix](/zh-cn/partners/channels/) — 所有 channel 一览
- [DingTalk](/zh-cn/partners/dingtalk/) — 另一大国内办公 IM，同样免 webhook
