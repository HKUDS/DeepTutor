---
title: HTTP API
description: deeptutor serve 暴露的 HTTP 和 WebSocket 表面 —— 用于自定义前端和集成。
quadrant: reference
---

`deeptutor serve` 在 `http://localhost:8001/` 上启动 FastAPI 后端（除非你改了后端端口）。本页是给自定义前端、移动 App 和服务间集成准备的高密度地图。Turn 命令和事件见 [Turn 协议](/zh-cn/developers/reference/turn-protocol/)。

要看穷尽且永远最新的 schema，启动服务后打开：

```text
GET /openapi.json     # 完整 OpenAPI 3.1 spec
GET /docs             # 交互式 Swagger UI
GET /redoc            # 备选的 ReDoc UI
```

## 启动服务

```bash
# 仅后端。端口取自 data/user/settings/system.json，默认 8001。
deeptutor serve

# 给本次进程指定自定义 host/port
deeptutor serve --host 127.0.0.1 --port 18001

# 开发模式：Python 文件变动时热重载
deeptutor serve --reload
```

## 鉴权

开启鉴权后，多数路由要求 Bearer JWT 或 `dt_token` cookie。登录/初始化可公开，资料/管理受保护；`GET /api/settings/ui` 公开。MarginNote `/sync`、`/heartbeat` 使用 `Authorization: MarginNote <device_id>:<token>`。

```bash
# 登录
curl -X POST http://localhost:8001/api/auth/login \
  -c cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"..."}'

# 响应是用户元数据；JWT 写入 dt_token cookie。

# 复用 cookie
curl -b cookies.txt http://localhost:8001/api/sessions
```

如果鉴权没开，认证依赖就是 no-op，本地单用户请求不需要带 token。

## Turn 执行 WebSocket

```text
WS /ws
```

这是 Web UI 在用的统一 turn WebSocket。它对所有 capability 一视同仁，输出的事件和 `deeptutor run --format json` 打印的是同一族。

发一个 `type: "start_turn"` 或 `type: "message"` 载荷启动 turn：

```json
{
  "type": "start_turn",
  "protocol_version": "2.0",
  "content": "Find d/dx [sin(x^2)]",
  "capability": "deep_solve",
  "session_id": null,
  "tools": ["reason"],
  "knowledge_bases": ["math"],
  "language": "en",
  "config": {},
  "notebook_references": [],
  "history_references": [],
  "partner_group_references": [],
  "attachments": []
}
```

上面只是单轮 turn 的载荷本身。`/ws` 上的每个 client 帧都必须带 `"protocol_version": "2.0"`——`start_turn`、`subscribe_turn`、`cancel_turn`、`ping` 都一样。缺这个字段的帧会先收到 `protocol_error` 事件（`error_code: "unsupported_protocol_version"`），此时还不会对载荷做任何命令模型的校验。

`skills` 不是无效字段，而是用来收窄本轮的：它会和当前工作区允许的技能取交集，所以指定了 skill 的 turn 里，`read_skill` 只能看到这几个。省略该字段或传空数组表示继承工作区允许的全部可见 skill。turn 的选择永远不会超出工作区允许的范围。

其他 client 类型包括 `subscribe_turn`、`resume_from`、`cancel_turn`、`submit_user_reply`、`regenerate` 等；订阅按 `after_seq` 补帧，终态必收 `done`（失败先 `error`）。

典型收到的事件：

```json
{"type":"stage_start","stage":"responding"}
{"type":"tool_call","content":"rag","metadata":{"args":{"query":"chain rule","kb_name":"math"}}}
{"type":"tool_result","content":"...","metadata":{"tool":"rag"}}
{"type":"content","content":"## Solution\n\nThe derivative..."}
{"type":"stage_end","stage":"responding"}
{"type":"done","session_id":"sess_abc123","turn_id":"turn_xyz789","metadata":{"status":"completed"}}
```

## WebSocket 接口

```text
WS /ws
WS /ws/books
WS /ws/questions/mimic
WS /ws/questions/generate
WS /ws/questions/judge
WS /ws/knowledge-bases/{kb_name}/progress
WS /ws/mastery-paths
WS /ws/partners/{partner_id}
WS /ws/partner-groups/{group_id}
```

旧的 `/api/v1/chat`、`/api/v1/ws` 与各功能的 API-prefixed socket 均已移除。上面是完整的规范 WebSocket namespace；`/ws` 统一处理所有 turn capability、回放、取消、重新生成与 `ask_user` 回复。

## Session

```text
GET    /api/sessions                              列 session
GET    /api/sessions/{session_id}                 拿到一个 session + 消息
PATCH  /api/sessions/{session_id}                 重命名（body: {"title":"..."}）
DELETE /api/sessions/{session_id}                 删除
PUT    /api/sessions/{session_id}/branch-selection
DELETE /api/sessions/{session_id}/messages/{message_id}
POST   /api/sessions/{session_id}/quiz-results
```

其他会话状态接口：

```text
GET   /api/sessions/{session_id}/ask-hint
PATCH /api/sessions/{session_id}/organization
```

## 知识库

```text
GET    /api/knowledge-bases                           列 KB
GET    /api/knowledge-bases/{kb_name}                 KB 信息
DELETE /api/knowledge-bases/{kb_name}                 删除
POST   /api/knowledge-bases                           创建 KB
POST   /api/knowledge-bases/{kb_name}/upload          添加文档
POST   /api/knowledge-bases/{kb_name}/reindex         重新 embed 文档
GET    /api/knowledge-bases/default                   获取默认 KB
PUT    /api/knowledge-bases/default/{kb_name}         设置默认 KB
GET    /api/knowledge-bases/supported-file-types      支持的上传格式
GET    /api/knowledge-bases/{kb_name}/files           列源文件
GET    /api/knowledge-bases/{kb_name}/files/{filename}  取单个源文件（预览/下载）
GET    /api/knowledge-bases/{kb_name}/file-preview-text/{filename}  提取的纯文本预览
GET    /api/knowledge-bases/{kb_name}/progress        索引进度
WS     /ws/knowledge-bases/{kb_name}/progress         `task_id` 回放终态；孤立任务 → `knowledge_task_interrupted`
```

临时的 KB 搜索目前是通过 RAG 运行时 / tool 路径暴露的，当前 API 里没有专门的 `POST /knowledge/{name}/search` 路由。从 CLI 走，用 `deeptutor kb search <name> <query>`。

## Notebook

```text
GET    /api/notebooks
GET    /api/notebooks/statistics
POST   /api/notebooks
GET    /api/notebooks/{notebook_id}
PUT    /api/notebooks/{notebook_id}
DELETE /api/notebooks/{notebook_id}
POST   /api/notebooks/actions/add-record
POST   /api/notebooks/actions/add-record-with-summary
DELETE /api/notebooks/{notebook_id}/records/{record_id}
PUT    /api/notebooks/{notebook_id}/records/{record_id}
POST   /api/notebooks/{notebook_id}/records/{record_id}/actions/copy
POST   /api/notebooks/{notebook_id}/records/{record_id}/actions/move
GET    /api/notebooks/{notebook_id}/export
```

## Memory

```text
GET    /api/memory/overview
GET    /api/memory/doc/{layer}/{key}
PUT    /api/memory/doc/{layer}/{key}
POST   /api/memory/doc/{layer}/{key}/reset
POST   /api/memory/doc/{layer}/{key}/update
POST   /api/memory/doc/{layer}/{key}/audit
POST   /api/memory/doc/{layer}/{key}/dedup
POST   /api/memory/runs/start
GET    /api/memory/runs
GET    /api/memory/runs/{run_id}
GET    /api/memory/runs/{run_id}/events?since=N    绝对 N = last_seen_seq + 1
POST   /api/memory/runs/{run_id}/cancel
POST   /api/memory/runs/{run_id}/undo
GET    /api/memory/trace/{surface}
DELETE /api/memory/trace/{surface}
GET    /api/memory/settings
PUT    /api/memory/settings
```

层级是 `L2` 和 `L3`；例：`/api/memory/doc/L3/profile` 和 `/api/memory/doc/L2/chat`。

## Settings、tools、visualizers 和 system

