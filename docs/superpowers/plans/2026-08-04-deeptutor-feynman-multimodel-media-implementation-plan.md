# DeepTutor 费曼学习、多模型、媒体与知识沉淀实施计划

**状态：** `APPROVED`<br>
**日期：** 2026-08-04<br>
**仓库：** `HKUDS/DeepTutor`<br>
**实施基线：** `main@a48f9a3e45863cbe3634de7e488bea946ac4a337`<br>
**上游/当前部署代码基线：** `44fa7a1552b88f9d8ce2c22259128a15ae2eb0c8` (`v1.5.8`)<br>
**批准 subject SHA-256：** `9429ce93158d225a3084f30ae932333120a1482012f80fa5cdf207240c4fc16d`<br>
**批准证据：** 当前任务用户于 2026-08-04 回复“批准”<br>
**环境修订证据：** 用户随后要求使用 `uv` 和单一共享 venv，避免各 worktree 各建环境；npm 依赖由 Coordinator 安装

## 1. 权威输入

- Spec：`docs/superpowers/specs/2026-08-04-deeptutor-feynman-multimodel-media-design.md`
- 批准 Spec SHA-256：`499dff16c81b08e0f93d828b2d82cdce7587f9458c123e5198cf1f308b17d26d`
- 渲染 HTML SHA-256：`7fea4746e54969d989ae902083164dfd17ed7d7738d993d20155354871b3ab2e`
- 用户最终批准证据：当前任务用户于 2026-08-04 回复“确认批准”。
- `baseline_revision`：`feynman-personal-learning-v2`
- required stories：`FT-01` 至 `FT-07`；各故事原文、Given/When/Then、constraints 和 non-goals 只引用 Spec 第 3 节，不在本计划重写。
- 视觉权威：`visual-companion-2026-08-04-r9`；知识卡片原型 SHA-256 `c8cb3093bbbcb83833c09f277930a978069f3b227333e5ffadc3cab72e325f30`；桌面 1440px、移动 390px 及 Spec 第 13 节列出的状态均已批准。
- 研究快照：`shiliai/training@9bbd8db26fe2da9dd503800acc908bf49cc66eb6`，仅作为 Spec 已冻结的研究输入，不在实施阶段重新解释需求。

## 2. 交付目标与边界

交付结果是一个继续使用现有 Mastery Path 的个人学习工作流：学习者通过解释、追问、迁移和延迟复教形成可追溯掌握证据；可以切换显式协议的教学模型并追踪评估模型；图片生成采用可恢复的异步任务；稳定掌握后形成待确认知识卡片，只有用户确认内容进入可写本地 KB。

本计划不实现独立 Feynman Capability、企业培训功能、connected KB 写回、已发布卡片原地编辑、浏览器 Cookie 模拟 ChatGPT 会话或本地 ASR provider 协议。本轮只实现 ASR 转写的“编辑并确认后才成为证据”边界；具体本地 ASR 接入留待后续批准设计。

## 3. 权限与停止条件

### 3.1 当前授权

- 允许在本仓库创建实现 worktree、修改代码/测试/文档、安装锁文件声明的开发依赖、运行测试并提交原子本地 commit。
- 允许在现有主机上构建不可变本地镜像，备份 `deeptutor-data`，替换现有 `deeptutor` 容器，并执行 health/readiness/restart/rollback/restore 验证。
- 允许在用户配置真实 provider 后发起最小文本/图片能力探测；不得输出或写入明文密钥。
- 不授权向 `origin` push、创建 PR、发布 PyPI/GHCR 制品或删除用户数据。

### 3.2 必须停止并请求用户决定

- 实现需要修改 FT-01 至 FT-07、non-goal、r9 信息层级或 approved viewport 行为。
- 需要 connected KB 写回、原地更新已发布卡片或未经确认自动写 KB。
- 真实 provider profile/model/effort 与批准的 Agent/provider assignment 不一致。
- 部署需要更换数据卷、端口、宿主，或备份/恢复验证不能通过。
- 同一 P0 Gate 出现第 3 个失败批次，或同一维护窗口出现第 2 次真实宿主失败。

