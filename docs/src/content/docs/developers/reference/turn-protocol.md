---
title: Turn protocol
description: Client commands and server events on the unified turn WebSocket.
quadrant: reference
---

The web UI and `deeptutor run --format json` share one socket:

```text
WS /ws
```

Commands and events are the models in `deeptutor/api/contracts/turn_protocol.py`. Extra fields are rejected. Current commands set `protocol_version` to `"2.0"`. How to open the socket and authenticate is on the [HTTP API](/developers/reference/http-api/) page.

## Commands

| `type` | Required fields |
| --- | --- |
| `start_turn` or `message` | The turn request: `content`, and optional `capability`, `session_id`, `tools`, `knowledge_bases`, `language`, `config`, `skills`, references, and `attachments`. `skills` narrows `read_skill` to its intersection with the workspace allowlist (omitting or sending `[]` inherits the workspace's visible set). |
| `subscribe_turn` | `turn_id`, optional `after_seq` |
| `subscribe_session` | `session_id`, optional `after_seq` |
| `resume_from` | `turn_id`, optional `seq` |
| `unsubscribe` | `turn_id` or `session_id` |
| `cancel_turn` | `turn_id`, `command_id` |
| `regenerate` | `session_id`, optional `overrides` |
| `submit_user_reply` | The reply payload defined on `SubmitUserReplyCommand` |
| `ping` | none |

Subscriptions replay events after `after_seq`. A terminal turn ends with `done`. A failed turn emits `error` first.

## Events

`stage_start`, `stage_end`, `thinking`, `observation`, `content`, `tool_call`, `tool_result`, `progress`, `sources`, `result`, `error`, `session`, `session_meta`, `wait_for_input`, `done`.

Control messages on the same socket also include `pong`, a command acknowledgement, and a protocol error. Their fields are the corresponding models in `turn_protocol.py`.
