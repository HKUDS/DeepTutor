# Fork-local feature contract

This file is owned by this fork. Do not include it in upstream PRs unless the
upstream maintainers explicitly ask for it. Before merging upstream, every
`active` item below must still have its routes, data contract, and regression
tests intact.

## Status ledger

- `active`
  - Learning Accounts on the shared `deeptutor.reading` / `ReaderPane` stack,
    with server-enforced surfaces, assigned materials, upload policy, locked
    persona, and per-account Reading extension allowlists.
  - Schema-driven `deeptutor.reading_extensions`, neutral idempotent learning
    records, and the `deeptutor migrate kids-to-learning` copy migration with
    one-time activation codes. Extensions never inject frontend JavaScript.
  - Kids standalone experience and its child-facing API under `/api/v1/kids`.
  - Parent management API under `/api/v1/kids-admin`.
  - `AUTH_ALLOW_REGISTRATION` and the persisted `auth.allow_registration` setting.
  - Partner Feishu/Lark and WeCom QR-code channel onboarding with short-lived
    credentials, administrator-only routes, masked responses, and explicit apply.
  - Tailscale-to-Quick-Tunnel session handoff (`deeptutor.services.tunnel_handoff`),
    ephemeral QR-code pairing (`/access/device`), and launchd-managed daily tunnel
    rotation (`scripts/rotate_deeptutor_tunnel.sh`).
  - YouTube Immersive Watching through a configured Invidious instance, with
    user-scoped timed-media materials, transcript cues, timestamp context,
    native Range playback, explicit audio-only ASR preprocessing, and private
    subtitle-range key-point marks. Optional yt-dlp and youtube-transcript-api
    adapters remain opt-in.
- `upstream-v1.5.16`
  - MarginNote 4 connected knowledge base type.
  - Device pairing, one-time device tokens, incremental sync, heartbeat, and revoke.
  - Seven read-only MN4 tools for search, object reading, type listing, document
    children, links, tags, and mindmap cards.
  - Exclusion of MarginNote libraries from generic `rag_search` sweeps.
- `parked`
  - Local MN4 write-back experiments and review UI work.
  - Chrome/MarginNote realtime probe and sync-coordinator work.
  - Historical preservation worktrees not merged into this integration branch.
- `retiring-after-migration-observation`
  - Standalone Kids profiles, device tokens, parent PIN entry, duplicated EPUB
    viewer, and Kids progress stores. They remain available during this release
    candidate so rollback is possible; after migration acceptance `/kids`
    becomes read-only for one release, then these paths are removed.
- `forbidden-regression`
  - Removing or weakening Kids child session authentication.
  - Removing parent PIN verification or its rate limiting.
  - Exposing child library, EPUB, progress, quiz, asset, or interactive-book
    routes outside their profile/session contract.
  - Deleting Kids regression tests or reducing guided-learning coverage.
  - Moving Kids reward rules, reward persistence, or reward copy back into the
    core Kids product.
  - Routing MarginNote libraries through generic RAG instead of their own tools.
  - Adding a video downloader, Bilibili scraper, or ASR model as a core runtime
    dependency instead of an explicitly installed and authorized plugin.

## Video learning ingestion contract

This follows the division of labor proposed in upstream issue #997: an ingest
boundary emits a timestamped transcript document, while DeepTutor keeps the
learning, locator, mastery, and note-taking responsibilities.

The current YouTube backend stage is deliberately no-download:

1. Resolve YouTube metadata, captions, muxed MP4 formats, and timestamps through
   the administrator-configured Invidious instance.
2. Prefer the exposed transcript and fall back to the optional
   `youtube-transcript-api` adapter.
3. Proxy playback with HTTP Range requests without persisting the complete
   video; only the server-side short-lived stream descriptor is stored.
4. On an explicit request, fetch only audio, cap it at 32 MB while streaming,
   transcribe it through the configured STT provider, and persist transcript
   state—never audio or video.