## 4. 当前环境与 Wave 0 Preflight

### 4.1 已确认事实

| 项目 | 证据 | 状态 |
|---|---|---|
| Git | `main@a48f9a3e`；`origin/main@44fa7a15`；仅 `.superpowers/` 未跟踪 | Passed |
| Docker host | Docker `29.2.1` / API `1.53` / linux-amd64 | Passed |
| 资源 | 24 CPU；62 GiB RAM、46 GiB available；`/home` 678 GiB available | Passed |
| 当前服务 | `deeptutor` healthy；前端 `:3782`、后端 `:8001` 均 HTTP 200 | Passed |
| 持久化 | `deeptutor-data` 挂载到 `/app/data`；当前数据约 272 KiB | Passed with deployment backup requirement |
| 回滚制品 | 当前 image digest `sha256:78059c7fcea9aeea68d7b615f38da1ae53508e8d60f93777c6e2c4fbd3b929da` | Passed |
| Python | 3.13.9，符合项目 `>=3.11,<3.14` | Passed |
| Node | Node 22.23.0 / npm 10.9.8，符合 CI Node 22 | Passed |
| Python dev deps | baseline collection 缺 `fastapi`、`loguru` | Pending `ENV-01` |
| Web dev deps | `web/node_modules` 缺失，Node tests 找不到 TypeScript | Pending `ENV-01` |
| LLM profiles | 1 个旧 profile，缺 `api_protocol` | Migration fixture available; real protocol probe pending |
| Image profiles | 0 | Pending user configuration before `REAL-01` |
| STT profiles | 0 | Deferred by approved scope |
| Local KB | 0 | Pending creation before `REAL-01` |

宿主直接读取 Docker volume 会 Permission denied；部署 owner 必须通过 Docker 只读挂载或容器内路径生成备份，不能依赖当前用户直接遍历 `/home/docker/volumes`。

### 4.2 环境合同

- Python 开发：统一使用 `uv 0.9.13` 创建 `<shared-venv>`，通过 `uv pip install --python <shared-venv>/bin/python -r requirements/dev.txt -r requirements/partners.txt` 安装依赖。不得在各 worktree 创建 `.venv`，也不得做绑定某个 worktree 的 editable install；每个任务从自己的 cwd 调用共享 venv 的 `python -m pytest`，确保导入当前 worktree 代码。
- Web 开发：Node 22；在主仓库 `web/` 执行一次 `npm ci --legacy-peer-deps`。各实现 worktree 复用主仓库的 `web/node_modules`（symlink），但 `.next`、测试输出和源码保持 worktree 本地；不得重复改写 lockfile。
- 真实端点：至少一个 OpenAI Responses 文本 profile、一个 Anthropic Messages profile、一个支持 `gpt-image-2` 的 Image API/compatible profile、一个 writable local indexed KB；Responses image/MCP image 只在配置存在时作为 required capability probe。
- 部署：保留容器名 `deeptutor`、宿主端口 `<host>:3782/8001` 和 volume `deeptutor-data`；新镜像以精确 Git SHA 标记，不部署 mutable `latest`。
- 运行中 mutation：所有 KB upload/delete/reindex/publish/retract 经过 per-KB coordinator；部署期间不执行 KB 写操作。

## 5. 依赖 DAG

```text
ENV-01
  ├─ LRN-01 -> LRN-02 -> LRN-03 ─────────────┐
  ├─ MOD-01 -> MOD-02 -> MOD-03 ────────┐    │
  ├─ MED-01 -> MED-02 -> MED-03 ───┐    │    │
  └─ KB-01 ─────────────────────┐   │    │    │
                                └-> KB-02 -> KB-03 -> KB-04
                                     ^       ^       |
                                     |       |       |
                              LRN-01/MOD-03/MED-01   |
                                                    v
LRN-03 -> UI-01 -------------------------------> UI-02
MED-03 -----------------------------------------> UI-02
KB-04 ------------------------------------------> UI-02
UI-02 -> ASM-01 -> REAL-01 -> DEP-01 -> E2E-01
```