```text
GET  /api/settings
GET  /api/settings/catalog
PUT  /api/settings/catalog
POST /api/settings/apply
POST /api/settings/model-capabilities
PUT  /api/settings/enabled-tools
GET  /api/tools
GET  /api/system/status
GET  /api/system/memory
GET  /api/system/runtime
GET  /api/system/update
POST /api/system/update/check
PUT  /api/system/update/settings
GET  /api/system/update/job
POST /api/system/update
POST /api/system/test/llm
POST /api/system/test/embeddings
POST /api/system/test/search
GET    /api/visualizers/list
POST   /api/visualizers/bundled/{visualizer_id}/install
POST   /api/visualizers/{visualizer_id}/enable
POST   /api/visualizers/{visualizer_id}/disable
DELETE /api/visualizers/{visualizer_id}
POST   /api/visualizers/import
GET    /api/visualizers/{visualizer_id}/assets/{asset_path}
```

Provider profile 通过 catalog endpoint 编辑；当前 API 里没有单独的 `/settings/llm` 或 `/settings/embedding` 路由。Capability 走统一 WebSocket / CLI 合约。Visualizer 导入的是声明式浏览器包，不是可执行的后端插件。

## Partners Manager

```text
GET    /api/partners
POST   /api/partners
GET    /api/partners/recent
GET    /api/channels/schema/schema
GET    /api/partners/tool-options
GET    /api/partners/souls
POST   /api/partners/souls
GET    /api/partners/soul-sources
GET    /api/partners/{partner_id}
PATCH  /api/partners/{partner_id}
POST   /api/partners/{partner_id}/start
POST   /api/partners/{partner_id}/stop
DELETE /api/partners/{partner_id}
POST   /api/partners/{partner_id}/channels/reload
GET    /api/partners/{partner_id}/channels/status
POST   /api/partners/{partner_id}/channel-onboarding/start
GET    /api/partners/{partner_id}/channel-onboarding/{session_id}
DELETE /api/partners/{partner_id}/channel-onboarding/{session_id}
POST   /api/partners/{partner_id}/channel-onboarding/{session_id}/apply
GET    /api/partners/{partner_id}/soul
PUT    /api/partners/{partner_id}/soul
GET    /api/partners/{partner_id}/assets
POST   /api/partners/{partner_id}/assets
DELETE /api/partners/{partner_id}/assets/{asset_type}/{name}
GET    /api/partners/{partner_id}/history
GET    /api/partners/{partner_id}/sessions
POST   /api/partners/{partner_id}/sessions/archive
POST   /api/partners/{partner_id}/sessions/resume
POST   /api/partners/{partner_id}/sessions/delete
POST   /api/partners/{partner_id}/sessions/branch
POST   /api/partners/{partner_id}/chat
POST   /api/partners/{partner_id}/chat/execute-stream
WS     /ws/partners/{partner_id}
```

已认证用户可创建 Partner。资源路由检查 **use** 或 **manage** 权限；owner/admin 可管理，grant 可仅允许对话。Secret 默认打码，除非可管理调用方请求 `include_secrets=true`。

## Book Engine

```text
GET    /api/books
POST   /api/books
GET    /api/books/block-types                         可生成的内容类型
GET    /api/books/{book_id}
GET    /api/books/{book_id}/spine
GET    /api/books/{book_id}/pages/{page_id}
DELETE /api/books/{book_id}
POST   /api/books/confirm-proposal
POST   /api/books/confirm-spine
POST   /api/books/compile-page
POST   /api/books/pause                               先持久化、取消工作、保留已完成页
POST   /api/books/resume                              只排入未完成页
POST   /api/books/{book_id}/refresh-fingerprints
WS     /ws/books                                      订阅传 `after_seq`；可能先确认 reset
```

## 沉浸式阅读

```text
GET    /api/reading/supported-formats          支持的扩展名、体积上限、可原样查看的格式
GET    /api/reading/materials                  列出本账号的素材
POST   /api/reading/materials                  上传文档（multipart）
GET    /api/reading/materials/{material_id}    清单：单元类型、单元数量、大纲
DELETE /api/reading/materials/{material_id}    忘掉某份素材
GET    /api/reading/materials/{material_id}/units/{locator}      单个单元的文本
GET    /api/reading/materials/{material_id}/revisions             之前不可变的 URL 快照
GET    /api/reading/materials/{material_id}/revisions/{revision}/units/{locator}
GET    /api/reading/materials/{material_id}/raw                  原始字节（PDF）
GET    /api/reading/materials/{material_id}/assets/{asset_name}  经鉴权的快照图片
GET    /api/reading/materials/{material_id}/bookmarks            列出书签
POST   /api/reading/materials/{material_id}/bookmarks            保存书签
DELETE /api/reading/materials/{material_id}/bookmarks/{bookmark_id}
GET    /api/reading/materials/{material_id}/annotations          列出批注
PUT    /api/reading/materials/{material_id}/annotations          创建或更新一条；返回 AnnotationInfo
DELETE /api/reading/materials/{material_id}/annotations/{id}     删除一条
GET    /api/reading/materials/{material_id}/export?fmt=auto|pdf|markdown
```

素材以内容寻址：同样的字节上传两次会拿到同一个 `material_id`，上面已有的批注也都还在。`export?fmt=pdf` 返回写入了真正 PDF 批注的原文件，仅对保留了原始字节的素材可用。

URL 刷新会保留不可变的旧 revision。快照 asset 需要鉴权、经过 MIME sniff，并带 `nosniff` 返回，不会在阅读器中直接暴露实时第三方页面。

## 沉浸式观看

```text
GET  /api/settings/video-learning
PUT  /api/settings/video-learning
POST /api/settings/video-learning/test-invidious
POST /api/video-learning/materials/resolve
GET  /api/video-learning/materials/{material_id}
PUT  /api/video-learning/materials/{material_id}/progress
GET  /api/video-learning/materials/{material_id}/subtitles.vtt
GET|HEAD /api/video-learning/materials/{material_id}/stream/{format_id}
```

这些兼容端点保留 YouTube 播放、转录字幕与独立于 provider 的进度。当前视频会话使用 Reading，旧 Watching 会话重开时迁移。Resolve 接收 URL 及可选语言 / provider；VTT 返回归一化字幕。

## 其余路由

上面并未逐一展开所有接口。以下这些同样存在、遵循同样的约定，其 schema 请查 `/openapi.json`：

```text
/api/skills          技能库与 hub 安装
/api/personas        人设预设
/api/plugins         托管插件生命周期与审批
/api/learning-journal 工作区目标、交接与已确认记录
/api/documents       协同写作文档与编辑流
/api/mastery-paths   掌握路径、目标与进度
/api/subagents       已连接智能体的配置
/api/imports         Claude Code / Codex 对话导入
/api/space/mcp       按账号的 MCP 服务与精选目录
/api/space/cli-apps  CLI 应用目录、安装与授权
/api/voice           语音合成与语音识别
/api/dashboard       最近活动、起始建议/刷新与活动详情
```

## 输出和附件

产物通过认证路由提供：

```text
GET /files/outputs/<path>
```

仅解析调用者或单个可见 Partner 的 allowlist 文件；非法、私有、穿越路径均失败。附件挂在：

```text
GET /files/attachments/{session_id}/{attachment_id}/{filename}
```

## 生成 typed client

```bash
curl http://localhost:8001/openapi.json > deeptutor.openapi.json

# TypeScript client
npx openapi-typescript deeptutor.openapi.json -o deeptutor.d.ts

# Python client
pip install openapi-python-client
openapi-python-client generate --path deeptutor.openapi.json
```

<!-- generated-route-index -->

## 路由索引

下面的表由 `deeptutor/modules/manifests/*.json` 与 `deeptutor/api/router_index.json` 生成。路径是挂载前缀加上路由模板。字段和请求体以运行中的 `GET /openapi.json` 为准。

### books

