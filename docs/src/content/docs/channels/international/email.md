---
title: Email
description: Configure the email channel for a Partner using IMAP polling for inbound mail and SMTP replies.
quadrant: how-to
---

<img src="/channel-icons/email.svg" alt="" width="40" height="40" />

The `email` channel turns a Partner into an asynchronous mailbox correspondent: it polls an IMAP inbox for unread mail and answers through SMTP. There is no realtime connection — turnaround is one poll cycle — which makes it a natural fit for help-desk style support and for users who simply prefer email over chat apps.

![Email channel configuration](/screenshots/dev/partners-channel-email.png)

While the Partner is running, use the card's live status first: **Listener running** confirms the polling loop is active, while **Configuration required** names missing setup before you inspect logs.

## Install requirements

Nothing extra. The email channel is built entirely on Python's standard library (`imaplib` + `smtplib`), so every DeepTutor install can run it — no additional pip packages, no extras.

## Prepare a mail account

The Partner needs its own mailbox with IMAP and SMTP access. Do not reuse a personal inbox: the channel reads and replies to everything unread.

**Gmail**

1. Enable 2-Step Verification on the account.
2. Create an [App Password](https://myaccount.google.com/apppasswords) — a 16-character password used in place of the account password. With 2FA on, regular passwords are rejected for IMAP/SMTP.
3. Make sure IMAP is on: Gmail Settings -> **Forwarding and POP/IMAP** -> Enable IMAP.
4. Hosts: `imap.gmail.com:993` (SSL) and `smtp.gmail.com:587` (STARTTLS).

**Outlook / Office 365** — with 2FA enabled, an App Password works the same way if your tenant allows them; otherwise ask your admin.

**Self-hosted** (Postfix, Maddy, ...) — use the account credentials directly and fill in your own hosts and ports.

## Configure the channel card

Open **Partners -> your partner -> Channels -> Email**.

Card fields for this channel are in the [channel schema](/channels/schema/#email).


Each unique sender address is its own session, and replies carry `In-Reply-To` headers so they thread correctly in the sender's mail client.

## After you save

1. Click **Save**, then turn on both **Enabled** and **Consent Granted** and save again.
2. Start the partner — from the UI, or `deeptutor partner start <partner-id>`. If it is already running, restart it so the channel picks up the new config.
3. Send a test email from an address listed in **Allow From** and wait up to one poll interval for the reply.
4. Once replies flow, replace `*` in **Allow From** with the real addresses you want to serve.

## Verify it is healthy

A healthy email channel has three signs:

- the log shows `Starting Email channel (IMAP polling mode)...` with no `missing:` or consent warnings;
- a test mail from an allowed sender gets a reply within roughly one poll interval;
- processed messages show up as read in the mailbox (when **Mark Seen** is on).

## Troubleshooting

### The channel starts and then does nothing

Check the log. `consent_granted is false` means the consent gate is off — that is deliberate friction, flip **Consent Granted** consciously. `Email channel not configured, missing: ...` lists exactly which of the six required fields (IMAP/SMTP host, username, password) are empty.

### IMAP authentication failed

On Gmail and Outlook with 2FA, the account password never works for IMAP/SMTP — you need an App Password. Also confirm IMAP is enabled in the provider's settings; Gmail ships with it off.

### Duplicate replies to the same email

**Mark Seen** is the primary dedup: if it is off, every poll re-reads the same unread mail. Also make sure only one running partner polls this mailbox — two instances will race each other.

### Reply storms with auto-responders

If the Partner mails an address that auto-replies (vacation responders, other bots), the two can loop once per poll interval. Keep **Allow From** tight so strangers' auto-replies are dropped at the gate, and use **Auto Reply Enabled** off as an emergency brake.

### Replies land in spam

Set a proper **From Address**, and for self-hosted domains add SPF/DKIM/DMARC records or relay outbound mail through a trusted SMTP service.