5. Store normalized `timed_media` segments with `locator`, `start`, `end`, and
   `text` for Chat, Notes, Quiz, and Mastery grounding.
6. Keep private key-point / question / review marks on the timed-media material.
   Range marks are created from selected subtitles or a current-time bookmark;
   AI suggestions are generated only on demand and are not saved until the
   learner confirms. Marks are never written back to Invidious.

Bilibili remains a follow-up TODO. Its BV/AV, multi-part, subtitle, and
provider-specific player work must land in a separate implementation branch.

Research references recorded in issue #997 are JefferyHcool/BiliNote,
AliceDel66/BiliNote, and Rimagination/bili-note. The issue does not identify a
canonical BiliInsight or BibiGPT repository, so those names are product
research leads rather than dependencies. yt-dlp, bilibili-API-collect,
bilibili-api, and BBDown remain external tooling references only.

Video downloads stay outside this default path. A deployment may add a
downloader only as an explicitly installed CLI app/plugin, subject to
administrator installation, per-user `grant.cli_apps` authorization, sandbox
execution, and artifact collection in the turn workspace. The vendored CLI
snapshot must be refreshed through its upstream process; it must not be hand
edited to inject yt-dlp or BBDown.

## Kids capability promise

The active Kids feature set is a coherent product, not a demo:

- Standalone child entry (`/kids`, `/kids/p/{profileId}`) with device tokens and
  parent unlock/exit verification.
- Parent profile management, book assignment, interactive-book assignment, and
  learning reports.
- Per-profile library isolation, reading progress, quiz scores, and
  interactive-book progress.
- The fork-local `deeptutor.kids_reward_providers` extension point. Core emits
  only neutral learning events; an optional provider owns its reward ledger,
  idempotency, copy, snapshot, and persistence. No default reward package ships
  with the core application. A provider failure must never block reading or
  quiz submission.
- A fork-local switch-time Kids dual-track sync tool. It merges learning facts
  between the legacy checkout and this extension build while preserving and
  restoring legacy star fields. It is not a live shared database; both UIs must
  be stopped while it runs.
- Authorized EPUB delivery and navigation mapped to backend reading sections.
- Visible-page text extraction for narration and guided questions.
- Source-grounded current-page concept learning with progressive reflection
  support for Chinese readers.
- Progressive word hints, word exploration, bilingual pronunciation, and shared
  speech playback state.
- Age-band story comprehension quizzes with deterministic fallback, age-aware
  cache invalidation, and exactly three presented questions.
- Interactive book pages, markdown/callout/media/code blocks, safe asset
  delivery, interactive widgets, and page quizzes.

## Kids Reading roadmap

The fork-local direction is to productize the child-facing experience as
**Kids Reading** while retaining DeepTutor's ordinary-account architecture.
The internal protocol and grant field remain `reading_extensions`; the product
name does not introduce a second child identity system.

### Architectural alignment: #992-#995 Learner Account

An audit of upstream `main` and `dev` confirms that issues #992-#995
("Learner Account") do not invent a new identity or parallel storage system,
but rather formalize DeepTutor's existing multi-user and runtime foundations:

```text
Old Kids Subsystem Approach:
  DeepTutor -> KidsProfile -> Kids Library / Kids Progress / Kids Session

Converged Learner Architecture (#992-#995):
  User (role="user") -> Learner Configuration (LearnerProfile, LearningPolicy, Guardian Auth)
                     -> Existing Shared Runtime (Workspace, Grants v2, ReadingStore, LearningStore, Audit)
```

#### Upstream infrastructure status vs #992-#995 requirements