#### `book:router` — `/api` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/books/health` |
| `GET` | `/api/books/estimate-basis` |
| `GET` | `/api/books/block-types` |
| `GET` | `/api/books` |
| `GET` | `/api/books/{book_id}/learning-captures` |
| `POST` | `/api/books/{book_id}/learning-captures` |
| `PATCH` | `/api/books/{book_id}/learning-captures/{capture_id}` |
| `GET` | `/api/books/{book_id}` |
| `GET` | `/api/books/{book_id}/spine` |
| `GET` | `/api/books/{book_id}/pages/{page_id}` |
| `DELETE` | `/api/books/{book_id}` |
| `POST` | `/api/books` |
| `POST` | `/api/books/confirm-proposal` |
| `POST` | `/api/books/confirm-spine` |
| `POST` | `/api/books/compile-page` |
| `POST` | `/api/books/regenerate-block` |
| `POST` | `/api/books/insert-block` |
| `POST` | `/api/books/delete-block` |
| `POST` | `/api/books/move-block` |
| `POST` | `/api/books/change-block-type` |
| `POST` | `/api/books/{book_id}/chapters` |
| `PATCH` | `/api/books/{book_id}/chapters/{chapter_id}` |
| `DELETE` | `/api/books/{book_id}/chapters/{chapter_id}` |
| `POST` | `/api/books/{book_id}/chapters/{chapter_id}/move` |
| `POST` | `/api/books/deep-dive` |
| `POST` | `/api/books/quiz-attempt` |
| `POST` | `/api/books/update-block` |
| `POST` | `/api/books/progress/visit` |
| `POST` | `/api/books/progress/bookmark` |
| `GET` | `/api/books/{book_id}/export` |
| `GET` | `/api/books/{book_id}/health` |
| `POST` | `/api/books/{book_id}/refresh-fingerprints` |
| `POST` | `/api/books/supplement` |
| `POST` | `/api/books/page-chat-session` |
| `POST` | `/api/books/resume` |
| `POST` | `/api/books/pause` |
| `POST` | `/api/books/rebuild` |
| `POST` | `/api/books/{book_id}/edits/preview` |
| `GET` | `/api/books/{book_id}/edits` |
| `POST` | `/api/books/{book_id}/edits/{edit_id}/apply` |
| `POST` | `/api/books/{book_id}/edits/{edit_id}/undo` |

#### `book:ws_router` — `/ws` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws/books` |

### calendar

#### `calendar:router` — `/api/calendar` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/calendar/export.ics` |
| `GET` | `/api/calendar/calendars` |
| `POST` | `/api/calendar/calendars` |
| `PATCH` | `/api/calendar/calendars/{id}` |
| `DELETE` | `/api/calendar/calendars/{id}` |
| `GET` | `/api/calendar/events` |
| `POST` | `/api/calendar/events` |
| `PATCH` | `/api/calendar/events/{id}` |
| `DELETE` | `/api/calendar/events/{id}` |
| `POST` | `/api/calendar/undo/{token}` |
| `GET` | `/api/calendar/search` |
| `GET` | `/api/calendar/layers` |
| `DELETE` | `/api/calendar/automations/{job_id}` |
| `GET` | `/api/calendar/stream` |
| `GET` | `/api/calendar/task-blocks` |

### co-writer

#### `co_writer:router` — `/api` · learning

| 方法 | 路径 |
| --- | --- |
| `POST` | `/api/documents/actions/edit` |
| `POST` | `/api/documents/actions/edit-react` |
| `POST` | `/api/documents/actions/edit-react/stream` |
| `POST` | `/api/documents/actions/automark` |
| `GET` | `/api/documents/history` |
| `GET` | `/api/documents/history/{operation_id}` |
| `GET` | `/api/documents/tool-calls/{operation_id}` |
| `GET` | `/api/documents` |
| `POST` | `/api/documents` |
| `POST` | `/api/documents/import/docx` |
| `POST` | `/api/documents/export/docx` |
| `GET` | `/api/documents/flashcards/export` |
| `GET` | `/api/documents/{doc_id}` |
| `PUT` | `/api/documents/{doc_id}` |
| `DELETE` | `/api/documents/{doc_id}` |
| `GET` | `/api/documents/{doc_id}/suggestions` |
| `POST` | `/api/documents/{doc_id}/suggestions/{suggestion_id}` |
| `GET` | `/api/documents/{doc_id}/backlinks` |
| `POST` | `/api/documents/{doc_id}/assets` |
| `GET` | `/api/documents/{doc_id}/assets/{name}` |
| `POST` | `/api/documents/{doc_id}/clips` |
| `GET` | `/api/documents/review/due` |
| `GET` | `/api/documents/{doc_id}/flashcards/export` |
| `POST` | `/api/documents/{doc_id}/review` |
| `POST` | `/api/documents/{doc_id}/suggestions` |
| `GET` | `/api/documents/{doc_id}/threads` |
| `POST` | `/api/documents/{doc_id}/threads` |
| `DELETE` | `/api/documents/{doc_id}/threads/{session_id}` |

### knowledge

#### `knowledge:router` — `/api` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/knowledge-bases/health` |
| `GET` | `/api/knowledge-bases/rag-providers` |
| `PUT` | `/api/knowledge-bases/rag-providers/{provider}/mode` |
| `GET` | `/api/knowledge-bases/rag-pipelines/pageindex/config` |
| `PUT` | `/api/knowledge-bases/rag-pipelines/pageindex/config` |
| `GET` | `/api/knowledge-bases/rag-pipelines/ima/config` |
| `PUT` | `/api/knowledge-bases/rag-pipelines/ima/config` |
| `GET` | `/api/knowledge-bases/rag-pipelines/llamaindex/config` |
| `PUT` | `/api/knowledge-bases/rag-pipelines/llamaindex/config` |
| `GET` | `/api/knowledge-bases/rag-pipelines/graphrag/config` |
| `PUT` | `/api/knowledge-bases/rag-pipelines/graphrag/config` |
| `GET` | `/api/knowledge-bases/rag-pipelines/lightrag/config` |
| `GET` | `/api/knowledge-bases/rag-pipelines/lightrag/model-options` |
| `PUT` | `/api/knowledge-bases/rag-pipelines/lightrag/config` |
| `GET` | `/api/knowledge-bases/rag-pipelines/lightrag-server/config` |
| `PUT` | `/api/knowledge-bases/rag-pipelines/lightrag-server/config` |
| `GET` | `/api/knowledge-bases/rag-pipelines/{provider}/preflight` |
| `GET` | `/api/knowledge-bases/rag-pipelines/model-options` |
| `GET` | `/api/knowledge-bases/embedding-usage` |
| `POST` | `/api/knowledge-bases/rag-pipelines/graphrag/model-compatibility` |
| `PUT` | `/api/knowledge-bases/rag-pipelines/active-model` |
| `GET` | `/api/knowledge-bases/supported-file-types` |
| `GET` | `/api/knowledge-bases/configs` |
| `GET` | `/api/knowledge-bases/{kb_name}/config` |
| `PUT` | `/api/knowledge-bases/{kb_name}/config` |
| `POST` | `/api/knowledge-bases/configs/sync` |
| `GET` | `/api/knowledge-bases/default` |
| `PUT` | `/api/knowledge-bases/default/{kb_name}` |
| `POST` | `/api/knowledge-bases/connect-obsidian` |
| `POST` | `/api/knowledge-bases/connect-marginnote4` |
| `POST` | `/api/knowledge-bases/probe-folder` |
| `POST` | `/api/knowledge-bases/connect-folder` |
| `POST` | `/api/knowledge-bases/probe-lightrag-server` |
| `POST` | `/api/knowledge-bases/connect-lightrag-server` |
| `POST` | `/api/knowledge-bases/probe-weknora` |
| `POST` | `/api/knowledge-bases/connect-weknora` |
| `POST` | `/api/knowledge-bases/list-ima` |
| `GET` | `/api/knowledge-bases/kiwix-catalog` |
| `POST` | `/api/knowledge-bases/probe-kiwix` |
| `POST` | `/api/knowledge-bases/connect-kiwix` |
| `GET` | `/api/knowledge-bases/kiwix-articles` |
| `POST` | `/api/knowledge-bases/probe-ima` |
| `POST` | `/api/knowledge-bases/connect-ima` |
| `GET` | `/api/knowledge-bases` |
| `GET` | `/api/knowledge-bases/list` |
| `GET` | `/api/knowledge-bases/{kb_name}` |
| `GET` | `/api/knowledge-bases/{kb_name}/files` |
| `POST` | `/api/knowledge-bases/{kb_name}/folders` |
| `POST` | `/api/knowledge-bases/{kb_name}/files/move` |
| `GET` | `/api/knowledge-bases/{kb_name}/file-preview-text/{filename:path}` |
| `GET` | `/api/knowledge-bases/{kb_name}/files/{filename:path}` |
| `GET` | `/api/knowledge-bases/{kb_name}/visual-assets/{asset_id}` |
| `GET` | `/api/knowledge-bases/{kb_name}/visual-coverage` |
| `GET` | `/api/knowledge-bases/{kb_name}/source-page` |
| `DELETE` | `/api/knowledge-bases/{kb_name}/files/{filename:path}` |
| `POST` | `/api/knowledge-bases/delete` |
| `DELETE` | `/api/knowledge-bases/{kb_name}` |
| `GET` | `/api/knowledge-bases/tasks/{task_id}/stream` |
| `POST` | `/api/knowledge-bases/{kb_name}/upload` |
| `POST` | `/api/knowledge-bases` |
| `GET` | `/api/knowledge-bases/{kb_name}/reindex-config` |
| `POST` | `/api/knowledge-bases/{kb_name}/reindex` |
| `PUT` | `/api/knowledge-bases/{kb_name}/indexing-policy` |
| `POST` | `/api/knowledge-bases/{kb_name}/retry` |
| `GET` | `/api/knowledge-bases/{kb_name}/indexing-run` |
| `POST` | `/api/knowledge-bases/{kb_name}/indexing-run/{task_id}/cancel` |
| `GET` | `/api/knowledge-bases/{kb_name}/indexing-readiness` |
| `GET` | `/api/knowledge-bases/{kb_name}/progress` |
| `POST` | `/api/knowledge-bases/{kb_name}/progress/clear` |
| `POST` | `/api/knowledge-bases/{kb_name}/link-folder` |
| `GET` | `/api/knowledge-bases/{kb_name}/linked-folders` |
| `DELETE` | `/api/knowledge-bases/{kb_name}/linked-folders/{folder_id}` |
| `POST` | `/api/knowledge-bases/{kb_name}/sync-folder/{folder_id}` |
| `POST` | `/api/knowledge-bases/{kb_name}/github-source` |
| `GET` | `/api/knowledge-bases/{kb_name}/github-sources` |
| `DELETE` | `/api/knowledge-bases/{kb_name}/github-source/{source_id}` |
| `POST` | `/api/knowledge-bases/{kb_name}/sync-github` |
| `POST` | `/api/knowledge-bases/{kb_name}/web-source` |
| `GET` | `/api/knowledge-bases/{kb_name}/web-sources` |
| `DELETE` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}` |
| `GET` | `/api/knowledge-bases/{kb_name}/web-source-sync` |
| `GET` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/pairings` |
| `PUT` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/schedule` |
| `POST` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/cancel` |
| `POST` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/retry` |
| `POST` | `/api/knowledge-bases/{kb_name}/sync-web` |

#### `marginnote4:router` — `/api/marginnote4` · public

| 方法 | 路径 |
| --- | --- |
| `POST` | `/api/marginnote4/pair` |
| `GET` | `/api/marginnote4/devices` |
| `DELETE` | `/api/marginnote4/devices/{device_id}` |
| `GET` | `/api/marginnote4/status` |
| `POST` | `/api/marginnote4/sync` |
| `POST` | `/api/marginnote4/heartbeat` |

#### `knowledge:ws_router` — `/ws` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws/knowledge-bases/{kb_name}/progress` |

