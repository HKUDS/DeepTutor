---
title: Create a partner
description: Create one partner, talk to it in the app, then deliver one reply through a single channel.
quadrant: how-to
---

A partner is a persistent companion on the same chat loop as [Chat](/learning-workspace/chat/). It has its own soul, library, and memory. A channel only delivers that loop to an external app.

Partners used to be a separate TutorBot engine with `deeptutor bot` commands and YAML channels. Those URLs redirect here. The companion now runs as a scoped chat turn, and channels are cards in the partner UI.

## Create one and send one message

1. Open **Partners** and choose **New partner**.
2. Set **Identity** (name and default reply language) and **Soul** (role and tone). The first reply uses this soul.
3. In **Mind**, pick a model. Leave extra tools off until the first reply works.
4. In **Library**, copy one small knowledge base or skill into a private library, or bind one existing workspace. Finish the wizard.
5. Open the partner's **Chat** tab and send one question. Continue only after it answers in the soul you wrote.
6. Open **Channels**, enable one channel, and save. Use your own sender id in **Allow From**. Keep **Send Progress** and **Send Tool Hints** on for this test.
7. Send one message from that app. The reply should land in the same thread you see in the partner's Chat tab.

Field names for the card are in the [channel schema](/channels/schema/). Choose the app in [Domestic IM](/channels/domestic/) or [International IM](/channels/international/).

You own the partners you create. An admin can assign one to other people; they can talk to it and cannot see its credentials. Each person gets a private conversation and relationship memory.

## See also

- [My Agents](/customize/agents/) — consult a partner from a normal chat turn
- [Memory](/learning-workspace/memory/) — what the partner can read and write
