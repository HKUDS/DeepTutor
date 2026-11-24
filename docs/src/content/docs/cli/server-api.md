---
title: Server API
description: The HTTP and WebSocket surface exposed by deeptutor serve -- for custom frontends and integrations.
quadrant: reference
---

`deeptutor serve` exposes a FastAPI backend at `http://localhost:8001/` unless you configured a different backend port. This page gives the high-signal map for custom frontends, mobile apps, and service-to-service integrations.

For the exhaustive, always-current schema, start the server and open:

```text
GET /openapi.json     # Full OpenAPI 3.1 spec
GET /docs             # Interactive Swagger UI
GET /redoc            # Alternative ReDoc UI
```

## Starting the server

```bash
# Backend only. Port comes from data/user/settings/system.json, default 8001.
deeptutor serve

# Custom host/port for this process
deeptutor serve --host 127.0.0.1 --port 18001

# Development: hot reload on Python file changes
deeptutor serve --reload
```

## Authentication

When enabled, protected routes require a Bearer JWT or `dt_token` cookie. Auth routes mix public login/bootstrap and guarded profile/admin endpoints; `GET /api/settings/ui` is public. MarginNote `/sync` and `/heartbeat` use `Authorization: MarginNote <device_id>:<token>`.

```bash
# Login
curl -X POST http://localhost:8001/api/auth/login \
  -c cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"..."}'

# Response contains user metadata; the JWT is set in the dt_token cookie.

# Reuse the cookie
curl -b cookies.txt http://localhost:8001/api/sessions
```

If auth is disabled, auth dependencies are no-ops and local single-user requests do not need a token.

## Turn execution WebSocket

```text
WS /ws
```

This is the unified turn WebSocket used by the Web UI. It supports every capability uniformly and streams the same event family that `deeptutor run --format json` prints.

Start a turn by sending a `type: "start_turn"` or `type: "message"` payload:

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

The example above shows the payload for one turn. Every client frame on `/ws` must also carry `"protocol_version": "2.0"` — `start_turn`, `subscribe_turn`, `cancel_turn`, `ping`, and the rest. A frame that omits it is rejected with a `protocol_error` event (`error_code: "unsupported_protocol_version"`) before the payload is validated against any command model.

`skills` narrows the turn rather than being ignored: the selection is intersected with the workspace allowlist, so a turn that names skills gives `read_skill` only those. Omitting it, or sending an empty list, inherits the workspace's full visible set. A turn selection can never exceed what the workspace permits.

Other client types include `subscribe_turn`, `subscribe_session`, `resume_from`, `unsubscribe`, `cancel_turn`, `submit_user_reply`, `regenerate`, and `ping`; subscriptions replay after `after_seq` and terminal turns end with `done` (`error` first on failure).

Typical received events:

```json
{"type":"stage_start","stage":"responding"}
{"type":"tool_call","content":"rag","metadata":{"args":{"query":"chain rule","kb_name":"math"}}}
{"type":"tool_result","content":"...","metadata":{"tool":"rag"}}
{"type":"content","content":"## Solution\n\nThe derivative..."}
{"type":"stage_end","stage":"responding"}
{"type":"done","session_id":"sess_abc123","turn_id":"turn_xyz789","metadata":{"status":"completed"}}
```

## WebSocket endpoints

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

The legacy `/api/v1/chat`, `/api/v1/ws`, and feature-specific API-prefixed sockets are removed. The list above is the complete canonical WebSocket namespace; `/ws` handles all turn capabilities, replay, cancellation, regeneration, and `ask_user` replies.

## Sessions

```text
GET    /api/sessions                              List sessions
GET    /api/sessions/{session_id}                 Get a session + messages
PATCH  /api/sessions/{session_id}                 Rename (body: {"title":"..."})
DELETE /api/sessions/{session_id}                 Delete
PUT    /api/sessions/{session_id}/branch-selection
DELETE /api/sessions/{session_id}/messages/{message_id}
POST   /api/sessions/{session_id}/quiz-results
```

Additional session-state endpoints:

```text
GET   /api/sessions/{session_id}/ask-hint
PATCH /api/sessions/{session_id}/organization
```

## Knowledge Bases

```text
GET    /api/knowledge-bases                           List KBs
GET    /api/knowledge-bases/{kb_name}                 KB info
DELETE /api/knowledge-bases/{kb_name}                 Delete
POST   /api/knowledge-bases                           Create a KB
POST   /api/knowledge-bases/{kb_name}/upload          Add documents
POST   /api/knowledge-bases/{kb_name}/reindex         Re-embed docs
GET    /api/knowledge-bases/default                   Get default KB
PUT    /api/knowledge-bases/default/{kb_name}         Set default KB
GET    /api/knowledge-bases/supported-file-types      Supported uploads
GET    /api/knowledge-bases/{kb_name}/files           List source files
GET    /api/knowledge-bases/{kb_name}/files/{filename}  Serve a source file (preview / download)
GET    /api/knowledge-bases/{kb_name}/file-preview-text/{filename}  Extracted plain-text preview
GET    /api/knowledge-bases/{kb_name}/progress        Indexing progress
WS     /ws/knowledge-bases/{kb_name}/progress         `task_id` replays terminal; orphan → `knowledge_task_interrupted`
```