同一 worktree 同时只有一个 writer；独立任务使用独立 worktree。最多 3 个实现 writer 并发，保留 1 个 slot 给 Coordinator/P0 review。依赖按 stable integrated SHA 传递，不按 Agent 返回顺序合并。

## 6. Task 清单

每个 Task 的 acceptance 清单版本为 `v1`。任何新增 acceptance 必须先登记，不得在评审时临时扩展。

### Wave 0：开发环境

#### ENV-01 依赖与基线测试

- Stories：基础设施，不直接关闭 story。
- Scope：单一共享 uv venv、一次性 npm 安装、worktree `node_modules` 复用、测试配置和只读 baseline evidence；不改产品行为。
- Acceptance：共享 venv 位于 Plan 固定路径且 worktree 内没有 `.venv`；Python learning tests、相关 provider/media/KB tests 能完整收集；Web node tests 能启动；记录既有失败，不顺手修复无关问题。
- Focused tests：`<shared-venv>/bin/python -m pytest -q deeptutor/learning/tests`；`npm run test:node`。
- Risk：low；Suggested profile：`codex_terra`。

### Wave 1：并行基础合同

#### LRN-01 学习事件模型、版本与迁移

- Stories：FT-01、FT-02、FT-03、FT-04。
- Scope：`deeptutor/learning/models.py`、`storage.py` 及 migration fixtures；FeynmanAttempt、EvidenceItem、RubricAssessment、Gap/Projection、SourceSnapshot/MapVersion/Conflict、append-only history 与 aggregate version。
- Acceptance：旧 JSON 无损加载为 provisional legacy projection；新模型 round-trip；不兼容 source/map 更新原子 invalidated；history 不覆盖。
- Focused tests：learning model/storage/migration/property tests。
- Risk：contract；Suggested profile：`codex_terra`。

#### MOD-01 Profile 协议字段与设置

- Stories：FT-05。
- Scope：model catalog schema/migration、settings API、Models UI；新增 `api_protocol`、`strict_protocol` 和 capability probe 展示。
- Acceptance：旧 profile 迁移为 `auto`；新编辑必须显式协议；UI 可选择三种协议且 connected secret 不回传浏览器。
- Focused tests：model catalog/provider runtime API tests、Web settings node tests、i18n parity。
- Risk：contract；Suggested profile：`codex_terra`。

#### MED-01 持久化图片任务与 ArtifactReference

- Stories：FT-06、FT-07。
- Scope：ImageGenerationJob、GeneratedArtifact、ArtifactReference、原子文件保存、SHA-256、缩略图、引用/软删除/GC/配额；不实现 provider adapter。
- Acceptance：只有本地原子保存成功才 succeeded；重启恢复；live reference 阻止 GC；所有位置删除有二次确认合同；磁盘配额可恢复。
- Focused tests：job/storage/reference/GC/quota tests。
- Risk：p0（文件生命周期与用户数据）；Suggested writer：`codex_terra`；required P0 gate：`codex_sol`。

#### KB-01 Per-KB 写协调器

- Stories：FT-07。
- Scope：KB metadata operation/lease、现有 upload/delete/reindex mutation 接入、busy/restart reconcile；不实现知识卡片。
- Acceptance：同一 KB 只有一个 mutation；过期 lease 先 reconcile；并发不会破坏 raw/hash/index；connected KB 始终只读。
- Focused tests：knowledge router/document adder concurrency、lease expiry、crash reconcile tests。
- Risk：p0（知识库数据一致性）；Suggested writer：`codex_terra`；required P0 gate：`codex_sol`。

### Wave 2：核心行为与 provider adapters

#### LRN-02 Feynman cycle policy 与状态投影

- Stories：FT-02、FT-03、FT-04。
- Dependencies：LRN-01。
- Scope：evidence chain validator、rubric gate、help-level invalidation、正交 mastery/review projection、所有知识类型 scheduler、test-out。
- Acceptance：服务端而非模型计算 pass；缺任一必需证据或 full explanation 后旧 chain 均失败；stable 必须包含延迟复教通过；失败复习回到 needs_revision。
- Focused tests：policy/grading/scheduler 属性测试。
- Risk：contract；Suggested profile：`codex_terra`。