### mastery

#### `mastery_path:router` — `/api/mastery-paths` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/mastery-paths/topics` |
| `GET` | `/api/mastery-paths/topics/index` |
| `GET` | `/api/mastery-paths/reading/records` |
| `POST` | `/api/mastery-paths/topics/draft` |
| `POST` | `/api/mastery-paths/topics` |
| `GET` | `/api/mastery-paths/topics/{path_id}` |
| `GET` | `/api/mastery-paths/topics/{path_id}/review-settings` |
| `PUT` | `/api/mastery-paths/topics/{path_id}/review-settings` |
| `GET` | `/api/mastery-paths/review-strategies` |
| `POST` | `/api/mastery-paths/review-strategies` |
| `GET` | `/api/mastery-paths/review-strategies/{template_id}` |
| `PUT` | `/api/mastery-paths/review-strategies/{template_id}` |
| `POST` | `/api/mastery-paths/review-strategies/{template_id}/duplicate` |
| `DELETE` | `/api/mastery-paths/review-strategies/{template_id}` |
| `PUT` | `/api/mastery-paths/topics/{path_id}/review-strategy` |
| `PUT` | `/api/mastery-paths/topics/{path_id}/map` |
| `POST` | `/api/mastery-paths/topics/{path_id}/objectives/{kp_id}/override` |
| `GET` | `/api/mastery-paths/topics/{path_id}/sessions` |
| `PUT` | `/api/mastery-paths/topics/{path_id}/sessions/{session_id}/mode` |
| `GET` | `/api/mastery-paths/topics/{path_id}/ask-hint` |
| `GET` | `/api/mastery-paths/progress` |
| `GET` | `/api/mastery-paths/progress/{book_id}` |
| `GET` | `/api/mastery-paths/progress/{book_id}/map` |
| `GET` | `/api/mastery-paths/progress/{book_id}/board` |
| `GET` | `/api/mastery-paths/progress/{book_id}/objectives/{kp_id}` |
| `GET` | `/api/mastery-paths/progress/{book_id}/events` |
| `GET` | `/api/mastery-paths/progress/{book_id}/sessions` |
| `POST` | `/api/mastery-paths/progress/{book_id}/init-modules` |
| `POST` | `/api/mastery-paths/progress/{book_id}/import-from-book` |
| `PATCH` | `/api/mastery-paths/progress/{book_id}` |
| `DELETE` | `/api/mastery-paths/progress/{book_id}` |
| `POST` | `/api/mastery-paths/progress/{book_id}/skip-question` |
| `POST` | `/api/mastery-paths/progress/{book_id}/redo` |
| `POST` | `/api/mastery-paths/progress/{book_id}/generate-from-notebook` |
| `POST` | `/api/mastery-paths/progress/{book_id}/generate-from-reading` |

#### `mastery_path:ws_router` — `/ws` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws/mastery-paths` |

### memory

#### `memory:router` — `/api/memory` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/memory/overview` |
| `GET` | `/api/memory/resolve_entry/{entry_id}` |
| `GET` | `/api/memory/backup` |
| `GET` | `/api/memory/doc/{layer}/{key}` |
| `PUT` | `/api/memory/doc/{layer}/{key}` |
| `DELETE` | `/api/memory/doc/{layer}/{key}/entry/{entry_id}` |
| `POST` | `/api/memory/doc/{layer}/{key}/reset` |
| `POST` | `/api/memory/runs/start` |
| `GET` | `/api/memory/runs/{run_id}` |
| `POST` | `/api/memory/runs/{run_id}/cancel` |
| `POST` | `/api/memory/runs/{run_id}/undo` |
| `GET` | `/api/memory/runs` |
| `GET` | `/api/memory/runs/{run_id}/events` |
| `POST` | `/api/memory/doc/{layer}/{key}/update` |
| `POST` | `/api/memory/doc/{layer}/{key}/audit` |
| `POST` | `/api/memory/doc/{layer}/{key}/dedup` |
| `GET` | `/api/memory/doc/{layer}/{key}/lines` |
| `GET` | `/api/memory/settings` |
| `PUT` | `/api/memory/settings` |
| `POST` | `/api/memory/doc/{layer}/{key}/apply` |
| `GET` | `/api/memory/trace/{surface}` |
| `DELETE` | `/api/memory/trace/{surface}` |
| `DELETE` | `/api/memory/trace/{surface}/day/{day}` |
| `GET` | `/api/memory/snapshot/{surface}` |
| `POST` | `/api/memory/snapshot/{surface}/refresh` |
| `GET` | `/api/memory/snapshot/{surface}/changes` |
| `DELETE` | `/api/memory/snapshot/{surface}/changes` |

### notebook

