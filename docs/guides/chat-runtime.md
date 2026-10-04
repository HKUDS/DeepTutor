# 聊天 / Agent 运行时代码导读

覆盖聊天主链路：turn 生命周期、WebSocket 传输与重连、`ask_user` 交互、长会话渲染边界。
会话历史的持久化细节与 Memory 不在本文（另见 session-history 导读）。
所有结论附 `path:line`，行号基于 main @ ef2d9e5c3（v1.6.12）。

## 模块地图

一条 turn 从命令到流式事件经过四层：

| 层 | 入口 | 职责 |
| --- | --- | --- |
| WS 适配 | `deeptutor/api/routers/unified_ws.py:43` | 鉴权、协议校验、命令分发、订阅转发 |
| 应用服务 | `deeptutor/app/service.py:19` | 持久化 turn 行、租约检查、僵尸回收、订阅重放 |
| Turn 运行时 | `deeptutor/services/session/turn_runtime.py:26` | 派生执行器：租约续期、命令泵、事件日志 |
| 编排/能力 | `deeptutor/runtime/orchestrator.py:51`、`deeptutor/agents/chat/capability.py:12` | 路由到 capability，跑 agentic loop，产出 StreamEvent |

前端对应三层：

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 传输客户端 | `web/features/chat/transport/TurnRuntimeClient.ts:90` | 原始 socket、序号缓冲、断线重连、命令 ACK |
| 兼容门面 | `web/features/chat/transport/UnifiedTurnClient.ts:93` | 把 v2 协议事件翻译成旧 StreamEvent 形状 |
| 状态适配 | `web/features/chat/ChatStateAdapter.tsx:1785` | reducer 状态机、会话加载、发送/回复/取消 |

支撑设施：`TurnEngine`（`deeptutor/runtime/turn_engine.py:11`）是 SDK/CLI 的稳定入口；
`StreamBus`（`deeptutor/runtime/stream_bus.py:31`）做进程内 fan-out，`register_bus`（:363）
让 `user_input` 命令能找到活跃 bus；协调器协议在 `deeptutor/runtime/coordination/protocol.py:11`
（租约/事件/命令三个流），有 memory 与 redis 两个实现（`coordination/memory.py`、`coordination/redis.py`）。

## Turn 生命周期与状态机

持久化状态只有五个：`queued → running ⇄ waiting_input → completed/failed/cancelled`
（`deeptutor/api/contracts/turn_protocol.py:16-30`）。关键点：

1. **入队**：`unified_ws.py:220` 收到 `start_turn`/`message`，调 `TurnApplicationService.start_turn`
   （`app/service.py:35`）。会话已有活跃 turn 时抛 `ActiveTurnConflict`，先尝试回收无主行再重试一次
   （`app/service.py:53-59`，回收逻辑 :313-353）。
2. **执行**：executor 的 `_run_turn`（`deeptutor/services/session/turns/executor.py:141`）组装
   `UnifiedContext`，经 `TurnEngine.execute`（`runtime/turn_engine.py:17`）进
   `ChatOrchestrator.handle`（`runtime/orchestrator.py:61`）。orchestrator 先发 SESSION 事件
   （:119），再为该 turn 建 StreamBus 并注册（:128-131），capability 在独立 task 里跑（:186）。
3. **消费者停止 ≠ 停止执行**：capability task 与订阅解耦；消费者提前退出时 orchestrator 显式
   cancel 残留 task（`orchestrator.py:191-200`，PR #1413 的修复点）。
4. **DONE 不是最后一个事件**：executor 扣住 DONE 直到非终止事件全部落库、终态行 CAS 成功后才发布
   （`executor.py:1161-1177`）；之后还有会话标题等 post-DONE 元数据（:1180-1186）。
   订阅端因此读两个源：先重放持久事件，再跟 live 流，DONE 后继续读到租约消失或 30s 上限
   （`app/service.py:135`、`subscribe_turn` :143-233）。
5. **终态兜底**：终态行存在但没有 DONE 事件（旧数据）时，订阅端合成一个 done
   （`app/service.py:206-231`）。

租约模型：执行器每 turn 拿 `TurnLease`，后台循环续期并消费命令
（`deeptutor/services/session/turns/lifecycle.py:228-303`）。“活着”的判据是租约，不是行状态或
`updated_at`——park 在 ask_user 上的 turn 不产生事件但仍续租（`app/service.py:325-333` 注释）。

## WebSocket 传输与重连

### 协议

v2 协议命令：`start_turn / ping / subscribe_turn / resume_from / subscribe_session /
check_active_turn / unsubscribe / cancel_turn / submit_user_reply / regenerate / user_input`
（`deeptutor/api/routers/unified_ws.py:220-372`；类型定义 `deeptutor/api/contracts/turn_protocol.py:69-214`）。
服务端事件带单调 `seq`，`command_ack` / `protocol_error` / `active_turn_info` / `pong` 是控制事件。
客户端解析层：`web/contracts/parse/turn-event.ts:33`。

