---
title: 服务端 API
description: deeptutor serve 暴露的 HTTP 和 WebSocket 表面 —— 用于自定义前端和集成。
quadrant: reference
---

`deeptutor serve` 在 `http://localhost:8001/` 上启动 FastAPI 后端（除非你改了后端端口）。本页是给自定义前端、移动 App 和服务间集成准备的高密度地图。

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
GET    /api/partners/channels/schema
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