#### `notebook:router` — `/api` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/notebooks/health` |
| `GET` | `/api/notebooks` |
| `GET` | `/api/notebooks/statistics` |
| `POST` | `/api/notebooks` |
| `GET` | `/api/notebooks/{notebook_id}` |
| `PUT` | `/api/notebooks/{notebook_id}` |
| `DELETE` | `/api/notebooks/{notebook_id}` |
| `POST` | `/api/notebooks/actions/add-record` |
| `POST` | `/api/notebooks/actions/add-record-with-summary` |
| `DELETE` | `/api/notebooks/{notebook_id}/records/{record_id}` |
| `GET` | `/api/notebooks/records/{record_id}/location` |
| `PUT` | `/api/notebooks/{notebook_id}/records/{record_id}` |
| `POST` | `/api/notebooks/{notebook_id}/records/{record_id}/actions/copy` |
| `POST` | `/api/notebooks/{notebook_id}/records/{record_id}/actions/move` |
| `GET` | `/api/notebooks/{notebook_id}/export` |

### partners

#### `partner_groups:router` — `/api/partner-groups` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/partner-groups` |
| `GET` | `/api/partner-groups/discussion-modes` |
| `GET` | `/api/partner-groups/shared-memory-types` |
| `POST` | `/api/partner-groups` |
| `GET` | `/api/partner-groups/{group_id}` |
| `PATCH` | `/api/partner-groups/{group_id}` |
| `DELETE` | `/api/partner-groups/{group_id}` |
| `GET` | `/api/partner-groups/{group_id}/history` |
| `GET` | `/api/partner-groups/{group_id}/sessions` |
| `POST` | `/api/partner-groups/{group_id}/sessions` |
| `DELETE` | `/api/partner-groups/{group_id}/sessions/{session_key}` |
| `GET` | `/api/partner-groups/{group_id}/whiteboard` |
| `POST` | `/api/partner-groups/{group_id}/whiteboard/pins` |
| `DELETE` | `/api/partner-groups/{group_id}/whiteboard/pins/{event_id}` |
| `GET` | `/api/partner-groups/{group_id}/invocations` |
| `POST` | `/api/partner-groups/{group_id}/invocations` |
| `POST` | `/api/partner-groups/{group_id}/messages` |
| `POST` | `/api/partner-groups/{group_id}/turns/{turn_id}/partners/{partner_id}/retry` |
| `POST` | `/api/partner-groups/{group_id}/rounds/{turn_id}/summary` |
| `POST` | `/api/partner-groups/{group_id}/invocations/{invocation_id}/approve` |
| `POST` | `/api/partner-groups/{group_id}/invocations/{invocation_id}/reject` |

#### `partners:router` — `/api/partners` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/partners/souls` |
| `POST` | `/api/partners/souls` |
| `GET` | `/api/partners/souls/{soul_id}` |
| `PUT` | `/api/partners/souls/{soul_id}` |
| `DELETE` | `/api/partners/souls/{soul_id}` |
| `GET` | `/api/partners/soul-sources` |
| `GET` | `/api/partners` |
| `GET` | `/api/partners/navigation` |
| `GET` | `/api/partners/consultation-session` |
| `GET` | `/api/partners/recent` |
| `GET` | `/api/partners/channels/schema` |
| `POST` | `/api/partners/{partner_id}/channels/weixin/qr` |
| `GET` | `/api/partners/{partner_id}/channels/weixin/qr/{session_id}` |
| `GET` | `/api/partners/tool-options` |
| `POST` | `/api/partners` |
| `GET` | `/api/partners/drafts/{draft_id}` |
| `POST` | `/api/partners/drafts/{draft_id}/confirm` |
| `GET` | `/api/partners/{partner_id}` |
| `PATCH` | `/api/partners/{partner_id}` |
| `POST` | `/api/partners/{partner_id}/start` |
| `POST` | `/api/partners/{partner_id}/stop` |
| `DELETE` | `/api/partners/{partner_id}` |
| `POST` | `/api/partners/{partner_id}/channels/reload` |
| `GET` | `/api/partners/{partner_id}/channels/status` |
| `POST` | `/api/partners/{partner_id}/channel-onboarding/start` |
| `GET` | `/api/partners/{partner_id}/channel-onboarding/{session_id}` |
| `DELETE` | `/api/partners/{partner_id}/channel-onboarding/{session_id}` |
| `POST` | `/api/partners/{partner_id}/channel-onboarding/{session_id}/apply` |
| `GET` | `/api/partners/{partner_id}/soul` |
| `PUT` | `/api/partners/{partner_id}/soul` |
| `GET` | `/api/partners/{partner_id}/workspaces` |
| `GET` | `/api/partners/{partner_id}/assets` |
| `POST` | `/api/partners/{partner_id}/assets` |
| `DELETE` | `/api/partners/{partner_id}/assets/{asset_type}/{name}` |
| `POST` | `/api/partners/{partner_id}/links/code` |
| `GET` | `/api/partners/{partner_id}/links` |
| `DELETE` | `/api/partners/{partner_id}/links/{key:path}` |
| `GET` | `/api/partners/{partner_id}/history` |
| `GET` | `/api/partners/{partner_id}/history/page` |
| `GET` | `/api/partners/{partner_id}/web-continuity` |
| `PUT` | `/api/partners/{partner_id}/web-continuity` |
| `GET` | `/api/partners/{partner_id}/sessions` |
| `POST` | `/api/partners/{partner_id}/sessions/archive` |
| `POST` | `/api/partners/{partner_id}/sessions/resume` |
| `POST` | `/api/partners/{partner_id}/sessions/delete` |
| `POST` | `/api/partners/{partner_id}/sessions/branch` |
| `GET` | `/api/partners/commands/palette` |
| `POST` | `/api/partners/{partner_id}/chat` |
| `POST` | `/api/partners/{partner_id}/chat/execute-stream` |

#### `partner_groups:ws_router` — `/ws/partner-groups` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws/partner-groups/{group_id}` |

#### `partners:ws_router` — `/ws/partners` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws/partners/{partner_id}` |

### questions

#### `question:router` — `/api/question` · learning

| 方法 | 路径 |
| --- | --- |

#### `question_notebook:router` — `/api/question-notebook` · learning

| 方法 | 路径 |
| --- | --- |
| `POST` | `/api/question-notebook/entries/upsert` |
| `GET` | `/api/question-notebook/entries` |
| `GET` | `/api/question-notebook/entries/lookup/by-question` |
| `GET` | `/api/question-notebook/entries/{entry_id}` |
| `PATCH` | `/api/question-notebook/entries/{entry_id}` |
| `DELETE` | `/api/question-notebook/entries/{entry_id}` |
| `POST` | `/api/question-notebook/entries/categories/bulk` |
| `POST` | `/api/question-notebook/entries/{entry_id}/categories` |
| `DELETE` | `/api/question-notebook/entries/{entry_id}/categories/{category_id}` |
| `GET` | `/api/question-notebook/stats` |
| `GET` | `/api/question-notebook/materials` |
| `GET` | `/api/question-notebook/categories` |
| `POST` | `/api/question-notebook/categories` |
| `PATCH` | `/api/question-notebook/categories/{category_id}` |
| `DELETE` | `/api/question-notebook/categories/{category_id}` |

#### `practice:router` — `/api/question-notebook/practice` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/question-notebook/practice/summary` |
| `GET` | `/api/question-notebook/practice/queue` |
| `GET` | `/api/question-notebook/practice/analytics` |
| `GET` | `/api/question-notebook/practice/questions/{entry_id}` |
| `POST` | `/api/question-notebook/practice/questions/{entry_id}/check` |
| `POST` | `/api/question-notebook/practice/questions/{entry_id}/review` |
| `GET` | `/api/question-notebook/practice/import/template` |
| `POST` | `/api/question-notebook/practice/import/preview` |
| `POST` | `/api/question-notebook/practice/import/commit` |

#### `question:ws_router` — `/ws/questions` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws/questions/mimic` |
| `WS` | `/ws/questions/generate` |

### reading