### 断线重连（前端）

- 退避：250ms 起、×2 指数、上限 8s、抖动 0.8–1.2（`web/features/chat/transport/reconnect-policy.ts:1-15`）。
- 是否续连：有活跃 turn 永远重试；无活跃 turn 只在前台且少于 5 次时重试
  （`reconnect-policy.ts:17-24`）。页面回前台立即补连（`TurnRuntimeClient.ts:186-189`）。
- 重连后先发 `resume_turn{turn_id, after_seq}` 续传（`TurnRuntimeClient.ts:270-274`），
  再 flush 未 ACK 的持久命令（:275、:400-407）。`cancel_turn / submit_user_reply / user_input`
  需要服务端 ACK（:58-62），重连重发直到 ack 抵达或客户端 stop（:234-263）。
- 序号缓冲：gap ≤ 32 先缓存并起 replay probe（`TurnRuntimeClient.ts:327-347`、:420-434），
  probe 到期发 `resume_turn` 要持久重放；`done` 观察到后停止 probe（:363-370）。
  React 状态晚于 socket 一拍时不允许光标回退（:176-183）。

### 重放（后端）

`TurnApplicationService.subscribe_turn` 先重放 `store.get_events`，再轮询
`coordinator.read_events`（`app/service.py:143-233`）；跨进程重启后仍能从持久日志补齐。
`deeptutor/api/routers/unified_ws.py:140-157` 把订阅包成 task，每个 socket 可同时挂多个 turn 订阅。

## ask_user 交互环

1. **payload 构造**：`deeptutor/tools/ask_user.py:102`（`build_ask_user_payload`）把 1–4 个结构化问题
   规范成 `AskUserPayload`；流式中途用 `build_ask_user_preview`（:160）让卡片边生成边渲染，
   并丢弃 json_repair 伪造的半截选项（:217-235）。
2. **暂停信号**：tool 结果带 `pause_for_user`（`deeptutor/runtime/agentic/tool_dispatch.py:780`），
   dispatch 汇总成 `DispatchOutcome.pause`（:907-914）；agentic loop 收到后进入
   `resolve_pause`（`deeptutor/runtime/agentic/loop.py:103`、:366-367）。
3. **等待**：pipeline 调 `context.runtime.wait_for_user_reply`（`deeptutor/agents/loop/pipeline.py:1170-1182`）。
   executor 在 turn 开始前就建好 per-turn 回复队列（`executor.py:180-181`），等待时把持久状态
   CAS 成 `waiting_input`（:186-196），恢复时 CAS 回 `running`（:200-217）。
4. **送达**：前端 `submitUserReply`（`web/features/chat/ChatStateAdapter.tsx:3103-3140`）发
   `submit_user_reply` 命令 → WS（`unified_ws.py:305-326`）→ 应用服务（`app/service.py:284-311`，
   无租约时同步回收僵尸行）→ 命令泵读出（`lifecycle.py:241-277`）→ `submit_user_reply` 入队
   （:325-352）→ `reply_queue.get()` 解除 pipeline 等待。
5. **续跑与痕迹**：回复进入 transcript 的 trace 事件带 `ask_user_resolved`
   （`pipeline.py:1196-1209`）；卡片渲染读 `tool_result.metadata.ask_user`
   （`web/components/chat/home/AskUserOptions.tsx:919` 起），提交入口从 composer 复用
   （`web/features/chat/components/ChatWorkspace.tsx:1907`、:2639）。
6. **等不到 waiter 时**：租约活着但 waiter 队列丢了 → 取消执行并写终态流
   （`lifecycle.py:267-277`，PR #1373）；orchestrator 侧消费者停止时 cancel capability
   （`orchestrator.py:191-200`，PR #1413）。

## 长会话渲染边界

- **全量加载**：`loadSession` 一次拉整条会话（`ChatStateAdapter.tsx:2411-2417`，
  `web/lib/session-api.ts:267`），后端 `GET /api/sessions/<id>` 不分页。
- **树形可见路径**：消息按 `parent_message_id` 组成编辑分支树，UI 只渲染 root→leaf 一条路径，
  分叉点默认取最新子节点（`web/lib/message-branches.ts:101-159`）；ChatMessageList 调用点
  `web/features/chat/messages/ChatMessageList.tsx:1957`。**一条游离分支即可截断整条可见路径**——
  这是 #1614 只渲染前 7 轮的直接机制。
- **新消息挂哪**：发送时取可见路径 tip 作为 `parent_message_id`；tip 仍是乐观负 id 时省略键，
  由后端追加到最新持久行（`ChatStateAdapter.tsx:3060-3066`；`tipMessageId`
  `message-branches.ts:221-227`）。可见路径被截断时 tip 就是错的 → 新消息错误分叉（#1614 症状 3）。
- **乐观 id 对账**：turn DONE 后用 `web/lib/turn-reconcile.ts` 把负 id 换成服务端 id，并重映射
  `selectedBranches`。
