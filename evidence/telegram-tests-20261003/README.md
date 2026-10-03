# Telegram 通道消息解析与发送 — 失败测试集说明

- 基线：`origin/main` @ `ef2d9e5c3`（release v1.6.12），覆盖缺口 #17（`deeptutor/partners/channels/telegram.py`，418 缺失 / 30.2%）
- 测试文件：`tests/services/partners/test_telegram_message_parsing.py`（30 例）
- 分支：`myfork/test/telegram-message-parsing-20261003`（仅新增测试与证据，**未改任何产品代码**）

## 运行方式

```bash
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/services/partners/test_telegram_message_parsing.py -v
# 汇总：2 failed / 28 passed（失败为设计内红测试，对应下述 2 个真实缺陷）
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/services/partners/ -q
# 全目录：589 passed + 上述 2 failed，无既有用例回归
```

环境：mock SDK（SimpleNamespace/AsyncMock 替身 `channel._app.bot`），不需要真实 Telegram token，不连网；媒体落盘经 `partners_root` 夹具隔离到 `tmp_path`。`telegram`（python-telegram-bot 22.8）缺失时整文件 skip（模块级 `importorskip`）。

## 设计内红测试（2 个真实缺陷，2 例）

| # | 缺陷 | 定位（origin/main） | 红测试 | 修复建议 |
|---|------|--------------------|--------|----------|
| 1 | 相册（media group）补发消息被静默丢弃：`_flush_media_group` 先 `pop` 缓冲区再分发，`finally` 才移除 flush task；分发窗口内同 `media_group_id` 的滞后消息会写入**新建**缓冲区，但 `key in self._media_group_tasks` 成立 → 不会调度新 flush task → 消息永久滞留、缓冲区泄漏 | `telegram.py:994-1010`（`_flush_media_group` + `_on_message` media-group 分支 977-978） | `test_media_group_straggler_during_flush_is_not_dropped` | 先从 `_media_group_tasks` 弹出自身 task 再分发；或分发完成后复查 `_media_group_buffers`，若同 key 缓冲区重新出现则补调度一次 flush |
| 2 | ACL 拒绝后 typing 指示器永不停：`_on_message` 在 `_handle_message` 做 ACL 检查**之前**就 `_start_typing`；被拒用户永远收不到回复（也就永远不会触发 `send()` 里的 `_stop_typing`），4 秒一次的 `send_chat_action` 循环持续到通道重启 | `telegram.py:982`（typing 启动点）+ `base.py:225`（ACL 拒绝点） | `test_denied_sender_typing_indicator_is_stopped` | 在 `_start_typing` 前先做 `self.is_allowed(sender_id)` 预检，或让 `_handle_message` 返回是否放行、被拒时 `_stop_typing` |

## 绿测试清单（钉住现状，防回归）

- 入站解析：私聊文本 → bus 契约（sender_id `id|username`、字符串 chat_id、metadata 全字段）；论坛话题消息派生 `telegram:<chat>:topic:<thread>` session key
- 回复上下文：reply 长文本截断到 `TELEGRAM_REPLY_CONTEXT_MAX_LEN`+`...`；reply 纯媒体消息附加 `[Reply to: [image: …]]` 标签且媒体前置
- 媒体解析：相册两条缓冲后合并为一轮（contents 以 `\n` 连接、task 清理）；photo 取**最大尺寸**（`photo[-1]`）下载 `.jpg` 并附 `[image: path]`；voice 下载 `.ogg` + 转写占位 `[transcription: …]`；document 保留原始扩展名；媒体下载失败降级 `[image: download failed]` 不崩溃
- 群策略路由：mention 策略下无 @ 跳过；`@tutorbot` 文本命中进群 chat；open 策略群媒体直通；`_has_mention_entity`（mention 实体 / text_mention 实体 / 文本回退 / 非 bot 提及不误判）；`is_allowed` 的 `id|username`、`*`、空表、畸形格式判定
- 长文本分片：2000 词超长文本按 4000 切片发送（每片 ≤ 4000、词序完整）；`send_delta` 收尾 HTML 超 4096 时拆主消息 + 追加消息；`_flush_stream_overflow` 编辑首片、补发中片、用尾片重开流消息（`buf.text`/`message_id` 状态正确）；HTML 解析失败回退纯文本（无 `parse_mode`）；`replyToMessage` 开启时回复带 `reply_parameters` + 话题 `message_thread_id`
- 出站媒体：按扩展名分派 `send_photo`/`send_document`；发送失败降级 `[Failed to send: name]`；非法 chat_id 静默丢弃不崩溃
- typing 生命周期：入站消息启动 typing（首拍 `send_chat_action(typing)`）；`_progress` 发送不停 typing、最终发送停止并取消 task；`_start_typing` 替换旧 task；循环重复发送直到 cancel；`_app` 置空后循环自退；`stop()` 清空全部 typing task

## 备注

- 流式基础协议（首 delta 建消息、节流编辑、新 `_stream_id` 开新消息）已由 `test_channel_streaming.py` 覆盖，本文件不重复。
- 与飞书同类卡（`myfork/test/feishu-message-parsing-20261003`）同一"红优先契约"模式：绿测试钉现状，红测试即修复卡的验收标准。
- 修复卡可直接按上表领取：每条红测试的断言即期望行为，修复后全量 `pytest tests/services/partners/` 应 591 passed / 0 failed。
