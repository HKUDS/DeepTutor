---
title: Turn 协议
description: 统一 turn WebSocket 上的客户端命令和服务端事件。
quadrant: reference
---

Web 界面和 `deeptutor run --format json` 共用同一个套接字：

```text
WS /ws
```

命令和事件是 `deeptutor/api/contracts/turn_protocol.py` 里的模型。多余字段会被拒绝。当前命令的 `protocol_version` 为 `"2.0"`。如何打开套接字和完成认证，写在 [HTTP API](/zh-cn/developers/reference/http-api/)。

## 命令

| `type` | 必填字段 |
| --- | --- |
| `start_turn` 或 `message` | Turn 请求：`content`，以及可选的 `capability`、`session_id`、`tools`、`knowledge_bases`、`language`、`config`、`skills`、引用和 `attachments`。`skills` 会与当前工作区允许的技能取交集来收窄 `read_skill` 可见范围（省略或传 `[]` 继承工作区全部可见技能）。 |
| `subscribe_turn` | `turn_id`，可选 `after_seq` |
| `subscribe_session` | `session_id`，可选 `after_seq` |
| `resume_from` | `turn_id`，可选 `seq` |
| `unsubscribe` | `turn_id` 或 `session_id` |
| `cancel_turn` | `turn_id`、`command_id` |
| `regenerate` | `session_id`，可选 `overrides` |
| `submit_user_reply` | `SubmitUserReplyCommand` 上定义的回复 |
| `ping` | 无 |

订阅会在 `after_seq` 之后重放事件。结束的 turn 以 `done` 收尾。失败的 turn 会先发出 `error`。

## 事件

`stage_start`、`stage_end`、`thinking`、`observation`、`content`、`tool_call`、`tool_result`、`progress`、`sources`、`result`、`error`、`session`、`session_meta`、`wait_for_input`、`done`。

同一套接字上的控制消息还有 `pong`、命令确认和协议错误。字段以 `turn_protocol.py` 里对应的模型为准。