Ad-hoc KB search is exposed through the RAG runtime/tool path rather than a dedicated `POST /knowledge/{name}/search` route in the current API. From CLI, use `deeptutor kb search <name> <query>`.

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
GET    /api/memory/runs/{run_id}/events?since=N    Absolute N = last_seen_seq + 1
POST   /api/memory/runs/{run_id}/cancel
POST   /api/memory/runs/{run_id}/undo
GET    /api/memory/trace/{surface}
DELETE /api/memory/trace/{surface}
GET    /api/memory/settings
PUT    /api/memory/settings
```

Layers are `L2` and `L3`; examples: `/api/memory/doc/L3/profile` and `/api/memory/doc/L2/chat`.

## Settings, tools, visualizers, and system

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

Provider profiles are edited through the catalog endpoints; there are not separate `/settings/llm` or `/settings/embedding` routes in the current API. Capabilities run through the unified WebSocket/CLI contracts. Visualizer imports are declarative browser packages, not executable backend plugins.

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

Authenticated users may create Partners. Resource routes enforce **use** or **manage** rights; owners/admins manage, while grants can be conversation-only. Secrets are masked unless manageable callers request `include_secrets=true`.

## Book Engine

```text
GET    /api/books
POST   /api/books
GET    /api/books/block-types                         Available generated content types
GET    /api/books/{book_id}
GET    /api/books/{book_id}/spine
GET    /api/books/{book_id}/pages/{page_id}
DELETE /api/books/{book_id}
POST   /api/books/confirm-proposal
POST   /api/books/confirm-spine
POST   /api/books/compile-page
POST   /api/books/pause                               Persist, cancel work, keep completed pages
POST   /api/books/resume                              Queue unfinished pages only
POST   /api/books/{book_id}/refresh-fingerprints
WS     /ws/books                                      Subscribe with `after_seq`; may acknowledge reset
```

## Immersive Reading

```text
GET    /api/reading/supported-formats          Extensions, size cap, raw-view formats
GET    /api/reading/materials                  List this account's materials
POST   /api/reading/materials                  Upload a document (multipart)
GET    /api/reading/materials/{material_id}    Manifest: unit kind, unit count, outline
DELETE /api/reading/materials/{material_id}    Forget a material
GET    /api/reading/materials/{material_id}/units/{locator}      One unit's text
GET    /api/reading/materials/{material_id}/revisions             Prior immutable URL snapshots
GET    /api/reading/materials/{material_id}/revisions/{revision}/units/{locator}
GET    /api/reading/materials/{material_id}/raw                  Original bytes (PDF)
GET    /api/reading/materials/{material_id}/assets/{asset_name}  Authenticated snapshot image
GET    /api/reading/materials/{material_id}/bookmarks            List bookmarks
POST   /api/reading/materials/{material_id}/bookmarks            Save a bookmark
DELETE /api/reading/materials/{material_id}/bookmarks/{bookmark_id}
GET    /api/reading/materials/{material_id}/annotations          List annotations
PUT    /api/reading/materials/{material_id}/annotations          Create or update one; returns AnnotationInfo
DELETE /api/reading/materials/{material_id}/annotations/{id}     Delete one
GET    /api/reading/materials/{material_id}/export?fmt=auto|pdf|markdown
```

A material is content-addressed: uploading the same bytes twice returns the same `material_id` and keeps the annotations already on it. `export?fmt=pdf` returns the original file with real PDF annotations written in, and is only available for materials that kept their raw bytes.

URL refreshes preserve immutable prior revisions. Snapshot assets are authenticated, MIME-sniffed, and served with `nosniff` rather than exposing a live third-party page inside the reader.

## Immersive Watching

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

These compatibility endpoints retain YouTube playback, transcript cues, and provider-independent progress. Current video sessions use Reading; legacy Watching sessions migrate when reopened. Resolve accepts a YouTube URL and optional language/provider override; VTT returns normalized cues.

## Other routers

Not every surface is expanded above. These exist and follow the same conventions; use `/openapi.json` for their schemas:

```text
/api/skills          Skill library and hub installs
/api/personas        Persona presets
/api/plugins         Managed plugin lifecycle and approvals
/api/learning-journal Workspace missions, handoffs, and confirmed records
/api/documents       Co-Writer documents and edit streams
/api/mastery-paths   Mastery paths, objectives, and progress
/api/subagents       Connected agent configuration
/api/imports         Claude Code / Codex conversation import
/api/space/mcp       Per-account MCP services and the curated catalog
/api/space/cli-apps  CLI app catalog, installs, and grants
/api/voice           Text-to-speech and speech-to-text
/api/dashboard       Recent activity, starter suggestions/refresh, and activity detail
```

## Outputs and attachments

User-generated artifacts are served by an authenticated, request-scoped router:

```text
GET /files/outputs/<path>
```

Requests resolve allowlisted files in the caller's or one visible Partner workspace; invalid/private/traversal paths fail closed. Original chat attachments are served under:

```text
GET /files/attachments/{session_id}/{attachment_id}/{filename}
```

## Generate a typed client

```bash
curl http://localhost:8001/openapi.json > deeptutor.openapi.json

# TypeScript client
npx openapi-typescript deeptutor.openapi.json -o deeptutor.d.ts

# Python client
pip install openapi-python-client
openapi-python-client generate --path deeptutor.openapi.json
```
