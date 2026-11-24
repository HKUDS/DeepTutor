---
title: WhatsApp
description: 通过外部 Node.js bridge（WhatsApp Web 协议）把 Partner 接入 WhatsApp。
quadrant: how-to
---

<img src="/channel-icons/whatsapp.svg" alt="" width="40" height="40" />

`whatsapp` channel 通过一个**外部 Node.js bridge** 进程把 Partner 接到 WhatsApp 账号。DeepTutor 和 bridge 之间走 WebSocket；bridge 负责登录 WhatsApp Web（扫一次码）并双向转发消息。这绕开了官方 WhatsApp Business API 的门槛——不需要企业认证、没有按条计费——代价是多跑一个进程。

![WhatsApp 渠道配置](/screenshots/dev/partners-channel-whatsapp.png)

bridge 发布 QR/status 事件后，卡片会在浏览器渲染二维码与实时状态。在那里扫码并观察 **Waiting for scan** 进入 **Connected**；bridge 终端只作为旧版本的后备。

## 安装依赖

Python 侧依赖在 Partners extra 里。bridge 另外需要一台 Node.js 18+ 的机器，可以和 DeepTutor 同机。

```bash
python scripts/install_extras.py partners
# 或发布包支持 extras 时：
pip install "deeptutor[partners]"
```

## 运行 bridge

DeepTutor 本身不带 bridge 实现。任何基于 [@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys)、说下面这套 JSON 协议的 bridge 都可以用。一个最小实现：

```javascript
// bridge.js
const { default: makeWASocket, useMultiFileAuthState } = require('@whiskeysockets/baileys')
const WebSocket = require('ws')

const wss = new WebSocket.Server({ port: 3001 })
let waSocket = null

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState('./auth')
  waSocket = makeWASocket({ auth: state, printQRInTerminal: true })
  waSocket.ev.on('creds.update', saveCreds)
  waSocket.ev.on('messages.upsert', ({ messages, type }) => {
    if (type !== 'notify') return
    const message = messages[0]
    if (!message || message.key.fromMe) return

    const chatJid = message.key.remoteJid || ''
    const senderJid = message.key.participant || chatJid
    const content = message.message?.conversation
      || message.message?.extendedTextMessage?.text
      || ''
    if (!chatJid || !senderJid || !content) return

    const envelope = JSON.stringify({
      type: 'message',
      id: message.key.id || '',
      sender: chatJid,
      pn: senderJid,
      content,
      media: [],
      timestamp: Number(message.messageTimestamp || Math.floor(Date.now() / 1000)),
      isGroup: chatJid.endsWith('@g.us'),
    })
    wss.clients.forEach(client => {
      if (client.readyState === WebSocket.OPEN) client.send(envelope)
    })
  })
}

wss.on('connection', (ws) => {
  ws.on('message', (raw) => {
    const message = JSON.parse(raw.toString())
    if (message.type !== 'send' || !message.to || !message.text) return
    waSocket?.sendMessage(message.to, { text: message.text })
  })
})

start()
```

```bash
npm install @whiskeysockets/baileys ws
node bridge.js
```

bridge 的 `qr` 事件会显示在 DeepTutor 渠道卡片中（示例 bridge 也可能同时打印）。手机上打开 **WhatsApp -> 设置 -> 已关联的设备 -> 关联新设备**，扫描浏览器卡片。建议用进程管理器（`pm2`、systemd）守护 bridge；DeepTutor 断线后每 5 秒自动重连。

### Bridge 协议

- 连接建立时，如果配置了 **Bridge Token**，DeepTutor 会先发 `{"type": "auth", "token": "..."}`。
- bridge 发给 DeepTutor：`{"type": "message", "id": ..., "sender": ..., "pn": ..., "content": ..., "media": ["/path", ...], "timestamp": ..., "isGroup": ...}`。媒体文件由 bridge 下载到本地路径后通过 `media` 传入，DeepTutor 会作为图片/文件附件处理。
- DeepTutor 发给 bridge：`{"type": "send", "to": "<jid>", "text": "..."}`。
- bridge 还可以发 `{"type": "status"}`、`{"type": "qr"}`、`{"type": "error"}` 事件。

语音消息暂不支持转写，会以占位文本进入对话。

## 配置 channel card

打开 **Partners -> 你的 partner -> Channels -> WhatsApp**。

| 字段 | 怎么填 |
| --- | --- |
| **Send Progress** | 测试时建议开启。长任务会把过程 narration 发到 WhatsApp。 |
| **Send Tool Hints** | 调试时建议开启；不想让用户看到一行工具调用就关掉。 |
| **Enabled** | bridge 跑起来、准备启动 channel 时再打开。 |
| **Bridge Url** | bridge 的 WebSocket 地址，默认 `ws://localhost:3001`。 |
| **Bridge Token** | 可选共享密钥。只有你的 bridge 校验 `auth` 消息时才需要填。 |
| **Allow From** | 一行一个值。测试可填 `*` 表示开放；上线后换成具体 sender id（WhatsApp id 里 `@` 前面那段，通常是手机号）。空列表拒绝所有人。 |

## 配置完成之后

1. 保存 card，**Enabled** 打开。
2. 从 UI 或 CLI 启动（或重启）partner，让 channel 加载新配置。
3. 观察服务端日志出现 `Connected to WhatsApp bridge`。
4. 给登录在 bridge 上的 WhatsApp 号码发一条短消息。
5. 在日志里看到真实 sender id 之后，把 **Allow From** 的 `*` 换成明确值。

```bash
deeptutor partner start <partner-id>
```

## 如何确认健康

健康的 WhatsApp channel 通常有三个迹象：

- DeepTutor 渠道卡片进入 **Connected**，不再刷新二维码；
- DeepTutor 日志出现 `Connected to WhatsApp bridge`；
- 允许的发送者发一条短消息后，Partner 能正常回复。

## 常见问题

### Bridge 连不上 / channel 一直重连

日志反复出现 `WhatsApp bridge connection error` 和 `Reconnecting in 5 seconds...`。检查 bridge 进程是否在跑、**Bridge Url** 的主机和端口是否正确。DeepTutor 会一直重试，bridge 恢复后 channel 自动复原。

### Bridge 反复打印二维码

bridge 的登录状态没有持久化。确认它的 auth 目录（示例里是 `./auth`）可写且重启后还在。另外手机离线约两周后 WhatsApp Web 会话会过期，重新扫码即可恢复。

### 收得到消息但回复发不出去

如果 bridge 在回合中途断线，DeepTutor 回复时日志会出现 `WhatsApp bridge not connected`。等 bridge 恢复连接后再发一条新消息。入站消息按 id 去重，bridge 重连不会产生重复回答。