#### `reading:router` — `/api/reading` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/reading/library/materials` |
| `POST` | `/api/reading/library/duplicate-check` |
| `POST` | `/api/reading/library/import-urls` |
| `POST` | `/api/reading/library/import-zim-article` |
| `POST` | `/api/reading/materials/{material_id}/retry` |
| `GET` | `/api/reading/workspaces` |
| `GET` | `/api/reading/workspaces/index` |
| `POST` | `/api/reading/workspaces` |
| `GET` | `/api/reading/workspaces/{workspace_id}` |
| `GET` | `/api/reading/workspaces/{workspace_id}/ask-hint` |
| `PATCH` | `/api/reading/workspaces/{workspace_id}` |
| `DELETE` | `/api/reading/workspaces/{workspace_id}` |
| `POST` | `/api/reading/workspaces/{workspace_id}/materials` |
| `PUT` | `/api/reading/workspaces/{workspace_id}/materials/order` |
| `PUT` | `/api/reading/workspaces/{workspace_id}/materials/{material_id}/active` |
| `DELETE` | `/api/reading/workspaces/{workspace_id}/materials/{material_id}` |
| `GET` | `/api/reading/workspaces/{workspace_id}/sessions` |
| `POST` | `/api/reading/workspaces/{workspace_id}/sessions` |
| `PATCH` | `/api/reading/workspaces/{workspace_id}/sessions/{session_id}` |
| `DELETE` | `/api/reading/workspaces/{workspace_id}/sessions/{session_id}` |
| `POST` | `/api/reading/workspaces/{workspace_id}/sessions/{session_id}/links` |
| `DELETE` | `/api/reading/workspaces/{workspace_id}/sessions/{session_id}/links/{target_session_id}` |
| `POST` | `/api/reading/workspaces/{workspace_id}/notes/organize` |
| `POST` | `/api/reading/workspaces/{workspace_id}/notebook` |
| `GET` | `/api/reading/supported-formats` |
| `GET` | `/api/reading/materials` |
| `POST` | `/api/reading/materials` |
| `GET` | `/api/reading/materials/{material_id}` |
| `GET` | `/api/reading/materials/{material_id}/epub-pairing-candidates` |
| `GET` | `/api/reading/epub-pairings` |
| `POST` | `/api/reading/epub-pairings` |
| `DELETE` | `/api/reading/epub-pairings/{pairing_id}` |
| `DELETE` | `/api/reading/materials/{material_id}` |
| `GET` | `/api/reading/materials/{material_id}/transcript` |
| `GET` | `/api/reading/materials/{material_id}/units/{locator}` |
| `GET` | `/api/reading/materials/{material_id}/revisions` |
| `GET` | `/api/reading/materials/{material_id}/revisions/{revision}/units/{locator}` |
| `GET` | `/api/reading/materials/{material_id}/raw` |
| `GET` | `/api/reading/materials/{material_id}/render` |
| `GET` | `/api/reading/materials/{material_id}/assets/{asset_name}` |
| `GET` | `/api/reading/materials/{material_id}/media` |
| `GET` | `/api/reading/materials/{material_id}/media/{name}` |
| `GET` | `/api/reading/materials/{material_id}/annotations` |
| `GET` | `/api/reading/materials/{material_id}/position` |
| `PUT` | `/api/reading/materials/{material_id}/position` |
| `GET` | `/api/reading/materials/{material_id}/bookmarks` |
| `POST` | `/api/reading/materials/{material_id}/bookmarks` |
| `DELETE` | `/api/reading/materials/{material_id}/bookmarks/{bookmark_id}` |
| `PUT` | `/api/reading/materials/{material_id}/annotations` |
| `DELETE` | `/api/reading/materials/{material_id}/annotations/{annotation_id}` |
| `GET` | `/api/reading/materials/{material_id}/export` |

#### `reading_extensions:router` — `/api/reading` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/reading/extensions` |
| `POST` | `/api/reading/materials/{material_id}/read-aloud` |
| `POST` | `/api/reading/materials/{material_id}/extensions/{extension_id}/actions/{action}` |
| `POST` | `/api/reading/materials/{material_id}/extensions/quiz/answers` |
| `GET` | `/api/reading/materials/{material_id}/quiz/rewards` |

#### `video_learning:settings_router` — `/api/settings/video-learning` · admin

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/settings/video-learning` |
| `PUT` | `/api/settings/video-learning` |
| `POST` | `/api/settings/video-learning/test-invidious` |

#### `video_learning:router` — `/api/video-learning` · learning

| 方法 | 路径 |
| --- | --- |
| `POST` | `/api/video-learning/invidious/account/authorize` |
| `GET` | `/api/video-learning/invidious/account/callback` |
| `GET` | `/api/video-learning/invidious/browse/{kind}` |
| `GET` | `/api/video-learning/invidious/account/status` |
| `POST` | `/api/video-learning/invidious/account/disconnect` |
| `POST` | `/api/video-learning/materials/resolve` |
| `GET` | `/api/video-learning/materials/{material_id}` |
| `POST` | `/api/video-learning/materials/{material_id}/transcript/refresh` |
| `PUT` | `/api/video-learning/materials/{material_id}/progress` |
| `GET` | `/api/video-learning/materials/{material_id}/notes` |
| `GET` | `/api/video-learning/materials/{material_id}/notes.md` |
| `POST` | `/api/video-learning/materials/{material_id}/notes` |
| `PUT` | `/api/video-learning/materials/{material_id}/notes/{note_id}` |
| `DELETE` | `/api/video-learning/materials/{material_id}/notes/{note_id}` |
| `GET` | `/api/video-learning/materials/{material_id}/marks` |
| `GET` | `/api/video-learning/materials/{material_id}/marks/{mark_id}` |
| `POST` | `/api/video-learning/materials/{material_id}/marks` |
| `PATCH` | `/api/video-learning/materials/{material_id}/marks/{mark_id}` |
| `DELETE` | `/api/video-learning/materials/{material_id}/marks/{mark_id}` |
| `POST` | `/api/video-learning/materials/{material_id}/mark-suggestions` |
| `GET` | `/api/video-learning/materials/{material_id}/subtitles.vtt` |
| `HEAD` | `/api/video-learning/materials/{material_id}/stream/{format_id}` |
| `GET` | `/api/video-learning/materials/{material_id}/stream/{format_id}` |

#### `voice:router` — `/api/voice` · learning

| 方法 | 路径 |
| --- | --- |
| `POST` | `/api/voice/tts` |
| `POST` | `/api/voice/stt` |

### server

#### `unified_ws:router` — `/` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws` |

#### `personas:router` — `/api` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/personas` |
| `GET` | `/api/personas/{name}` |
| `POST` | `/api/personas` |
| `PUT` | `/api/personas/{name}` |
| `DELETE` | `/api/personas/{name}` |

#### `agent_config:router` — `/api/agent-config` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/agent-config/agents` |
| `GET` | `/api/agent-config/agents/{agent_type}` |

#### `auth:router` — `/api/auth` · public

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/auth/openai-codex/callback` |
| `GET` | `/api/auth/status` |
| `POST` | `/api/auth/login` |
| `POST` | `/api/auth/device-login` |
| `POST` | `/api/auth/session-handoff` |
| `POST` | `/api/auth/session-handoff/exchange` |
| `POST` | `/api/auth/session-handoff/complete` |
| `POST` | `/api/auth/device/heartbeat` |
| `POST` | `/api/auth/logout` |
| `POST` | `/api/auth/register` |
| `GET` | `/api/auth/is_first_user` |
| `GET` | `/api/auth/profile` |
| `PUT` | `/api/auth/profile` |
| `PUT` | `/api/auth/profile/avatar` |
| `DELETE` | `/api/auth/profile/avatar` |
| `GET` | `/api/auth/avatar/{user_id}` |
| `PUT` | `/api/auth/profile/password` |
| `GET` | `/api/auth/devices` |
| `POST` | `/api/auth/devices` |
| `DELETE` | `/api/auth/devices/{device_credential_id}` |
| `GET` | `/api/auth/users` |
| `GET` | `/api/auth/profile/learner-profile` |
| `PUT` | `/api/auth/profile/learner-profile` |
| `GET` | `/api/auth/users/{username}/learner-profile` |
| `PUT` | `/api/auth/users/{username}/learner-profile` |
| `POST` | `/api/auth/users` |
| `POST` | `/api/auth/users/import` |
| `DELETE` | `/api/auth/users/{username}` |
| `POST` | `/api/auth/users/batch-delete` |
| `PUT` | `/api/auth/users/{username}/role` |
| `PUT` | `/api/auth/users/{username}/password` |

#### `capabilities:router` — `/api/capabilities` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/capabilities/registered` |

