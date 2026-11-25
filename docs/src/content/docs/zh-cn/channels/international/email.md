---
title: Email
description: 使用 IMAP 轮询收信、SMTP 回信，为 Partner 配置 email channel。
quadrant: how-to
---

<img src="/channel-icons/email.svg" alt="" width="40" height="40" />

`email` channel 把 Partner 变成一个异步的邮件通信者：轮询 IMAP 收件箱里的未读邮件，通过 SMTP 回信。没有实时连接——一来一回就是一个轮询周期——所以很适合 help-desk 式的支持场景，以及那些就是更喜欢邮件、不爱用聊天软件的用户。

![Email 渠道配置](/screenshots/dev/partners-channel-email.png)

Partner 运行时先看卡片实时状态：**Listener running** 表示轮询循环已启动，**Configuration required** 会在查日志前指出缺失项。

## 安装依赖

什么都不用装。email channel 完全基于 Python 标准库（`imaplib` + `smtplib`），任何 DeepTutor 安装都能直接跑——不需要额外的 pip 包，也不需要 extras。

## 准备邮箱账号

Partner 需要一个自己的邮箱，开通 IMAP 和 SMTP。不要复用个人邮箱：channel 会读取并回复所有未读邮件。

**Gmail**

1. 给账号开启两步验证（2-Step Verification）。
2. 创建一个 [App Password](https://myaccount.google.com/apppasswords)——16 位密码，代替账号密码使用。开了 2FA 之后，普通密码在 IMAP/SMTP 上会被拒绝。
3. 确认 IMAP 已开启：Gmail 设置 -> **Forwarding and POP/IMAP** -> Enable IMAP。
4. 服务器地址：`imap.gmail.com:993`（SSL）和 `smtp.gmail.com:587`（STARTTLS）。

**Outlook / Office 365** —— 开了 2FA 的情况下，App Password 用法相同（前提是租户允许）；不行就找管理员。

**自建邮件服务**（Postfix、Maddy 等）—— 直接用账号密码，host 和端口填自己的。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Email**。

这张卡片的字段见[渠道 schema](/zh-cn/channels/schema/#email)。


每个不同的发件人地址是一个独立 session；回信带 `In-Reply-To` header，在对方的邮件客户端里能正确归到同一个会话线程。

## 保存之后

1. 点 **Save**，然后把 **Enabled** 和 **Consent Granted** 都打开，再保存一次。
2. 启动 partner——从 UI，或 `deeptutor partner start <partner-id>`。如果已经在运行，重启一下让 channel 读到新配置。
3. 用 **Allow From** 里列出的地址发一封测试邮件，最多等一个轮询周期收回复。
4. 回复正常后，把 **Allow From** 里的 `*` 换成真正要服务的地址。

## 如何确认健康

健康的 email channel 通常有三个迹象：

- 日志显示 `Starting Email channel (IMAP polling mode)...`，没有 `missing:` 或 consent 警告；
- 允许的发件人发一封测试邮件，大约一个轮询周期内能收到回复；
- 处理过的邮件在邮箱里显示为已读（**Mark Seen** 开启时）。

## 常见问题

### channel 启动了但什么都不做

看日志。`consent_granted is false` 说明 consent 闸门没开——这是刻意设计的阻力，请有意识地打开 **Consent Granted**。`Email channel not configured, missing: ...` 会列出六个必填字段（IMAP/SMTP 的 host、username、password）里具体哪几个是空的。

### IMAP authentication failed

Gmail 和 Outlook 开了 2FA 之后，账号密码在 IMAP/SMTP 上永远不可用——必须用 App Password。同时确认服务商设置里 IMAP 已开启；Gmail 默认是关的。

### 同一封邮件收到重复回复

**Mark Seen** 是主要的去重手段：关掉它，每次轮询都会重读同一封未读邮件。另外确保只有一个运行中的 partner 在轮询这个邮箱——两个实例会互相打架。

### 和自动回复机器人互刷

如果 Partner 给一个会自动回复的地址发信（休假自动回复、其他 bot），双方可能每个轮询周期互怼一轮。把 **Allow From** 收紧，陌生人的自动回复直接挡在门外；紧急时关掉 **Auto Reply Enabled** 当刹车。

### 回信进了垃圾箱

设置一个正经的 **From Address**；自建域名要补上 SPF/DKIM/DMARC 记录，或者把出站邮件中转到可信的 SMTP 服务。