| Component / Requirement | Upstream `main`/`dev` Status | Implementation & Local Contract |
| ----------------------- | ---------------------------- | ------------------------------- |
| Identity model (`admin/user` only) | Complete | `Role = Literal["admin", "user"]`; no special child role |
| Independent user workspaces | Complete | Filesystem isolation under `data/users/<user_id>/` |
| Tool grant allowlists | Complete | Grants v2 `enabled_tools` filter |
| MCP / CLI / exec restrictions | Complete | Deny-by-default for non-admin (`mcp_tools`, `cli_apps`, `exec_enabled`) |
| Resource & material assignment | Complete | Admin API grants for models, KBs, skills; assigned KBs are read-only (403) |
| Server-side turn enforcement | Complete | `tool_access.py` and `turn_runtime` filter every turn payload |
| Usage & administration audit | Complete | `audit/usage.jsonl` logs actor, target, action, timestamp |
| Isolated Reading Store | Complete | Workspace-scoped `ReadingStore` (`deeptutor/reading/store.py`) |
| Reading Agent safety context | Complete | Server binds `reading_material_id` / viewport; deterministic locator pre-pass |
| Grounding on turn regenerate | Complete | Turn snapshot stores `readingMaterialId` to prevent silent ungrounding |
| Learning & Mastery persistence | Complete | Workspace-scoped SQLite database (`<workspace>/learning/mastery.sqlite3`) |
| `learner preset` | Pending | Preset expansion into grant / policy rules |
| `learning_policy` schema | Pending | Server-enforced account policy structure |
| Guardian -> Learner delegation | Pending | Parent-child authorization abstraction over existing grant APIs |
| Age / grade `LearnerProfile` | Pending | Metadata for age-banded prompt adaptation |
| Capability whitelist | Incomplete | Account-level capability allowlisting |
| Reading Extensions policy | Blocked on #970 | Upstream PR #970 (Safe Reading Extension Protocol) is open/unmerged |

### Delivery phases

1. **Now: keep Kids Reading inside DeepTutor.** Learners remain ordinary
   `role="user"` accounts with a server-enforced learning policy, assigned
   materials, and per-account Reading extension allowlists. The public child
   surface is named Kids Reading, but storage, identity, authorization, and
   progress continue to use the shared DeepTutor contracts.
2. **Short term: isolate Kids Reading Essentials.** Keep the schema-only
   read-aloud, guided-learning, vocabulary, translation, and quiz actions in
   `packages/deeptutor-reading-essentials`, and keep that package independent
   of legacy `/kids` profile routes, Kids admin routes, local migration code,
   reward providers, and private deployment configuration.
3. **After Reading extension protocol stabilization:** publish the essentials
   package separately, likely as `deeptutor-reading-essentials` or
   `kids-reading-essentials`. This split is appropriate only once protocol
   versioning, entry-point compatibility, security boundaries, tests, release
   automation, and a compatibility matrix are documented. Track upstream
   reading-extension protocol PR #970 before finalizing the public contract.
4. **Upstream #992-#995 landing & legacy retirement:** As upstream #992-#995
   merges into `main`/`dev`, replace fork-local `kids-to-learning` migration
   shims, standalone profile/PIN tables, and `/api/v1/kids` routes with official
   `LearnerProfile`, `LearningPolicy`, and `Guardian` delegation APIs.
5. **Later: consider a full Kids Reading application repository only if it
   becomes a standalone product.** A separate app must not fork the account,
   bookshelf, progress, guardian authorization, or reading-security model until
   there is an explicit product decision to operate and support it as a
   separate child-facing deployment.

Do not move the fork-local legacy Kids routes, Kids-to-Learning migration,
parent PIN/device flows, dual-track sync details, local reward providers, or
child data/deployment assumptions into the public essentials package.
## Regression gates

Follow `DEVELOPMENT_WORKFLOW.md` for branching, isolated worktrees, ports,
verification, and local product deployment before merging or releasing.

Run these before releasing or merging upstream changes into this fork:

```bash
.venv/bin/python -m pytest \
  tests/test_local_feature_contract.py \
  tests/multi_user/test_learning_policy.py \
  tests/multi_user/test_kids_to_learning_migration.py \
  tests/reading/test_extensions.py \
  tests/immersive_reading/test_kids_reading_endpoints.py \
  tests/immersive_reading/test_kids_interactive_books.py \
  tests/immersive_reading/test_kids_quiz_cache.py \
  tests/immersive_reading/test_kids_learn.py \
  tests/immersive_reading/test_kids_learn_endpoints.py \
  tests/immersive_reading/test_kids_rewards.py \
  tests/scripts/test_kids_dual_track_sync.py \
  tests/cli/test_plugin_cli.py \
  tests/api/test_partners_router.py \
  tests/services/partners/test_channel_onboarding.py \
  tests/services/partners/test_feishu_domain_initialization.py \
  tests/api/test_marginnote4_router.py \
  tests/capabilities/marginnote4 \
  tests/knowledge/test_marginnote4_kb.py
cd web && npm run test:node
```

For a release candidate, also run `cd web && npm run build`, the Kids Playwright
golden path, and the upstream v1.5.16 gateway test set.

## Upstream contribution workflow

1. Keep the working tree clean before an upstream merge. Commit valuable WIP or
   create a preservation branch first.
2. Add fork-local value to this ledger and bind it to at least one regression
   test before it depends on that value.
3. Split upstream-ready work into independently reviewable units. Open an issue
   for the problem and contract first, then submit backend, frontend, and
   tests/docs PRs separately.
4. Do not send this ledger, private Kids product flows, or unauthorized local
   configuration in upstream PRs.
5. Continue MN4 write-back as a separate Phase 2 chain; do not mix it with a
   release upgrade or read-only bridge fixes.

## MarginNote 4 v1.5.16 usage

The upstream release includes the server bridge and web management UI, not the
MarginNote 4 add-on artifact. To use it:

1. Create a MarginNote 4 knowledge base.
2. Open the library's Devices tab and pair a device.
3. Copy the one-time token immediately.
4. Enter the token in the MarginNote 4 add-on on the paired device.
5. Let the add-on call heartbeat and sync; notes, excerpts, cards, and mindmap
   nodes arrive incrementally into DeepTutor's store.

A real-device check is blocked until an MN4 add-on artifact is available; server
pairing and simulated device sync are covered by tests.

## Tailscale & Quick Tunnel Auth Handoff (方案 1 维护规范)

本功能为个人/私有部署专属，用于在 Tailscale 稳定地址上登录后，通过 Mac 屏幕动态二维码或一键跳转，免密安全切换至每日轮换的 Cloudflare Quick Tunnel (`*.trycloudflare.com`) 地址，并自动下发 30 天 HttpOnly 会话 Cookie。

### 架构与核心组件

1. **守护与轮换（0% 代码侵入）**：
   - `scripts/rotate_deeptutor_tunnel.sh`：每日凌晨 05:05 触发，HTTP/2 协议启动 `cloudflared`，捕获最新公网 URL 写入 `data/system/auth/deeptutor_tunnel.json`。
   - `~/Library/LaunchAgents/com.deeptutor.cloudflared.plist`：常驻隧道守护进程。
   - `~/Library/LaunchAgents/com.deeptutor.rotate-tunnel.plist`：定时轮换任务。