#### `capabilities_settings:router` — `/api/capabilities` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/capabilities/settings` |
| `PUT` | `/api/capabilities/settings` |

#### `creations:router` — `/api/creations` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/creations/drafts/{draft_id}` |
| `POST` | `/api/creations/drafts/{draft_id}/approve` |

#### `dashboard:router` — `/api/dashboard` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/dashboard/recent` |
| `GET` | `/api/dashboard/suggestions` |
| `POST` | `/api/dashboard/suggestions/refresh` |
| `GET` | `/api/dashboard/learning-index` |
| `GET` | `/api/dashboard/source-library/{kind}` |
| `GET` | `/api/dashboard/learning-library/{kind}` |
| `GET` | `/api/dashboard/{entry_id}` |

#### `file_preview:router` — `/api/file-preview` · authenticated

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/file-preview/pdf` |
| `POST` | `/api/file-preview/pdf` |

#### `imports:router` — `/api/imports` · learning

| 方法 | 路径 |
| --- | --- |
| `POST` | `/api/imports/chat-history` |
| `GET` | `/api/imports/chat-history` |

#### `learning_journal:router` — `/api/learning-journal` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/learning-journal` |

#### `modules:router` — `/api/modules` · authenticated

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/modules` |

#### `multi_user:router` — `/api/multi-user` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/multi-user/admin/resources` |
| `GET` | `/api/multi-user/admin/books` |
| `GET` | `/api/multi-user/guardians` |
| `POST` | `/api/multi-user/guardians` |
| `DELETE` | `/api/multi-user/guardians/{relationship_id}` |
| `GET` | `/api/multi-user/me/guardianships` |
| `DELETE` | `/api/multi-user/me/guardianships/{relationship_id}` |
| `GET` | `/api/multi-user/learners/{learner_user_id}/guardian-report` |
| `GET` | `/api/multi-user/learners/{learner_user_id}/materials` |
| `PUT` | `/api/multi-user/learners/{learner_user_id}/materials` |
| `GET` | `/api/multi-user/learners/{learner_user_id}/restrictions` |
| `PUT` | `/api/multi-user/learners/{learner_user_id}/restrictions` |
| `POST` | `/api/multi-user/learners/{learner_user_id}/credentials/reset` |
| `GET` | `/api/multi-user/users/{user_id}/grants` |
| `PUT` | `/api/multi-user/users/{user_id}/grants` |
| `GET` | `/api/multi-user/users/{user_id}/book-permission` |
| `PUT` | `/api/multi-user/users/{user_id}/book-permission` |
| `POST` | `/api/multi-user/admin/skills/install` |
| `GET` | `/api/multi-user/users` |

#### `plugins:router` — `/api/plugins` · public

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/plugins/extensions` |
| `GET` | `/api/plugins/{plugin_id}/pages/{extension_id}` |
| `GET` | `/api/plugins/{plugin_id}/pages/{extension_id}/` |
| `GET` | `/api/plugins/{plugin_id}/pages/{extension_id}/assets/{asset_path:path}` |
| `GET` | `/api/plugins/catalog` |
| `GET` | `/api/plugins/state` |
| `GET` | `/api/plugins/{plugin_id}/info` |
| `POST` | `/api/plugins/{plugin_id}/approve` |
| `POST` | `/api/plugins/{plugin_id}/enable` |
| `POST` | `/api/plugins/{plugin_id}/disable` |
| `POST` | `/api/plugins/{plugin_id}/install` |
| `POST` | `/api/plugins/{plugin_id}/rollback` |
| `DELETE` | `/api/plugins/{plugin_id}/installation` |
| `GET` | `/api/plugins/{plugin_id}/{plugin_path:path}` |
| `POST` | `/api/plugins/{plugin_id}/{plugin_path:path}` |
| `PUT` | `/api/plugins/{plugin_id}/{plugin_path:path}` |
| `PATCH` | `/api/plugins/{plugin_id}/{plugin_path:path}` |
| `DELETE` | `/api/plugins/{plugin_id}/{plugin_path:path}` |

#### `sessions:router` — `/api/sessions` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/sessions/capabilities` |
| `POST` | `/api/sessions/submission-replacement` |
| `GET` | `/api/sessions` |
| `GET` | `/api/sessions/search` |
| `GET` | `/api/sessions/recycle-bin` |
| `POST` | `/api/sessions/{session_id}/migrate-watching` |
| `GET` | `/api/sessions/{session_id}` |
| `GET` | `/api/sessions/{session_id}/organization` |
| `GET` | `/api/sessions/{session_id}/threads` |
| `GET` | `/api/sessions/{session_id}/messages/{message_id}/events` |
| `GET` | `/api/sessions/{session_id}/ask-hint` |
| `PATCH` | `/api/sessions/{session_id}` |
| `PATCH` | `/api/sessions/{session_id}/reply-language` |
| `PATCH` | `/api/sessions/{session_id}/organization` |
| `DELETE` | `/api/sessions/{session_id}` |
| `POST` | `/api/sessions/{session_id}/restore` |
| `DELETE` | `/api/sessions/{session_id}/purge` |
| `PUT` | `/api/sessions/{session_id}/branch-selection` |
| `DELETE` | `/api/sessions/{session_id}/messages/{message_id}` |
| `POST` | `/api/sessions/{session_id}/quiz-results` |

#### `settings:public_router` — `/api/settings` · public

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/settings/ui` |

#### `settings:router` — `/api/settings` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/settings` |
| `POST` | `/api/settings/providers/openai-codex/oauth/start` |
| `GET` | `/api/settings/providers/openai-codex/oauth/status` |
| `POST` | `/api/settings/providers/openai-codex/oauth/complete` |
| `POST` | `/api/settings/providers/openai-codex/oauth/cancel` |
| `POST` | `/api/settings/providers/openai-codex/oauth/logout` |
| `POST` | `/api/settings/providers/openai-codex/models/refresh` |
| `GET` | `/api/settings/providers/codebuddy/auth/status` |
| `POST` | `/api/settings/providers/codebuddy/auth/start` |
| `POST` | `/api/settings/providers/codebuddy/auth/cancel` |
| `POST` | `/api/settings/providers/codebuddy/auth/logout` |
| `POST` | `/api/settings/providers/openai-codex/models/reasoning-effort` |
| `GET` | `/api/settings/catalog` |
| `GET` | `/api/settings/network` |
| `PUT` | `/api/settings/network` |
| `GET` | `/api/settings/web-fetch` |
| `PUT` | `/api/settings/web-fetch` |
| `GET` | `/api/settings/chat-attachments` |
| `GET` | `/api/settings/chat-starters` |
| `PUT` | `/api/settings/chat-starters` |
| `PUT` | `/api/settings/chat-attachments` |
| `GET` | `/api/settings/mineru` |
| `PUT` | `/api/settings/mineru` |
| `GET` | `/api/settings/document-parsing` |
| `GET` | `/api/settings/readiness` |
| `GET` | `/api/settings/profile` |
| `POST` | `/api/settings/profile/diff` |
| `GET` | `/api/settings/presets` |
| `POST` | `/api/settings/presets/{preset_id}/draft` |
| `PUT` | `/api/settings/document-parsing` |
| `POST` | `/api/settings/document-parsing/test` |
| `POST` | `/api/settings/document-parsing/docling/test` |
| `POST` | `/api/settings/document-parsing/tika/test` |
| `POST` | `/api/settings/document-parsing/install` |
| `POST` | `/api/settings/document-parsing/models/download` |
| `GET` | `/api/settings/document-parsing/job/status` |
| `POST` | `/api/settings/document-parsing/job/cancel` |
| `POST` | `/api/settings/mineru/models/download` |
| `GET` | `/api/settings/mineru/models/download/status` |
| `POST` | `/api/settings/mineru/models/download/cancel` |
| `POST` | `/api/settings/mineru/test` |
| `GET` | `/api/settings/llm-options` |
| `PUT` | `/api/settings/catalog` |
| `POST` | `/api/settings/apply/registry` |
| `POST` | `/api/settings/apply/provider` |
| `POST` | `/api/settings/apply/service` |
| `GET` | `/api/settings/draft` |
| `PUT` | `/api/settings/draft` |
| `DELETE` | `/api/settings/draft` |
| `POST` | `/api/settings/apply` |
| `POST` | `/api/settings/test-provider` |
| `POST` | `/api/settings/fetch-models` |
| `POST` | `/api/settings/model-capabilities` |
| `PUT` | `/api/settings/theme` |
| `PUT` | `/api/settings/language` |
| `PUT` | `/api/settings/voice-autoplay` |
| `PUT` | `/api/settings/voice-math-speak` |
| `PUT` | `/api/settings/chat-response-timeout` |
| `GET` | `/api/settings/page-customization` |
| `PUT` | `/api/settings/page-customization/chat` |
| `PUT` | `/api/settings/page-customization/learning` |
| `GET` | `/api/settings/display` |
| `PUT` | `/api/settings/ui` |
| `POST` | `/api/settings/reset` |
| `GET` | `/api/settings/themes` |
| `GET` | `/api/settings/sidebar` |
| `PUT` | `/api/settings/sidebar/description` |
| `PUT` | `/api/settings/sidebar/nav-order` |
| `PUT` | `/api/settings/enabled-tools` |
| `POST` | `/api/settings/voice/voices` |
| `POST` | `/api/settings/voice/preview` |
| `POST` | `/api/settings/services/{service}/preview` |
| `POST` | `/api/settings/tests/{service}/start` |
| `GET` | `/api/settings/tests/{service}/{run_id}/events` |
| `POST` | `/api/settings/tests/{service}/{run_id}/cancel` |
| `GET` | `/api/settings/tour/status` |
| `POST` | `/api/settings/tour/complete` |
| `POST` | `/api/settings/tour/reopen` |
| `GET` | `/api/settings/usage` |