#### LRN-03 Mastery tools、来源冲突与 API

- Stories：FT-01、FT-02、FT-03、FT-04。
- Dependencies：LRN-02。
- Scope：cycle start/record/finalize、map edit/confirm、challenge/reassess、conflict resolve/reopen、read APIs、WebSocket metadata；旧 `mastery_assess` 只兼容 legacy。
- Acceptance：服务端注入真实 session/turn/message；幂等/version conflict 可恢复；challenge 不直接写 pass；citation 必须命中 snapshot；工具结果驱动 UI refresh。
- Focused tests：mastery tools/API/WebSocket contract tests。
- Risk：contract；Suggested profile：`codex_terra`。

#### MOD-02 三协议统一表示与 adapters

- Stories：FT-05。
- Dependencies：MOD-01。
- Scope：OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 内部消息/工具/thinking/reasoning/streaming adapters；strict protocol 不静默 fallback。
- Acceptance：相同内部消息在三协议语义一致；非流式/流式/tool result/usage/error fixtures 全覆盖；Responses background retrieve/cancel 合同可测试。
- Focused tests：provider contract fixtures，不调用真实 endpoint。
- Risk：contract；Suggested profile：`codex_terra`。

#### MOD-03 ModelInvocation 审计与 evaluator snapshot

- Stories：FT-03、FT-05、FT-07。
- Dependencies：MOD-02、LRN-01。
- Scope：ModelInvocationRecord、teaching/evaluation/card-draft purpose、ModelSelector、评估模型 path 固定/attempt 快照、challenge 显式跨模型重评。
- Acceptance：requested/resolved/provider-reported 模型均可追溯；`auto` 保存理由；教学切换不改变 evaluator snapshot；历史评估和 invocation append-only。
- Focused tests：model selection/audit/evaluator/challenge contract tests。
- Risk：contract；Suggested profile：`codex_terra`。

#### MED-02 Image API、Responses 与 MCP adapters

- Stories：FT-06。
- Dependencies：MED-01、MOD-02。
- Scope：统一 generate/edit；OpenAI Image API、Responses image tool/background、MCP structured ImageContent/ResourceLink；长 connect/read/total timeout、unknown、cancel、retry lineage。
- Acceptance：非 streaming 长任务不阻塞聊天；remote ID 后断线不重复提交；edit 不支持时不静默 generate；URL/MIME/magic/size/SSRF 验证 fail-closed。
- Focused tests：adapter fixtures、timeout/restart/cancel/edit/security tests。
- Risk：p0（远程下载与文件输入）；Suggested writer：`codex_terra`；required P0 gate：`codex_sol`。

### Wave 3：知识沉淀与垂直 UI

#### KB-02 知识卡片领域与生成 attempt

- Stories：FT-07。
- Dependencies：LRN-01、MOD-03、MED-01。
- Scope：KnowledgeCardRecord/GenerationAttempt、stable eligibility、single-flight lease、冻结 evaluator snapshot、用户编辑锁、stale evidence、artifact refs。
- Acceptance：只有 latest valid stable assessment 创建草稿；unknown 不自动重提；显式 retry append-only；手工编辑不被迟到结果覆盖；撤回后旧 stable sequence 不能复用。
- Focused tests：generation lifecycle/eligibility/restart/reference tests。
- Risk：contract；Suggested profile：`codex_terra`。

#### KB-03 幂等发布与 reconcile

- Stories：FT-07。
- Dependencies：KB-01、KB-02。
- Scope：WritableKbPolicy、deterministic Markdown、KnowledgeCardPublication、固定 path/hash、DocumentAdder/RAGService 集成、publish retry/reconcile APIs。
- Acceptance：只有用户确认且当前仍 stable 的卡片进入 writable local KB；connected/needs-reindex 拒绝；失败保留草稿；重复点击/重启不产生第二文档。
- Focused tests：publication API/KB integration/index failure/restart/idempotency tests。
- Risk：p0（用户确认边界与 KB 写入）；Suggested writer：`codex_terra`；required P0 gate：`codex_sol`。