2. **后端状态机与路由（独立模块）**：
   - `deeptutor/services/tunnel_handoff.py`：单文件状态机，管理 120 秒一次性配对码 (`Pairing`)、60 秒一次性凭证 (`Ticket`)、隧道 Host 绑定校验，以及通用的 `SessionHandoff`（安全站内 redirect 与受限附加 Cookie，禁止注入/覆盖 `dt_token`、禁止重复或冲突 Cookie 名称，严格过滤路径注入与反斜杠跳转）。
   - `deeptutor/api/routers/auth.py`：挂载 `/handoff`、`/handoff/pairing`、`/handoff/pairing/{pairing_id}`、`/handoff/consume` 接口；全量密码入口（`/login`、`/register`、`/activate-learning`）严格按私网 Host 白名单（`auth.json` 中的 `private_login_hosts` / `AUTH_PRIVATE_LOGIN_HOSTS`，隐式包含 `localhost`/`127.0.0.1`/`::1`）Fail-Closed 防护；普通账号交接默认清理旧 `dt_video_controller`。
   - `deeptutor/api/routers/video_remote_control.py`：作为本地扩展调用方声明自己的 `dt_video_controller` Cookie 与 `/video-learning` redirect；认证核心不依赖视频学习模块。
3. **前端页面与代理策略（独立路由）**：
   - `web/app/(auth)/access/page.tsx`：Mac 已登录展示页，生成 120 秒动态二维码（`qrcode.react`）及「在此电脑上打开」直连入口。
   - `web/app/(auth)/access/device/page.tsx`：手机扫码落地页，免认证（`isAuthExempt`）获取一次性 Ticket 并自动 POST 提交至消费端。
   - `web/proxy.ts` 与 `web/lib/proxy-policy.ts`：`frontendForwardingHost` 优先转发公网 `Host` 请求头。
4. **反向代理身份守卫**：
   - Uvicorn 各启动点（`run_server.py`、`deeptutor_cli/main.py`、`launcher.py`、Dockerfile）统一设置 `--no-proxy-headers` (`proxy_headers=False`)，确保后端仅信任来自本机 Next.js 代理清洗后的 `x-deeptutor-*` 头部。

### 本地扩展边界

本能力保持“本地薄扩展”，暂不注册为 DeepTutor Tool/Capability 插件。现有插件协议只覆盖 LLM 工具和会话能力，不能声明 FastAPI 认证路由、登录前公共 Next.js 页面、代理豁免规则或跨域 Cookie 策略；强行包装会把认证入口和部署细节混入插件注册表。等官方提供 Web/API/Auth 扩展点后，再把 `SessionHandoff` 与 `/access/device` 迁移到正式插件协议。

### 上游（`origin/main`）更新同步与维护手册

当上游官方仓库更新并需要合并至本地时，按以下标准流程操作：

#### 1. 准备工作
确保当前处于主工作区且工作区干净：
```bash
python3 scripts/check_primary_checkout.py
git status --short --branch
```

#### 2. 同步与 Rebase
```bash
git fetch origin
git rebase origin/main
```

#### 3. 冲突处理指引（如遇极少数核心文件冲突）
* **`web/proxy.ts`**：确认 `backendForwardingHeaders` 使用 `frontendForwardingHost(req.headers.get("host"), req.nextUrl.host)`。
* **`web/lib/proxy-policy.ts`**：确认 `isAuthExempt` 包含 `pathname.startsWith("/access/device")`。
* **`deeptutor/api/routers/auth.py`**：确认引入 `tunnel_handoff` 相关路由处理函数并保留 `/handoff` 路由定义。
* **`deeptutor/api/routers/video_remote_control.py`**：确认视频学习只通过 `SessionHandoff` 声明 redirect 和附加 Cookie，不向通用状态机添加视频字段。
* **`run_server.py` / `launcher.py`**：确认 Uvicorn 启动参数包含 `proxy_headers=False` 或 `--no-proxy-headers`。

#### 4. 本地回归验证门禁
```bash
.venv/bin/python -m pytest \
  tests/api/test_auth_tunnel_handoff.py \
  tests/video_learning/test_renderer_remote.py \
  tests/runtime/test_uvicorn_launch_flags.py \
  tests/test_local_feature_contract.py
cd web && npm run test:node && npm run lint && npm run build
```

#### 5. 重启服务生效
```bash
launchctl kickstart -k gui/$(id -u)/com.deeptutor.web
launchctl kickstart -k gui/$(id -u)/com.deeptutor.api
```
