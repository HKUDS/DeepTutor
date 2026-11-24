---
title: WhatsApp
description: Connect a Partner to WhatsApp through an external Node.js bridge that speaks the WhatsApp Web protocol.
quadrant: how-to
---

<img src="/channel-icons/whatsapp.svg" alt="" width="40" height="40" />

The `whatsapp` channel connects a Partner to a WhatsApp account through an **external Node.js bridge** process. DeepTutor talks to the bridge over a WebSocket; the bridge logs into WhatsApp Web (one QR scan) and relays messages in both directions. This avoids the friction of the official WhatsApp Business API — no verified business, no per-message fees — at the cost of running one extra process.

![WhatsApp channel configuration](/screenshots/dev/partners-channel-whatsapp.png)

When the bridge publishes QR/status events, the card renders the code and live state in the browser. Scan there and watch **Waiting for scan** become **Connected**; the bridge terminal is a fallback for older bridge builds.

## Install requirements

The Python side is included with the Partners extra. The bridge additionally needs a Node.js 18+ host — it can be the same machine as DeepTutor.

```bash
python scripts/install_extras.py partners
# or, from an installed release when partners extras are available:
pip install "deeptutor[partners]"
```

## Run the bridge

DeepTutor does not ship the bridge itself. Any bridge built on [@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys) that speaks the JSON protocol below works. A minimal bridge:

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

The bridge's `qr` event appears in the DeepTutor channel card (and may also be printed by the sample bridge). On your phone: **WhatsApp -> Settings -> Linked devices -> Link a device** -> scan the browser card. Run the bridge under a process manager (`pm2`, systemd) so it survives crashes; DeepTutor reconnects to it automatically every 5 seconds.

### Bridge protocol

- On connect, DeepTutor sends `{"type": "auth", "token": "..."}` when **Bridge Token** is set.
- Bridge to DeepTutor: `{"type": "message", "id": ..., "sender": ..., "pn": ..., "content": ..., "media": ["/path", ...], "timestamp": ..., "isGroup": ...}`. Media must be downloaded by the bridge to local paths; DeepTutor attaches them as files/images.
- DeepTutor to bridge: `{"type": "send", "to": "<jid>", "text": "..."}`.
- The bridge may also emit `{"type": "status"}`, `{"type": "qr"}`, and `{"type": "error"}` events.

Voice messages are not transcribed yet; they arrive as a placeholder note.

## Configure the channel card

Open **Partners -> your partner -> Channels -> WhatsApp**.

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It sends narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if you do not want users to see one-line tool calls. |
| **Enabled** | Turn on only when the bridge is running and you are ready to start the channel. |
| **Bridge Url** | WebSocket URL of the bridge. Default: `ws://localhost:3001`. |
| **Bridge Token** | Optional shared secret. Set it only if your bridge checks the `auth` message. |
| **Allow From** | One value per line. Use `*` for an open test channel, or specific sender ids (the part before `@` in WhatsApp ids — usually the phone number). Empty denies access. |

## After you save

1. Save the card with **Enabled** on.
2. Start (or restart) the partner from the UI or CLI so the channel picks up the config.
3. Watch the server log for `Connected to WhatsApp bridge`.
4. Send a short message to the WhatsApp number that is logged into the bridge.
5. Once you see real sender ids in the logs, replace `*` in **Allow From** with explicit values.

```bash
deeptutor partner start <partner-id>
```

## Verify it is healthy

A healthy WhatsApp channel has three signs:

- the DeepTutor channel card reaches **Connected** and stops showing fresh QR codes;
- the DeepTutor log shows `Connected to WhatsApp bridge`;
- a short message from an allowed sender produces a Partner reply.

## Troubleshooting

### Bridge unreachable / channel keeps reconnecting

The log shows `WhatsApp bridge connection error` followed by `Reconnecting in 5 seconds...`. Check that the bridge process is running and that **Bridge Url** points at the right host and port. DeepTutor retries forever, so the channel recovers on its own once the bridge is back.

### The bridge keeps printing QR codes

The bridge's auth state is not being persisted. Make sure its auth directory (`./auth` in the sample) is writable and survives restarts. WhatsApp Web sessions also expire when the phone is offline for around two weeks — re-scan and the session resumes.

### Messages arrive but replies are dropped

If the bridge disconnects mid-turn, the log shows `WhatsApp bridge not connected` when DeepTutor tries to reply. Restore the bridge connection and send a fresh message. Inbound messages are deduplicated by id, so bridge reconnects do not produce duplicate answers.