- **上下文侧**：滚动摘要水位 `summary_up_to_msg_id` 必须落在本 turn 祖先链上，否则清零重建
  （`deeptutor/services/session/context_builder.py:493-504`），这是“助手失忆”的服务端防线。

## 常见故障点

| 症状 | 机制 | 首查位置 |
| --- | --- | --- |
| 会话发不出新消息（锁死） | 僵尸活跃行阻塞 `_begin_turn_sync` | `app/service.py:313-353`（按租约回收）、`tests/app/test_blocked_session_reclaims_itself.py` |
| 卡片提交失败“问题已失效” | 提交窗口(2s) < 单级重连退避(8s)，或服务端拒绝 | 门：`ChatStateAdapter.tsx:2244-2282`、`web/context/QuizFollowupContext.tsx:392-408`、`web/app/(workspace)/learning/books/components/BookChatPanel.tsx:279-283`、`web/app/(workspace)/whisper/page.tsx:183-206`；拒绝文案 `web/lib/ask-user-state.ts:16` |
| 卡片永远转圈 | ack 永不到达 | `TurnRuntimeClient.ts:210-219`（waiter 随 stop 释放）、`web/tests/turn-runtime-client.test.ts:322` |
| 断线后丢事件/重复事件 | seq gap 处理 | `TurnRuntimeClient.ts:318-356`、`app/service.py:157-174` |
| DONE 后标题不更新 | post-DONE 尾巴被提前断流 | `app/service.py:112-141`、executor `:1180-1224` |
| 长会话只渲染前几轮 | 游离分支截断可见路径 | `message-branches.ts:101-159`、孤立树兜底 :45-80（#912） |
| 助手“失忆” | 水位不在祖先链或可见路径截断 | `context_builder.py:493-504` |
| 重启后 turn 卡 running | 租约过期 → 后台恢复写 worker_lost | `app/service.py:355-424`、`tests/app/test_waiting_turn_recovery.py` |

## 关联 issue 的代码位置与测试空白

上游均未关闭（2026-10-04 核对）；已有 PR 的本卡不重复实现。

### #1648 — ask_user 提交撞上重连窗口（PR #1668 open）
- 门逻辑四处复制：`ChatStateAdapter.tsx:2245`、`QuizFollowupContext.tsx:393`、
  `BookChatPanel.tsx:283`、`whisper/page.tsx:192`（均 10×200ms=2s）。
  退避阶梯上限 8s：`reconnect-policy.ts:1-2`。拒绝文案：`ask-user-state.ts:16-17`。
- 测试空白：没有“socket 重连中提交 ask_user 回复、在退避阶梯内最终送达”的用例；
  `turn-runtime-client.test.ts` 只覆盖单测层，四处门的集成行为无测试。

### #1359 — ask_user 后卡片报错且会话锁死（PR #1363 closed、#1373/#1413 merged）
- 后端修复已合入：waiter 丢失写终态（`lifecycle.py:267-277`）、消费者停止 cancel capability
  （`orchestrator.py:191-200`）、僵尸行回收（`app/service.py:295-353`）。
  Python 测试已覆盖：`tests/app/test_multiworker_turn_reply_after_queue_drop.py`、
  `tests/app/test_turn_parked_on_ask_user_is_reclaimable.py`、
  `tests/app/test_blocked_session_reclaims_itself.py`、`tests/api/test_unified_ws_turn_runtime.py`。
- 测试空白：前端没有覆盖“卡片提交被服务端拒绝后 composer 仍可继续发消息”的端到端断言
  （`ChatWorkspace.tsx:1907` 的 fallthrough 只有零散单测）；四处提交门与后端
  `turn_not_waiting_input` ack（`unified_ws.py:317-325`）之间无契约测试。

### #1614 — 长会话只渲染前 ~7 轮且新消息错挂父节点（PR #1619 open）
- 机制位置：可见路径走树 `message-branches.ts:101-159`；渲染调用
  `ChatMessageList.tsx:1957`；新消息 parent 取自可见 tip `ChatStateAdapter.tsx:3060-3066`；
  服务端水位防线 `context_builder.py:493-504`。
- 测试空白：`web/tests/orphaned-tree.test.ts` 只测孤立树，没有 600+ 消息、中途分叉的长会话
  回归用例；没有“提交后 parent 必须落在真实 tip 而非被截断 tip”的断言；
  `context_builder.py` 水位清零分支（:498-503）无直接单测
  （仅间接覆盖于 `tests/app/test_multiworker_turn_reply_after_queue_drop.py`）。

## 建议阅读顺序

1. `unified_ws.py` 命令分发 → 2. `app/service.py` start/subscribe/回收 →
3. `lifecycle.py` 命令泵 → 4. `executor.py` 事件落库与 DONE → 5. `orchestrator.py` + agentic loop
→ 6. 前端 `TurnRuntimeClient` → `ChatStateAdapter` reducer → `ChatMessageList` 渲染。