#### KB-04 可恢复撤回

- Stories：FT-07。
- Dependencies：KB-03。
- Scope：KnowledgeCardRetraction、同 volume quarantine、reindex、rollback、reconcile-retraction、artifact ref release。
- Acceptance：只在新索引确认后 retracted；失败且回滚确认时保持 published；不确定时锁定为 retract_reconcile_required；显式 reconcile 不重复删除/索引。
- Focused tests：success、rollback success、reconcile-required、crash recovery、no-duplicate tests。
- Risk：p0（数据删除与恢复）；Suggested writer：`codex_terra`；required P0 gate：`codex_sol`。

#### MED-03 图片任务与媒体管理 UI

- Stories：FT-06。
- Dependencies：MED-02。
- Scope：聊天 job card、刷新恢复、取消/手工 retry、preview/download、引用删除/全局删除、配额管理；遵循 r9 样式和现有 design tokens。
- Acceptance：所有 job/cancel/unknown 状态可见；动态内容不改变稳定布局；桌面/移动无重叠；不显示 provider 密钥或原始错误正文。
- Focused tests：Web node state reducers/components、Playwright desktop/mobile screenshots。
- Risk：standard；Suggested profile：`codex_terra`。

#### UI-01 Feynman 学习工作台

- Stories：FT-01、FT-02、FT-03、FT-04、FT-05。
- Dependencies：LRN-03、MOD-03。
- Scope：桌面三栏、移动 tabs、Evidence Panel、知识地图/source conflict/gap、阶段条、confirmed transcript、模型身份；不包含知识卡编辑器和图片卡细节。
- Acceptance：1440px/390px 与 r9 信息层级一致；不同色块清晰区分；所有批准状态可达；文本不重叠；键盘/触屏主流程可用。
- Focused tests：Web component/node tests、Playwright screenshots 和交互 smoke。
- Risk：standard；Suggested profile：`codex_terra`。

### Wave 4：UI 汇合与 Assembly

#### UI-02 知识卡片审核/发布 UI 与工作台汇合

- Stories：FT-06、FT-07。
- Dependencies：UI-01、MED-03、KB-04。
- Scope：pending summary、桌面中栏编辑器、移动全屏编辑器、KB selector/read-only locks、publish/retry/reconcile/retract 状态；整合图片引用和模型身份。
- Acceptance：与批准知识卡原型一致；connected KB 禁用且解释原因；失败明确保留草稿/掌握；stale 只读；发布必须显式确认。
- Focused tests：Web component/node tests、1440/390 Playwright screenshots、非重叠检查。
- Risk：standard；Suggested profile：`codex_terra`。

#### ASM-01 跨模块收敛

- Stories：FT-01 至 FT-07。
- Dependencies：LRN-03、MOD-03、MED-03、KB-04、UI-02。
- Scope：schema/version convergence、i18n、auth/ownership、API registration、packaging、migration fixtures、integrated smoke；不新增行为。
- Acceptance：contract versions 唯一；legacy 数据可加载；所有新增 router/tool/job worker 可从 packaged app 启动；P0 gate 均通过；全量 lint/build/tests 无新增失败。
- Focused tests：`ruff check/format`、`pytest -q tests deeptutor/learning/tests`、`npm run test:node`、`npm run i18n:check`、`npm run build`。
- Risk：contract；Suggested profile：`codex_terra`。

### Wave 5：真实端点、部署与最终验收

#### REAL-01 真实能力 preflight

- Stories：FT-05、FT-06、FT-07。
- Dependencies：ASM-01；用户完成 provider/KB 配置。
- Scope：小请求验证 Responses text、Anthropic Messages、`gpt-image-2` Image API/compatible endpoint、可选 Responses/MCP image、writable local KB；不记录 key。
- Acceptance：记录 profile/protocol/model/latency/result type；strict protocol 不 fallback；图片保存到临时测试 artifact 后按生命周期清理；connected KB 负向探测只读。
- Risk：contract；Suggested profile：`codex_terra`。

