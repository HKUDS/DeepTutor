---
title: International IM
description: Which built-in international and asynchronous channels fit which kind of partner.
quadrant: explanation
---

These channels deliver the same partner outside the domestic set. Email is in this group because it is an asynchronous inbox, not a regional IM.

| Channel | Connection | Fits |
| --- | --- | --- |
| [Telegram](/channels/international/telegram/) | Bot API long-poll | The shortest setup: a BotFather token and no public URL |
| [Discord](/channels/international/discord/) | Gateway WebSocket | A Discord server or DMs |
| [Slack](/channels/international/slack/) | Socket Mode | A Slack workspace, including threads |
| [Microsoft Teams](/channels/international/msteams/) | Bot Framework webhook | Teams, with a public messaging endpoint |
| [WhatsApp](/channels/international/whatsapp/) | An external bridge | WhatsApp through that bridge runtime |
| [Matrix](/channels/international/matrix/) | Sync against a homeserver | Rooms on a homeserver you choose, with optional encryption |
| [Zulip](/channels/international/zulip/) | Event queue | Stream and topic conversations |
| [Mattermost](/channels/international/mattermost/) | Native v4 WebSocket | A Mattermost server you host |
| [Email](/channels/international/email/) | IMAP poll and SMTP reply | An inbox, when a delayed reply is acceptable |

Shared switches and per-card fields are in the [channel schema](/channels/schema/).
