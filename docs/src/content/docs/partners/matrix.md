---
title: Matrix
description: Configure the Matrix channel for a Partner — any homeserver, long-poll sync, optional end-to-end encryption.
quadrant: how-to
---

<img src="/channel-icons/matrix.svg" alt="" width="40" height="40" />

The `matrix` channel connects a Partner to decentralized Matrix rooms through the standard client-server API. Any homeserver works — matrix.org, or your self-hosted Synapse / Conduit / Dendrite — and end-to-end encryption is available as an opt-in so most installs do not pay the libolm dependency cost.

![Matrix channel configuration](/screenshots/dev/partners-channel-matrix.png)

While the Partner is running, use the card's live status first: it distinguishes a connected sync loop from missing Matrix dependencies or configuration before you inspect logs.

## Install requirements

Matrix is **not** part of the Partners extra — it ships as two extras of its own:

```bash
# plain Matrix (unencrypted rooms)
python scripts/install_extras.py matrix

# Matrix including end-to-end encrypted rooms
python scripts/install_extras.py matrix-e2e
```

- `[matrix]` installs `matrix-nio`, `mistune`, and `nh3`. This is enough for direct chats and unencrypted rooms.
- `[matrix-e2e]` adds `matrix-nio[e2e]`, which pulls `python-olm` — and that needs the native **libolm** library installed first:

```bash
# macOS
brew install libolm

# Debian / Ubuntu
sudo apt-get install libolm-dev
```

For Docker/CI without a source checkout, the same sets are mirrored in `requirements/matrix.txt` and `requirements/matrix-e2e.txt`.

If you skip the extras entirely, the channel fails at import time with `Matrix dependencies not installed`.

## Create a bot account and get an access token

The Partner needs its own Matrix account on any homeserver — matrix.org is fine for testing.

1. Create the account: Element web app -> your homeserver -> Create Account (or `register_new_matrix_user` on self-hosted Synapse).
2. Get the access token, either way:
   - **Element**: sign in as the bot, **Settings -> Help & About -> Advanced -> Access Token**, reveal and copy.
   - **REST API**:

```bash
curl -X POST https://matrix.org/_matrix/client/r0/login \
  -H "Content-Type: application/json" \
  -d '{"type": "m.login.password", "user": "my-bot", "password": "your-password"}'
# the response contains "access_token": "syt_..."
```

## Configure the channel card

Open **Partners -> your partner -> Channels -> Matrix**.

| Field | What to enter |
| --- | --- |
| **Send Progress** | Keep on while testing. It sends narration updates during long turns. |
| **Send Tool Hints** | Keep on for debugging; turn off if you do not want users to see one-line tool calls. |
| **Enabled** | Turn on when you are ready to start the channel. |
| **Homeserver** | Default `https://matrix.org`. Use your own server's URL if self-hosted. |
| **Access Token** | The token from Element or the login API. Stored as a secret. |
| **User Id** | The bot's full Matrix id, e.g. `@my-bot:matrix.org`. Also used to detect mentions. |
| **Device Id** | Optional but recommended: pick any stable string and keep it. If blank, a restart may replay recent messages. |
| **E2Ee Enabled** | Turn on only after installing the `[matrix-e2e]` extra plus libolm. Without them the bot cannot decrypt encrypted rooms. |
| **Sync Stop Grace Seconds** | Default `2`. How long an in-flight sync may finish during shutdown. Rarely changed. |
| **Max Media Bytes** | Default `20971520` (20 MB). Size cap for attachment uploads and downloads. |
| **Allow From** | One Matrix user id per line, e.g. `@frank:matrix.org`. `*` for an open test channel. Empty denies everyone — including room invites. |
| **Group Policy** | For multi-person rooms: `open` (default) answers every message, `mention` answers only when the bot is mentioned, `allowlist` answers only in rooms listed below. Direct 1:1 chats are always answered. |
| **Group Allow From** | Room ids (`!abc123:matrix.org`), one per line. Only used with the `allowlist` policy. |
| **Allow Room Mentions** | Whether an `@room` ping counts as mentioning the bot under the `mention` policy. Off by default. |

## After you save

1. Click **Save**, then turn on **Enabled** and save again.
2. Start the partner — from the UI, or `deeptutor partner start <partner-id>`. If it is already running, restart it.
3. Invite the bot from any Matrix client: `/invite @my-bot:matrix.org`. The bot only accepts invites from senders that pass **Allow From** — with an empty list it will never join.
4. Send a short message in the room and check the reply.
5. Once it works, replace `*` in **Allow From** with real user ids.

Markdown in replies is rendered as Matrix HTML, so tables and code blocks display correctly in Element and other clients.

## Verify it is healthy

A healthy Matrix channel has three signs:

- the log shows the sync loop running with no repeated sync errors;
- the bot joins a room within seconds of an invite from an allowed sender;
- a short message in that room produces a Partner reply.

Note the privacy boundary: E2EE protects the transport between Matrix clients and the bot, but message text still reaches your configured LLM provider in plaintext. If that matters, pair the channel with a local model.

## Troubleshooting

### The bot joins but never answers in an encrypted room

**E2Ee Enabled** is on without the `[matrix-e2e]` extra (or libolm), or it is off while the room is encrypted. Install libolm, then `python scripts/install_extras.py matrix-e2e`, turn the toggle on, and restart the partner.

### `M_UNKNOWN_TOKEN`

The access token was invalidated — usually by logging the bot out from another client, or a server-side reset. Fetch a fresh token via Element or the login API and update the card.

### The first sync takes a long time

An account with a long history syncs a large initial batch; this is normal and only happens once per device. Set a stable **Device Id** so later restarts resume incrementally instead of starting over.

### The bot ignores my invite

The inviter must pass **Allow From**. Add your own Matrix user id (or `*` while testing), save, and re-invite.
