---
title: WeChat（个人微信）
description: 使用扫码登录和 HTTP long-poll 为 Partner 配置个人微信渠道。
quadrant: how-to
---

<img src="/channel-icons/weixin.svg" alt="" width="40" height="40" />

`weixin` channel 用 iLink long-poll API 把 Partner 接到个人微信账号。它和 **WeCom 企业微信** 不一样：普通个人微信看本页，企业微信 / WeChat Work 看 [WeCom](/zh-cn/partners/wecom/)。

![WeChat 渠道配置](/screenshots/dev/partners-channel-weixin.png)

卡片同时负责 setup 与运行反馈：在其中生成并扫描二维码，观察 **Waiting for scan** 变成 **Connected**，无需依赖终端二维码。

## 安装依赖

个人微信支持在 Partners extra 里；浏览器二维码渲染还会用到 `qrcode`。

```bash
python scripts/install_extras.py partners
# 或发布包支持 extras 时：
pip install "deeptutor[partners]"
```

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> WeChat**。

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

## 登录流程

1. 先不要启动 Partner，打开它的 WeChat channel card，并把 **Token** 留空。
2. 点 **Scan to connect**，二维码会直接显示在浏览器里。
3. 用微信扫码并在手机上确认。这一步只把 bot token（以及服务端返回的 base URL）写进 channel 配置，不会启动 Partner，也不会开始 long polling。
4. 确认 **Enabled** 已打开，再从 UI 或 CLI 启动 Partner。channel 会载入刚保存的 token，然后开始 long polling。
5. 用允许的账号发一条短消息测试。无 token 时直接启动 channel 仍会在终端打印二维码作为兜底，但推荐先在浏览器完成扫码，再启动 Partner。

```bash
deeptutor partner start <partner-id>
```

如果二维码过期，点 **New code**（或重启 partner）后扫新的那张。实现会自动刷新几次二维码，但登录必须人工扫码完成。

## 如何确认健康

健康的 WeChat channel 通常有三个迹象：

- 扫码结果提示 bot token 已保存，并且账号状态已经写入；
- 挂载的 `data/` 目录里存在 `data/partners/<partner-id>/channels/weixin/account.json`；
- 允许的发送者发一条短消息后，Partner 能正常回复。

Docker 部署必须持久化 `data/partners/`，否则每次容器重启都可能需要重新扫码。

## 访问控制

消息进入 partner brain 之前会先检查 `Allow From`。第一次测试填 `*` 可以；生产环境建议从日志里确认 sender id 后换成明确 allowlist。

## 常见问题

### 每次启动都要求重新扫码

检查 `State Dir` 是否可写、是否持久化。留空时 DeepTutor 写到 Partner 的 `channels/weixin/` 目录；如果 Docker 没挂载该目录，重启后 token 会丢失。

### 收得到消息但回不了

微信回复依赖最近入站消息带来的 `context_token`。如果账号空闲太久，先从微信发一条新消息，让 DeepTutor 刷新 context 后再回复。

### 过程消息太多

在 channel card 里关闭 **Send Progress** 或 **Send Tool Hints**。这不会改变 partner 推理，只改变微信里看到的投递内容。
