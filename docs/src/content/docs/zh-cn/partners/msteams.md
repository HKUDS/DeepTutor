---
title: Microsoft Teams
description: 为 Partner 配置 Microsoft Teams 渠道——Azure Bot 注册、公网 messaging endpoint、入站 JWT 校验。
quadrant: how-to
---

<img src="/channel-icons/msteams.svg" alt="" width="40" height="40" />

`msteams` channel 通过 **Bot Framework** 把 Partner 接到 Microsoft Teams。和 DeepTutor 其他所有 channel 不一样，它不是主动外连：它内置了一个小型 **HTTP 服务器**（默认 `0.0.0.0:3978`，路径 `/api/messages`），由微软的服务器把每条消息 POST 过来。所以你需要一个**公网可达的 HTTPS endpoint**——生产环境在端口前面架一层反向代理（nginx、Caddy、Cloudflare Tunnel 都行），再把 Azure Bot 的 messaging endpoint 指过来。本地测试用 `ngrok http 3978` 这类隧道就够了。

**每个启用 Teams 的 Partner 都必须使用独立 bind port。** 每个 Partner 会启动自己的 HTTP server，因此同一主机上的两个 Teams channel 不能共用同一组 host/port。请把每个 Partner 的公网 messaging endpoint 分别转发到它自己的端口。

当前能力范围以私聊为主：文本进、文本出。群聊和频道消息会被忽略，附件暂不支持。

![Microsoft Teams 渠道配置](/screenshots/dev/partners-channel-msteams.png)

Partner 运行时先看卡片实时状态：**Listener running** 表示 webhook server 已绑定，失败状态会在查日志前指出端口或配置问题。

## 安装依赖

Teams 支持已包含在 Partners extra 里。入站请求用 `PyJWT[crypto]` 做校验，它也已经在内——不需要额外安装任何东西。

```bash
python scripts/install_extras.py partners
# 或发布包支持 extras 时：
pip install "deeptutor[partners]"
```

## 在 Azure 注册机器人

1. 在 [Azure Portal](https://portal.azure.com/) 打开 **Microsoft Entra ID -> App registrations -> New registration**。起个名字，选好账户类型（单租户即可），完成注册。复制 **Application (client) ID**——这就是 **App Id**；再复制 **Directory (tenant) ID**——这就是 **Tenant Id**。
2. 在这个注册下打开 **Certificates & secrets -> New client secret**，立刻复制 secret 的 **Value**（只显示这一次）——这就是 **App Password**。
3. 创建一个 **Azure Bot** 资源（在 marketplace 里搜 "Azure Bot"）。*Microsoft App ID* 选 **Use existing app registration**，填入你的 App Id。租户类型要和注册保持一致：单租户的注册就建单租户的 bot。
4. 在 bot 资源里进 **Settings -> Configuration**，把 **Messaging endpoint** 设成你的公网 HTTPS 地址，结尾必须是 channel 的路径，比如 `https://bots.example.com/api/messages`。
5. 进 **Settings -> Channels**，添加 **Microsoft Teams** channel。
6. 想直接开聊，点 Teams channel 那一行的 **Open in Teams** 链接；要在组织内分发，就打一个引用同一 App Id 的 Teams 应用 manifest 包。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> Microsoft Teams**。

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

## 保存之后

1. 点 **Save**，把 **Enabled** 打开。
2. 启动 partner（已在运行的话重启，或在 Channels 面板上用 reload）。
3. 从外网验证 endpoint 可达：`curl -X POST https://your-domain/api/messages -H 'Content-Type: application/json' -d '{}'` 应该返回 **401**（JWT 校验把你拦下来了）——如果是连接错误，说明代理链路有问题。
4. 用允许的账号在 Teams 里打开机器人（**Open in Teams** 链接），私聊发一条短消息。
5. 在日志里确认 sender id 之后，把 **Allow From** 里的 `*` 换成真实 id。

## 如何确认健康

- 启动日志出现 `MSTeams webhook listening on http://0.0.0.0:3978/api/messages`。
- 对公网 endpoint 发一个不带凭证的 POST 返回 401 而不是超时——代理链路通了，JWT 门也立着。
- 允许的账号私聊能收到回复，并出现 `data/partners/<partner-id>/channels/msteams/msteams_conversations.json`——conversation reference 在正常持久化。

## 常见问题

### Teams 提示消息发送失败

messaging endpoint 不可达。确认 endpoint URL 以你配置的 **Path** 结尾、HTTPS 证书有效、反向代理转发到了 **Host**:**Port**。用上面清单里那条 `curl` 一步就能定位。

### 所有入站请求都被 401 拒绝

入站 JWT 校验没过。最常见的原因是 channel card 里的 **App Id** 和 bot 注册对不上——token 的 audience 必须等于 App Id。如果最近重建过注册，记得更新 card。除了本地测试，不要用关闭 **Validate Inbound Auth** 来绕过这个问题。

### 回复时报 token 错误

收得到但发不出，这是租户的坑：**单租户**注册却把 **Tenant Id** 留空，DeepTutor 会去多租户 endpoint 换 token，微软直接拒绝。把 **Tenant Id** 填成 Directory (tenant) ID 再保存即可。

### 私聊正常但群聊和频道不理人

设计如此：channel 目前只做私聊。非私聊会话到达即丢弃（**Prune Non Personal Refs** 开着时，存储里的 reference 也会被清掉）。

## 相关页面

- [Channel Matrix](/zh-cn/partners/channels/) — 所有 channel 一览
- [WeCom](/zh-cn/partners/wecom/) — 企业微信接入，另一种企业 IM 路线