#### `mcp_settings:router` — `/api/settings/mcp` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/settings/mcp` |
| `PUT` | `/api/settings/mcp` |
| `PUT` | `/api/settings/mcp/servers/{name}` |
| `DELETE` | `/api/settings/mcp/servers/{name}` |
| `POST` | `/api/settings/mcp/test` |

#### `workspace:settings_router` — `/api/settings/workspace` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/settings/workspace/folders` |
| `POST` | `/api/settings/workspace/knowledge-bases/preview-move` |
| `POST` | `/api/settings/workspace/knowledge-bases/move` |
| `GET` | `/api/settings/workspace/data/discover` |
| `POST` | `/api/settings/workspace/data/preview` |
| `POST` | `/api/settings/workspace/data/migrate` |
| `POST` | `/api/settings/workspace/data/export` |
| `GET` | `/api/settings/workspace/data/operations` |
| `POST` | `/api/settings/workspace/data/operations/{operation_id}/recover` |
| `GET` | `/api/settings/workspace/data/exports/{operation_id}` |
| `GET` | `/api/settings/workspace/registrations` |
| `POST` | `/api/settings/workspace/registrations/migrate-root` |
| `POST` | `/api/settings/workspace/registrations/{workspace_id}/migrate` |
| `POST` | `/api/settings/workspace/registrations/system-snapshot` |
| `GET` | `/api/settings/workspace/registrations/system-snapshot` |
| `GET` | `/api/settings/workspace/resource-usage` |
| `GET` | `/api/settings/workspace/resources` |
| `POST` | `/api/settings/workspace/registrations` |
| `PATCH` | `/api/settings/workspace/registrations/{workspace_id}` |
| `GET` | `/api/settings/workspace` |
| `POST` | `/api/settings/workspace/validate` |
| `PUT` | `/api/settings/workspace` |

#### `skills:router` — `/api/skills` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/skills/tags/list` |
| `POST` | `/api/skills/tags/create` |
| `PUT` | `/api/skills/tags/{tag}` |
| `DELETE` | `/api/skills/tags/{tag}` |
| `GET` | `/api/skills/list` |
| `GET` | `/api/skills/hub/catalog` |
| `GET` | `/api/skills/hub/detail` |
| `GET` | `/api/skills/{name}` |
| `POST` | `/api/skills/create` |
| `POST` | `/api/skills/install` |
| `PUT` | `/api/skills/{name}` |
| `DELETE` | `/api/skills/{name}` |

#### `space_cli_apps:router` — `/api/space/cli-apps` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/space/cli-apps/apps` |
| `PUT` | `/api/space/cli-apps/apps/{app_id}/enabled` |
| `GET` | `/api/space/cli-apps/catalog` |
| `POST` | `/api/space/cli-apps/catalog/{app_id}/install` |
| `DELETE` | `/api/space/cli-apps/apps/{app_id}` |

#### `space_mcp:router` — `/api/space/mcp` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/space/mcp/servers` |
| `PUT` | `/api/space/mcp/servers/{name}` |
| `DELETE` | `/api/space/mcp/servers/{name}` |
| `POST` | `/api/space/mcp/servers/{name}/authorize` |
| `GET` | `/api/space/mcp/oauth/callback` |
| `POST` | `/api/space/mcp/servers/{name}/test` |
| `GET` | `/api/space/mcp/catalog` |
| `POST` | `/api/space/mcp/catalog/{entry_id}/install` |

#### `subagents:router` — `/api/subagents` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/subagents/detect` |
| `GET` | `/api/subagents/backends/options` |
| `POST` | `/api/subagents/backends/{kind}/sync` |
| `GET` | `/api/subagents/connections` |
| `POST` | `/api/subagents/connections` |
| `DELETE` | `/api/subagents/connections/{name}` |
| `POST` | `/api/subagents/connections/{name}/message` |
| `GET` | `/api/subagents/settings` |
| `PUT` | `/api/subagents/settings` |

#### `system:router` — `/api/system` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/system/runtime` |
| `GET` | `/api/system/update` |
| `POST` | `/api/system/update/check` |
| `PUT` | `/api/system/update/settings` |
| `GET` | `/api/system/update/job` |
| `POST` | `/api/system/update` |
| `GET` | `/api/system/status` |
| `GET` | `/api/system/memory` |
| `POST` | `/api/system/test/llm` |
| `POST` | `/api/system/test/embeddings` |
| `POST` | `/api/system/test/search` |

#### `task_board:router` — `/api/task-board` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/task-board` |
| `GET` | `/api/task-board/events` |
| `POST` | `/api/task-board/cards` |
| `PATCH` | `/api/task-board/cards/{card_id}` |
| `PUT` | `/api/task-board/colors` |
| `PUT` | `/api/task-board/sessions/{session_id}` |
| `PATCH` | `/api/task-board/sessions/{session_id}/status` |

#### `tools:router` — `/api/tools` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/tools` |

#### `attachments:router` — `/files/attachments` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/files/attachments/{session_id}/{attachment_id}/{filename:path}` |

#### `file_library:router` — `/files/library` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/files/library/` |
| `POST` | `/files/library/` |
| `GET` | `/files/library/search` |
| `GET` | `/files/library/{file_id}` |
| `GET` | `/files/library/{file_id}/download` |
| `HEAD` | `/files/library/{file_id}/download` |
| `DELETE` | `/files/library/{file_id}` |
| `POST` | `/files/library/{file_id}/restore` |

#### `outputs:router` — `/files/outputs` · public

| 方法 | 路径 |
| --- | --- |
| `HEAD` | `/files/outputs/{output_path:path}` |
| `GET` | `/files/outputs/{output_path:path}` |

#### `quiz_judge:router` — `/ws` · public

| 方法 | 路径 |
| --- | --- |
| `WS` | `/ws/questions/judge` |

### visualize

#### `visualizers:router` — `/api/visualizers` · learning

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/visualizers/list` |
| `POST` | `/api/visualizers/bundled/{visualizer_id}/install` |
| `POST` | `/api/visualizers/{visualizer_id}/enable` |
| `POST` | `/api/visualizers/{visualizer_id}/disable` |
| `DELETE` | `/api/visualizers/{visualizer_id}` |
| `POST` | `/api/visualizers/import` |
| `GET` | `/api/visualizers/{visualizer_id}/assets/{asset_path:path}` |