#### DEP-01 不可变部署与恢复演练

- Stories：FT-01 至 FT-07。
- Dependencies：ASM-01、REAL-01。
- Unique owner：本 Task writer；其他 Agent 不操作 `deeptutor` 容器/volume。
- Scope：volume 备份与 hash、精确 SHA 镜像 build、替换容器、health/readiness、restart、rollback 到旧 digest、restore 验证，再部署目标 SHA。
- Acceptance：数据卷路径/文件计数保持；前端/backend 200；restart 后状态恢复；rollback/restore receipt 完整；最终容器运行精确新 digest，非 `latest`。
- Risk：p0（部署与持久数据）；Suggested writer：`codex_terra`；required P0/go-no-go：`codex_sol`。

#### E2E-01 最终用户旅程与关闭

- Stories：FT-01 至 FT-07。
- Dependencies：DEP-01。
- Scope：固定 deployed SHA 的文本 Teach-Back、confirmed transcript boundary、帮助升级、暂时/稳定/失败回流、challenge、多协议、异步图片、知识卡发布/retry/retract、桌面/移动；不修改代码。
- Acceptance：Spec 第 17.6 节每条 E2E 有新鲜证据；user-story playback drift 0；失败按根因聚类并返回原 owner；最终状态明确为 passed/accepted_risk/degraded/blocked。
- Risk：contract；Suggested profile：`codex_sol`（只读 E2E 分析/go-no-go）。

## 7. 验证节奏

- Task：writer 在稳定 head 只跑一次 focused suite，并提交 Receipt、原子 commit、clean worktree 和对当前 story 的 alignment 候选。
- Integration：Coordinator 验证 diff/scope/receipt，只运行本次集成新增的 contract smoke；在 integrated SHA 重放 story，drift 0 后关闭 Task。
- Wave：所有 Task 收敛后运行一次受影响 smoke，完成非阻塞 user-story playback；不重复全量 suite。
- Assembly：稳定 final subject 运行一次 Python full suite、Web node tests、i18n、build 和 required P0 validation。
- Deployment：固定 image digest 收集 backup/health/restart/rollback/restore receipt。
- Final：只在真实 deployed SHA 上运行一次完整 E2E；任何修复先跑受影响 focused tests，再重跑最终 E2E。

## 8. Agent Assignment Gate

默认建议采用：

- implementation/standard/contract writer：`codex_terra`。
- P0 review、E2E failure analysis、final go/no-go：`codex_sol`。
- UI 不再交给设计 Agent；布局权威已经由 r9 原型冻结，writer 只实现并用 Playwright 验证。
- launch mode：优先 Codex native；若 profile/model/effort 不能被真实 tool 参数精确表达则停止，不自动切换 CLI/fallback。

内置 profile catalog 当前把 `codex_terra` 和 `codex_sol` 都映射为 `xhigh` effort。用户早先提到的 `terra/medium` 不在此处静默解释为 `codex_terra/xhigh`；Assignment Gate 必须明确选择 Suggested、Uniform 或 Custom，并确认 launch mode 后才初始化/批准 Ledger assignment。

## 9. Plan 完成定义

只有以下事实全部成立才关闭本 Program：

- 所有 required Task 集成到一个精确 Git SHA，worktree clean；
- FT-01 至 FT-07 在 Task、Wave、部署和最终 E2E playback 中 drift 0；
- Python/Web/contract/security/P0/full E2E 均有新鲜证据；
- 真实 Responses、Anthropic、图片和 writable KB preflight 通过，ASR provider 明确保持后续范围；
- 用户数据备份、部署、restart、rollback、restore 均有可验证 receipt；
- 最终 `deeptutor` 容器运行精确不可变 image digest，前端/backend 健康；
- 没有 unresolved blocker、P0 finding、host STOP 或未声明 degraded state。

**Plan 当前精确下一动作：** Coordinator 初始化 Ledger、创建上述 Task DAG、输出正式 Agent Assignment Gate 表格，再请求选择 Suggested、Uniform 或 Custom 及 launch mode。assignment 获批后只派发 `ENV-01`。
