# DeepTutor 个人费曼学习、多模型与媒体生成设计

**状态：** 待最终文档批准<br>
**日期：** 2026-08-04<br>
**目标版本：** 在 DeepTutor v1.5.8 基线上设计，具体发布版本由实施计划决定<br>
**代码基线：** `44fa7a1552b88f9d8ce2c22259128a15ae2eb0c8`<br>
**设计范围：** 个人费曼学习、多模型协议切换、异步图像生成与持久化<br>

## 1. 背景与目标

DeepTutor 已有 Mastery Path、知识地图、RAG、聊天工具、定量/定性掌握门禁和间隔复习，但当前定性掌握主要依赖一次模型判断和一个布尔值，缺少可追溯的费曼学习证据链，也没有把概念/设计类知识点完整纳入延迟复教闭环。

本设计把现有 Mastery Path 扩展为适合个人长期使用的费曼学习系统。核心学习动作是：用户先用自己的语言教授，AI 先扮演不懂的新手追问，再扮演评估者；服务端依据完整证据执行掌握门禁，而不是让模型直接写入“已掌握”。

同时，系统应显式支持多模型与多 API 协议，在现有 OpenAI-compatible 基础上稳定支持 OpenAI Responses 和 Anthropic Messages；图像生成应支持 OpenAI Image API、OpenAI Responses 的 `image_generation` 工具和 MCP 图像工具，并采用不会阻塞聊天的持久化异步任务。

## 2. 研究依据

### 2.1 产品参考

本设计参考了私有仓库 `shiliai/training` 的“输入 -> 互动 -> 输出/Teach-Back -> 反馈”闭环、苏格拉底式追问、rubric 和学习缺口沉淀，但不引入该项目中的企业培训、PPT、播客、社区、排名或管理后台。

参考快照：

- `shiliai/training` commit：`9bbd8db26fe2da9dd503800acc908bf49cc66eb6`
- `AI培训系统交互设计.md` SHA-256：`9efee131b798802ddbccb5c393123d6efc89b020177b942882dc13a8cd1c09c7`
- `spec/requirements.md` SHA-256：`aefa635e9bf76b34f2ef6f7d3e6ed5988a4cb089a670e6229e623bb4dfef0ea6`

### 2.2 学习科学依据

设计优先采用检索练习、自我解释、为教授而准备、主动生成和间隔练习，而不依赖“费曼技巧必然产生某个固定提升百分比”之类证据不足的宣传性结论。

- Roediger & Karpicke, Test-Enhanced Learning: <https://doi.org/10.1111/j.1467-9280.2006.01693.x>
- Chi et al., Eliciting Self-Explanations: <https://doi.org/10.1207/s15516709cog1803_3>
- Nestojko et al., Expecting to Teach: <https://doi.org/10.3758/s13421-014-0416-z>
- Chi & Wylie, ICAP Framework: <https://doi.org/10.1080/00461520.2014.965823>
- Cepeda et al., Distributed Practice Meta-analysis: <https://doi.org/10.1037/0033-2909.132.3.354>
- 一项直接研究费曼技巧的有限证据：<https://doi.org/10.32871/rmrj2109.02.06>

### 2.3 API 依据

- OpenAI Image API 可直接选择 `gpt-image-2`；Responses API 通过支持该工具的主模型调用 `image_generation`，两者是不同协议：<https://developers.openai.com/api/docs/guides/image-generation>
- Responses 图像工具返回 `image_generation_call`，支持多轮编辑和远程响应状态：<https://developers.openai.com/api/docs/guides/tools-image-generation>
- Responses background mode 支持异步提交、轮询、取消和可恢复流式读取：<https://developers.openai.com/api/docs/guides/background>
- Anthropic Messages 使用 `POST /v1/messages`，system prompt 是顶层字段，消息内容由 typed content blocks 组成：<https://platform.claude.com/docs/en/api/messages.md>

## 3. 已批准用户故事基线

**baseline_revision：** `feynman-personal-learning-v2`<br>
**权威来源：** 当前任务中的用户需求与逐项确认、DeepTutor commit `44fa7a1552b88f9d8ce2c22259128a15ae2eb0c8`、第 2.1 节列出的 `shiliai/training` 快照<br>
**批准者：** 当前任务用户<br>
**批准证据：** 用户在 2026-08-04 依次确认故事基线、架构 A、布局 A、模型策略 A、图像路由、异步保存以及失败恢复/测试矩阵；新增的多协议、`gpt-image-2`、MCP、长超时和图片保存要求均已纳入后再次确认。随后用户批准“过程证据独立保存、稳定掌握后生成待确认知识卡片、确认后才写入个人 KB”，并确认桌面/移动端沉淀交互<br>
**Gate：** `BASELINE_APPROVED`

### FT-01 可追溯学习路径

**As a** 个人学习者<br>
**I want to** 从自己的资料出发建立并调整学习路径<br>
**So that** 学到的知识有来源、冲突可见，且学习顺序符合我的目标<br>

**Given** 个人学习者导入自己的资料或选择已有知识库<br>
**When** AI 生成知识模块和知识点地图<br>
**Then** 系统优先使用用户资料，必要时补充带来源的 Web 资料；用户可以编辑、排序和确认知识地图；资料冲突必须显示，不能静默覆盖。

### FT-02 混合式 Teach-Back

**As a** 个人学习者<br>
**I want to** 用文本或语音向 AI 新手教授知识并接受递进追问<br>
**So that** 我能暴露并修正自己讲不清楚的部分<br>

**Given** 学习者进入一个知识点<br>
**When** 学习者通过文本或语音用自己的语言教授该知识<br>
**Then** 语音先经本地 ASR 转写并由用户编辑确认；AI 先以新手身份追问，再进入评估；帮助按“问题 -> 提示 -> 资料定位 -> 完整讲解”逐级增加；一旦给出完整讲解，用户必须重新完成复教和后续证据链。

### FT-03 证据化掌握

**As a** 个人学习者<br>
**I want to** 看到掌握判断所依据的回答、评分、来源和缺口<br>
**So that** 我可以理解、质疑并重做评估，而不是接受一个黑盒结论<br>

**Given** 学习者提交了一轮讲解<br>
**When** 系统收集通俗解释、至少两个追问回答和一个新情境迁移回答<br>
**Then** 固定 rubric 对正确性、完整性、因果解释和迁移能力评分；失败项、引用依据和知识缺口可见；用户可以质疑并触发重评，但不能手动把未验证项标记为掌握。

### FT-04 稳定掌握与延迟复教

**As a** 个人学习者<br>
**I want to** 在一段时间后重新讲授并检验知识<br>
**So that** 一次答对不会被误认为长期掌握<br>

**Given** 学习者通过本轮门禁<br>
**When** 服务端验证全部证据<br>
**Then** 只写入“暂时掌握”并安排延迟复教；只有延迟复教再次通过才写入“稳定掌握”；失败证据和缺口提高下一轮优先级；每次学习只安排少量知识点，同时允许通过测试直接跳过已会内容。

### FT-05 多模型与显式协议切换

**As a** 个人学习者<br>
**I want to** 在多个模型和明确的 API 协议之间切换，并固定评估口径<br>
**So that** 我能选择合适的教学模型，同时保留可复现的评估历史<br>

**Given** 用户配置了多个 provider profile 和 model<br>
**When** 用户在聊天或学习会话中切换模型<br>
**Then** 系统按 profile 声明的 `openai_responses`、`openai_chat_completions` 或 `anthropic_messages` 协议发起请求，保留流式、工具调用和 reasoning 语义，并记录实际 provider、profile、protocol、model 和版本；严格协议失败时不静默换协议。

教学模型可按会话或每轮切换。评估模型固定在学习路径上，并在 attempt 开始时保存快照。质疑评估时可以显式选择另一已配置模型进行交叉重评，但新版结果追加保存，不覆盖旧版。

### FT-06 多路图像生成

**As a** 个人学习者<br>
**I want to** 从支持的 OpenAI 或 MCP 图像服务生成学习配图<br>
**So that** 漫长或非流式的生成过程不会中断学习，结果也不会因临时 URL 或重启丢失<br>

**Given** 用户配置了一个或多个图像生成 profile<br>
**When** 用户或教学模型请求生成或编辑图像<br>
**Then** 系统可以通过 OpenAI Image API、OpenAI Responses `image_generation` 工具或 MCP 图像工具执行，并统一保存为可预览、可下载、带完整来源信息的本地 artifact；生成任务不阻塞聊天，页面刷新和服务重启后仍可恢复状态。

### FT-07 经确认的知识沉淀

**As a** 个人学习者<br>
**I want to** 把稳定掌握后形成的精炼知识卡片确认并发布到个人知识库<br>
**So that** 学习成果可以被后续检索复用，同时错误回答和过程噪声不会污染 KB<br>

**Given** 一个知识点已经通过延迟复教并进入稳定掌握<br>
**When** 系统生成带来源、证据和版本信息的知识卡片草稿，用户完成编辑、选择可写本地 KB 并明确点击发布<br>
**Then** 系统只把用户确认的卡片正文和 provenance 写入所选 KB；讲解原文、追问回答、rubric 和 gap 继续独立保存在学习证据中；connected/只读 KB 不可选择；发布失败保留草稿且不回滚掌握状态，幂等重试不得产生重复 KB 文档。

### 3.1 约束

- 面向个人学习，不引入企业租户、管理员、社区、排行榜、PPT、播客或 UGC 市场。
- 文本和经确认的语音转写使用同一评估流程。
- 用户资料优先；Web 资料用于补充，来源和冲突必须可见。
- 掌握评估必须可解释、可追溯、可重评。
- API 密钥和可复用鉴权头只保存在服务端。
- 自定义 ChatGPT/OpenAI-compatible endpoint 使用 `base_url + auth + protocol` 配置，不嵌入浏览器会话 Cookie。
- 本地 ASR 的具体 provider、请求格式和部署协议在后续设计中确认；本设计只冻结转写确认边界。
- 学习过程证据与 KB 文档分层保存；只有用户明确确认的知识卡片可以进入 KB。
- 第一版只向 DeepTutor 可写的本地 indexed KB 发布；connected/外部 KB 没有显式写能力时保持只读。

### 3.2 非目标

- 不新建与 Mastery Path 并行的独立 Feynman Capability。
- 不在第一版实现多人协作、课程运营、认证证书或社交学习。
- 不把生成图片当作掌握证据；它只能作为解释材料或题目素材。
- 不自动跨 provider 降级，不在结果不明时自动重放可能重复计费的生成请求。
- 不自动发布知识卡片，不把原始对话、评分、gap 或未经确认的模型总结批量写入 KB。
- 不在第一版为 Obsidian、linked、IMA 或其他 connected KB 新建同步/写回协议。
- 不在第一版原地编辑已发布知识卡片；更新采用“显式撤回 -> 新稳定证据 -> 新草稿 -> 再确认发布”。

## 4. 现状与差距

### 4.1 可复用能力

- Mastery Path 已有知识模块、知识点类型、知识地图和硬门禁策略。
- `mastery_quiz` / `mastery_grade` 已把待答问题和标准答案保存在服务端。
- scheduler 已为 memory、concept、procedure、design 定义复习间隔。
- Learning Space 已展示路径、知识点状态和到期复习。
- 模型目录和前端 ModelSelector 已支持多个 profile/model。
- `AnthropicProvider` 已使用原生 Anthropic SDK。
- `OpenAICompatProvider` 已包含 Responses 转换与解析逻辑。
- imagegen 已有 OpenAI-compatible Image API 和 Chat Completions adapters。
- MCP 管理器已支持连接、工具发现、调用、超时和进度事件。
- 普通本地 KB 已有 writable 检查、增量文档加入、原始文件删除和重新索引能力。

### 4.2 必须修复的差距

- `MasteryAssessTool` 目前接受模型提供的 `passed: bool`，一次调用即可写入定性掌握。
- `LearningProgress` 只保存单个 explanation 字符串，没有 attempt、证据、rubric、迁移、帮助层级或评估版本历史。
- concept/design 的定性通过没有统一调用 scheduler，存在“代码中定义了间隔但实际没有排队”的缺口。
- 现有 `mastered` 无法区分本轮暂时掌握和延迟复教后的稳定掌握。
- Responses API 的选择依赖 provider 域名、模型名和 reasoning 的启发式判断；自定义 Responses endpoint 无法显式选择严格协议。
- Anthropic Messages 虽已存在，但协议不是 profile 的显式、可测试契约。
- imagegen 默认请求超时只有 120 秒，且工具调用同步等待生成完成。
- imagegen 尚无 Responses adapter；MCP 非文本内容目前被字符串化，图片不能可靠保存为 artifact。
- 现有 artifact 有文件展示能力，但缺少持久化媒体任务、远程状态、内容哈希、原子保存和生命周期元数据。
- 学习结果与 KB 之间没有“草稿 -> 用户确认 -> 幂等发布 -> 索引完成”的沉淀合同；现有 connected KB 也不具备统一写回能力。

## 5. 总体架构

### 5.1 决策

在现有 Mastery Path 内增加 **Feynman Cycle policy/strategy**，复用聊天 agent loop、知识地图、RAG、工具挂载、服务端 gate 和 scheduler。

模型负责：

- 选择适合当前知识点的解释方式。
- 扮演新手提出追问。
- 决定何时给问题、提示、资料定位或完整讲解。
- 根据固定 rubric 生成结构化 assessment、反馈和 gap 候选。
- 在稳定掌握后，根据已验证证据和来源生成知识卡片草稿；模型没有发布权限。

服务端负责：

- 绑定真实 session/turn/message 证据。
- 验证证据种类、数量、顺序和帮助约束。
- 验证引用和 assessment schema。
- 计算状态变化并写入历史。
- 安排所有知识类型的延迟复教。
- 执行幂等、并发、迁移和恢复规则。
- 把学习证据与知识卡片分开持久化，并且只在用户确认后向可写 KB 发布。

模型永远不能直接把知识点写成暂时或稳定掌握。

### 5.2 组件边界

```text
Learning Workspace
  ├─ Knowledge Map (现有 + 可编辑优先级)
  ├─ Chat / Teach-Back (现有聊天 + Feynman stage UI)
  ├─ Evidence Panel (新增)
  ├─ Knowledge Card Review (新增)
  └─ Model Selector (复用并显示协议)
          │
          ▼
Mastery Path Capability / Agent Loop
  ├─ mastery_status / mastery_quiz / mastery_grade (扩展)
  ├─ mastery_cycle_start (新增)
  ├─ mastery_record_evidence (新增)
  └─ mastery_finalize (替代直接 passed 写入)
          │
          ▼
LearningCycleService
  ├─ Evidence validator
  ├─ Rubric gate
  ├─ Knowledge state projector
  ├─ Gap tracker
  └─ SpacedRepetitionScheduler

Knowledge Capture Runtime
  ├─ KnowledgeCardDraftService
  ├─ WritableKbPolicy
  ├─ KnowledgeCardPublisher
  └─ 现有 DocumentAdder / RAGService

Model Runtime
  ├─ openai_chat_completions
  ├─ openai_responses
  └─ anthropic_messages

Media Runtime
  ├─ OpenAI Image API adapter
  ├─ OpenAI Responses image tool adapter
  ├─ MCP structured media adapter
  ├─ ImageGenerationJob worker
  └─ GeneratedArtifact store
```

## 6. 学习循环与状态机

### 6.1 本轮最小证据链

1. 用户提交通俗讲解；语音输入必须先确认转写稿。
2. AI 以新手身份提出至少两个针对性追问。
3. 用户回答追问。
4. AI 给出一个未在原材料中直接复述的新情境迁移题。
5. 用户完成迁移回答。
6. 评估模型按固定 rubric 提交 assessment、引用和 gap。
7. 服务端验证并决定进入“暂时掌握”或“待修订”。
8. 暂时掌握的知识点进入 scheduler。
9. 延迟复教重新建立证据并通过后，进入“稳定掌握”。
10. 稳定掌握提交完成后，系统异步生成一份待确认知识卡片草稿；该动作不改变 mastery/review 投影。

### 6.2 状态

```text
mastery_state:
  new -> in_progress
             \-> needs_revision       (任一门禁失败)
             \-> provisional_mastery  (本轮门禁通过)
                    \-> stable_mastery (延迟复教通过)

review_state:
  unscheduled -> scheduled -> due -> in_progress
                      ^                 |
                      +-----------------+  (通过并安排下一次复习)
```

`mastery_state` 和 `review_state` 是正交投影。本轮通过在一个原子写入中设置 `mastery_state=provisional_mastery`、`review_state=scheduled` 和 `next_review_at`，因此“暂时掌握”不会被排期状态覆盖。到期复教开始时只把 `review_state` 设为 `in_progress`；通过后把 mastery 提升为 `stable_mastery` 并安排下一次维护复习。后续复习失败会保留历史稳定记录，但当前 mastery 投影回到 `needs_revision`，review 重新排期，并提高 gap 优先级。

### 6.3 渐进帮助

帮助层级固定为：

1. `question`：换一种问题引导。
2. `hint`：给局部提示。
3. `source_locator`：指出资料位置或相关来源。
4. `full_explanation`：给出完整解释。

使用 `full_explanation` 后，服务端关闭当前证据链并创建新的 reteach chain。此前讲解、追问和迁移不能用于 finalize；用户必须重新完成完整证据链。

### 6.4 Rubric 与硬门禁

四项均为 `0 | 1 | 2`：

- `correctness`：事实与概念正确性。
- `completeness`：是否覆盖本知识点的核心边界。
- `causal_clarity`：是否能解释“为什么”和机制关系。
- `transfer`：是否能在新情境中正确应用。

本轮通过条件：

- 存在已确认的通俗讲解。
- 至少两个追问及对应回答完整绑定。
- 存在新情境迁移题及回答。
- `correctness == 2`。
- `transfer == 2`。
- `completeness >= 1` 且 `causal_clarity >= 1`。
- 没有 critical error。
- 所有引用能够解析到当前 source snapshot。
- 最近一次 `full_explanation` 之后存在全新的完整证据链。

评估模型只能提交 rubric 和依据；最终 `passed` 由服务端计算。

### 6.5 测试跳过

用户可以在知识地图或当前知识点选择“测试跳过”，直接进入 `test_out` attempt，不先展示教学内容或提示。测试仍要求用户完成自己的通俗解释、至少两个诊断追问和一个新情境迁移，并通过同一 rubric 与服务端硬门禁；通过后进入 `provisional_mastery` 和延迟复教，不能直接写 `stable_mastery`。未通过只生成 gap 和后续学习优先级，不惩罚或隐藏该知识点。

### 6.6 知识卡片沉淀

```text
none -> draft
draft -> publishing | stale_evidence | discarded
publishing -> published | publish_failed | reconcile_required
publish_failed -> publishing                         (显式重试)
reconcile_required -> published | publish_failed     (仅显式核对)
published -> retracting
retracting -> retracted | published                  (撤回成功 | 回滚确认)
retracting -> retract_reconcile_required
retract_reconcile_required -> retracted | published  (仅显式核对)
```

- `stable_mastery` 写入成功的同一事务先创建空草稿和 queued generation attempt，再异步生成正文；provisional pass 不创建。手动创建 API 也只能选择服务端投影中的“当前最新有效 stable assessment”，不接受客户端指定任意历史 assessment。
- 草稿冻结 stable assessment 的 evaluator snapshot 作为生成模型；同一 card/input revision 同时最多一个 active generation attempt。调用前追加 ModelInvocationRecord，重启或超时后不能确认结果的 attempt 进入 `unknown`，绝不自动重提产生重复计费；用户显式重试会创建新 attempt、关联前次 attempt 并复用同一冻结模型。
- 草稿模型只读取该稳定 assessment 绑定的 EvidenceItem、SourceSnapshot 和用户已拥有的 GeneratedArtifact 引用。自动正文不得包含原始对话、rubric 或 gap；这些只作为 provenance 引用。
- 草稿生成失败不回滚稳定掌握。系统保留可手工编辑的空草稿壳和失败原因，用户可以手工编辑或显式重试生成。生成结果只在 expected card revision 未变化时写入；用户已经编辑过时，该 attempt 标为 `superseded_by_edit`，保留输出指纹和调用历史但不得覆盖正文。
- 待发布草稿绑定的 assessment 一旦被后续失败复习/challenge 推翻，或当前 mastery 投影变为 `needs_revision`，草稿原子转为 `stale_evidence`。它只可查看或丢弃，不能继续生成或发布；后续新的 stable assessment 可以创建新草稿。
- 用户可以编辑标题/正文、选择可写本地 KB、添加或移除持久化图片引用，然后保存草稿、丢弃或明确发布。
- 发布与 mastery 状态完全正交；`publish_failed` 不改变 `stable_mastery`。
- 已发布卡片是用户确认过的不可变版本快照，不因普通复习失败而自动修改。第一版如需更新，用户先显式撤回；只有 assessment sequence 严格晚于该撤回卡片的全新 stable assessment 才能创建和发布新卡片，不能复用旧稳定证据。

## 7. 数据模型

采用向现有 `LearningProgress` 增加默认值字段的方式演进，保持 JSON 加载兼容。历史记录追加保存，当前状态作为可重建投影。

### 7.1 FeynmanAttempt

```text
id
knowledge_point_id
cycle_type: initial | delayed_reteach | reevaluation | test_out
status: draft | collecting | ready_to_assess | assessed | closed | invalidated
invalidated_reason
knowledge_point_version
source_snapshot_ids[]
supersedes_attempt_id
session_id
started_turn_id
active_chain_id
max_help_level
evaluator_snapshot
created_at / updated_at / closed_at
```

### 7.2 EvidenceItem

```text
id
attempt_id / chain_id
kind: explanation | probe_question | probe_answer | transfer_question |
      transfer_answer | reteach | source_reference
session_id / turn_id / message_id / event_seq
input_mode: text | voice_transcript
transcript_confirmed
content_snapshot / content_hash
question_evidence_id
source_citations[]
help_level
created_at
```

证据必须引用真实会话记录。模型不能提供 `_mastery_path_id`、`_session_id` 或 `_turn_id`；这些值由 capability loop 注入。若消息系统只能稳定提供 turn/event 引用，第一阶段使用 `(session_id, turn_id, event_seq)`，后续可迁移到 message ID。

### 7.3 RubricAssessment

```text
id / attempt_id / revision / assessment_sequence
rubric: {correctness, completeness, causal_clarity, transfer}
critical_errors[]
strengths[]
gap_ids[]
evidence_ids[]
source_citations[]
evaluator_snapshot
model_invocation_id
supersedes_assessment_id
challenge_id
server_gate_result
created_at
```

#### 7.3.1 ChallengeRecord

```text
id / knowledge_point_id
source_attempt_id / source_assessment_id
mode: reassess_existing | collect_new_evidence
requested_evaluator_snapshot
result_attempt_id / result_assessment_id
status: pending | completed | failed | cancelled
reason / created_at / completed_at
```

`reassess_existing` 冻结并复用原 attempt 的 EvidenceItem，在同一 attempt 上追加新的 RubricAssessment revision；它不能修改或补充证据。`collect_new_evidence` 创建 `cycle_type=reevaluation` 且带 `supersedes_attempt_id` 的新 attempt，用户重新完成完整证据链。challenge 进行中不改变当前投影；完成后，服务端按 knowledge point 分配单调递增的 `assessment_sequence`，并只用最新有效 gate 结果重算投影。旧 attempt、旧 assessment 和原 evaluator snapshot 永远保留。

### 7.4 GapRecord

```text
id / knowledge_point_id
label / description
evidence_ids[]
source_citations[]
status: active | improving | resolved | reopened
priority
first_seen_at / last_seen_at / resolved_at
```

### 7.5 KnowledgeStateProjection

```text
knowledge_point_id
mastery_state: new | in_progress | needs_revision |
               provisional_mastery | stable_mastery
review_state: unscheduled | scheduled | due | in_progress
active_attempt_id
latest_assessment_id
provisional_since
stable_since
next_review_at
updated_at
```

投影可以缓存，但必须能从 attempts、assessments 和 review events 重建。

### 7.6 评估配置快照

```text
profile_id
profile_name
profile_revision
requested_api_protocol
requested_model
resolved_provider
resolved_api_protocol
resolved_model
auto_resolution_reason
base_url_fingerprint
prompt_version
rubric_version
created_at
```

attempt 开始时解析 profile（包括 `auto` 的协议选择）并冻结此配置快照，不发起模型调用。实际评估发生后，RubricAssessment 同时保存该 snapshot 和对应 `model_invocation_id`；provider-reported 模型/版本只存在 ModelInvocationRecord 中，未返回时显式记录 `unknown`，不能用请求值冒充。不保存 API key；`base_url_fingerprint` 用于审计配置变化，不暴露完整私有 URL。

### 7.7 来源与知识地图版本

```text
SourceSnapshot
  id / source_type: user_material | web
  material_id / locator
  title / content_hash
  citation_anchors[]
  captured_at

KnowledgeMapVersion
  id / path_id / version
  nodes[] / edges[] / priorities[]
  source_snapshot_ids[]
  confirmed_at

SourceConflict
  id / path_id / knowledge_point_ids[]
  claim / source_snapshot_ids[] / citation_anchors[]
  version
  status: open | resolved
  accepted_snapshot_id
  resolution_note / resolved_at / resolved_by
```

Web 补充材料进入路径前必须先物化为 `SourceSnapshot`，不能只保存模型返回的 URL。用户编辑、排序或确认地图会创建新的 `KnowledgeMapVersion`；进行中的 attempt 继续绑定开始时的版本。开放冲突会显示在知识地图和 Evidence Panel，并阻止受影响的 correctness 门禁通过。

路径所有者可以在同时看到双方引用的情况下，从该 conflict 已列出的 snapshots 中选择一个作为当前评估依据并填写说明，或先修改/补充资料再重新生成 snapshot。解决动作保留冲突双方和历史状态，写入新的 SourceConflict revision，并创建引用该 resolution 的 KnowledgeMapVersion；不允许删除另一方依据或静默自动解决。受影响且绑定旧地图版本的 active attempt 原子转为 `invalidated`，记录 `invalidated_reason=source_version_changed`，旧证据只读且不能继续 record/finalize/resume；用户确认新版本后创建新 attempt 和证据链。用户可以重新打开已解决冲突，重开后 correctness 门禁立即恢复阻塞。

### 7.8 ModelInvocationRecord

```text
id / session_id / turn_id / message_id / attempt_id
knowledge_card_generation_attempt_id
purpose: chat | teaching | evaluation | knowledge_card_draft
profile_id / profile_revision
requested_provider / requested_protocol / requested_model
resolved_provider / resolved_protocol / resolved_model
provider_reported_model / provider_model_version
auto_resolution_reason
prompt_version / tool_schema_version
status / usage_summary
request_fingerprint / response_fingerprint
started_at / completed_at
```

每次聊天、教学、评估和知识卡片草稿模型调用都在发出请求前创建记录，并在完成或失败后追加实际解析结果。`api_protocol=auto` 必须在调用前记录解析出的协议和选择理由；provider 返回的模型标识或版本与请求值不同时两者都保留。消息 metadata、RubricAssessment 和 KnowledgeCardGenerationAttempt 引用 invocation ID，使教学、评估和卡片草稿历史都可复现审计。记录只保存配置/内容指纹和脱敏 usage，不保存 API key、完整鉴权头或默认保存完整私密 prompt/response。

### 7.9 KnowledgeCardRecord

```text
id / user_id / path_id / knowledge_point_id
stable_attempt_id / stable_assessment_id / stable_assessment_sequence
status: draft | publishing | published | publish_failed |
        reconcile_required | stale_evidence | discarded |
        retracting | retract_reconcile_required | retracted
revision / version / generation_locked_by_user_edit
title / body / content_hash
source_snapshot_ids[] / evidence_ids[] / artifact_ids[]
generation_attempt_ids[] / latest_generation_attempt_id
draft_generation_status: queued | running | ready | failed |
                         unknown | superseded_by_edit
target_kb_name / document_rel_path / document_sha256
publication_key / index_task_id / index_version
error_code / sanitized_error
created_at / updated_at / confirmed_at / published_at / stale_at / retracted_at
```

过程证据仍只存在 Evidence Store；KnowledgeCardRecord 保存引用，不复制原始讲解、回答、rubric 或 gap。写入 KB 的确定性 Markdown 只包含用户确认的标题、正文、来源列表、卡片 ID、revision、stable assessment ID 和可选图片 caption/link；图片二进制继续由 GeneratedArtifact store 管理。

每个 knowledge point 同时最多有一个非历史 card；draft、publishing、publish_failed、reconcile_required、published、retracting 和 retract_reconcile_required 都占用该位置，`stale_evidence`、discarded 和 retracted 不占用。资格规则为：创建时当前 mastery 必须是 `stable_mastery`，card 的 assessment ID/sequence 必须等于当前投影的 latest valid stable assessment，且其 sequence 必须大于该 knowledge point 历史中所有 retracted card 的 stable assessment sequence。草稿可以多次保存并递增 revision；第一版 published card 为不可变快照。该边界避免旧证据或多个版本同时进入当前 RAG 结果。

进入 `publishing` 后当前 card revision 锁定，PATCH 返回冲突。`publish_failed` 可以在正文未变化时复用原 publication key 重试；一旦用户继续编辑并产生新 revision，就创建新的 publication key，旧 publication history 保留但不能重新激活。第一次用户 PATCH 标题或正文时设置 `generation_locked_by_user_edit=true`，此后该 card 不再接受模型生成 retry，避免明确的手工内容被后续模型结果覆盖。

#### 7.9.1 KnowledgeCardGenerationAttempt

```text
id / card_id / input_card_revision / stable_assessment_id
generation_attempt_no / retry_of_generation_attempt_id
frozen_model_snapshot / input_hash
status: queued | running | succeeded | failed | unknown |
        superseded_by_edit
model_invocation_id / output_blob_ref / output_hash
lease_owner / lease_expires_at
error_code / sanitized_error
created_at / started_at / finished_at
```

`frozen_model_snapshot` 复制 stable assessment 的 evaluator snapshot，第一次生成和所有显式 retry 均不静默切换模型。`card_id + input_card_revision` 只有一个未终止 attempt，worker 用持久化 lease 单飞领取；调用 provider 前必须先创建并关联 append-only ModelInvocationRecord。

provider 返回完整结果后先把规范化的知识卡 draft payload 原子持久化为 `output_blob_ref/output_hash`，再尝试更新 card；该 blob 不包含完整 prompt、provider 原始响应或鉴权信息。重启规则是确定的：queued 可以继续执行；running 且存在完整持久化输出时，只在 card revision 仍等于 input revision 且 `generation_locked_by_user_edit=false` 时应用，否则标记 `superseded_by_edit`；running 且无法确认完整输出时标记 `unknown`，不自动重提。`POST retry-generation` 明确创建下一 generation attempt 并关联 `retry_of_generation_attempt_id`；旧 invocation/output 审计永不覆盖。

### 7.10 KnowledgeCardPublication

```text
id / card_id / card_revision / user_id
target_kb_name
publication_key
status: queued | validating | staging | indexing |
        published | failed | reconcile_required
document_rel_path / document_sha256
index_task_id / index_version
attempt_count / retry_of_publication_id
error_code / sanitized_error
created_at / started_at / updated_at / finished_at
```

`publication_key = user_id + card_id + card_revision + target_kb_name`。相同 key 和相同 content hash 复用既有 publication；相同 key 但内容不同返回冲突。publication history 追加保存，KnowledgeCardRecord 只投影当前发布状态。

### 7.11 KnowledgeCardRetraction

```text
id / card_id / card_revision / user_id / target_kb_name
request_id
status: queued | quarantining | reindexing | retracted |
        rolling_back | failed | reconcile_required
original_rel_path / quarantine_rel_path / document_sha256
index_task_id
error_code / sanitized_error
created_at / started_at / updated_at / finished_at
```

撤回记录追加保存且与 card 状态投影分离。`request_id` 幂等；同一 card revision 同时只能有一个 active retraction。原文档进入同 volume 隔离区且新索引确认完成前，系统不宣称 retracted；失败时通过原路径/hash 恢复并确认旧索引，无法确认任一终态则进入 `reconcile_required`。

### 7.12 KbWriteOperation

```text
id / kb_name / user_id
operation_type: upload | delete | reindex | card_publish | card_retract
subject_id / request_id
status: queued | running | succeeded | failed | reconcile_required
lease_owner / lease_expires_at
input_snapshot_hash / index_task_id
error_code / sanitized_error
created_at / started_at / updated_at / finished_at
```

该记录位于 KB metadata store，不放入单个 LearningProgress。`kb_name` 上最多一个 running/reconcile-required operation；过期 lease 只允许新 holder 先接管并核对该 operation，不能直接开始下一项 mutation。既有 upload/delete/reindex endpoint 也必须经此记录，避免知识卡片逻辑与原 KB API 分别持锁。

## 8. 学习工具与 API 契约

### 8.1 Agent tools

- `mastery_status`：继续作为每轮入口，返回 active attempt、当前知识点、下一必需证据和到期 review。
- `mastery_cycle_start(knowledge_point_id, cycle_type)`：幂等创建或恢复 attempt，返回 `attempt_id`、`chain_id` 和 required steps。
- `mastery_record_evidence(attempt_id, kind, structured_payload)`：服务端从注入上下文绑定真实 turn/message，并执行状态顺序验证。
- `mastery_quiz` / `mastery_grade`：继续服务 memory/procedure，并把结果同步写入统一 EvidenceItem。
- `mastery_finalize(attempt_id, rubric, critical_errors, gaps, citations)`：不接受 `passed`；服务端计算 gate，写 assessment、state 和 scheduler。
- `mastery_build`：保留知识地图创建/追加能力，并增加地图版本。

原 `mastery_assess(passed, feedback)` 进入兼容期：旧调用只能生成 legacy assessment，不能直接写 `stable_mastery`；新 prompt 和 tool mount 不再向模型暴露它。

### 8.2 Read APIs

- `GET /api/v1/learning/progress/{path_id}/map`：增加 projection、active attempt 和 evidence summary。
- `GET /api/v1/learning/progress/{path_id}/attempts/{attempt_id}`：返回证据、assessment revisions、gaps 和 audit metadata。
- `GET /api/v1/learning/progress/{path_id}/reviews`：返回统一 review queue。
- `PATCH /api/v1/learning/progress/{path_id}/map`：以 expected version 更新排序、优先级或节点选择并创建新地图版本。
- `POST /api/v1/learning/progress/{path_id}/map/confirm`：确认当前地图版本及其 source snapshots。
- `POST /api/v1/learning/progress/{path_id}/conflicts/{conflict_id}/resolve`：仅路径所有者可选择 accepted snapshot 并填写 resolution note；创建 conflict revision 和新地图版本。
- `POST /api/v1/learning/progress/{path_id}/conflicts/{conflict_id}/reopen`：仅路径所有者可重开冲突并恢复相关 correctness 阻塞。

### 8.3 User actions

- `POST .../attempts/{attempt_id}/challenge`：创建 challenge；请求显式选择 `reassess_existing` 或 `collect_new_evidence`，以及使用原 evaluator 或另一已配置 evaluator。
- `POST .../attempts/{attempt_id}/resume`：恢复草稿/中断 attempt；`invalidated` attempt 返回稳定的 `requires_restart` 和当前地图版本，不能恢复旧证据链。

并发和幂等键按被修改的 aggregate 定义：

- attempt/evidence/assessment：`attempt_id + event_id + expected_attempt_version`。
- map edit/confirm：`path_id + request_id + expected_map_version`。
- conflict resolve/reopen：`conflict_id + request_id + expected_conflict_version + expected_map_version`。
- image job submit：`user_id + idempotency_key`；cancel/retry 再带 `job_id + expected_status_version`。
- knowledge card draft/discard/retract：`card_id + request_id + expected_card_revision`；generation retry 还绑定 `latest_generation_attempt_id`；publish 使用第 7.10 节 publication key。

同一幂等键和同一 payload 返回既有结果；幂等键相同但 payload 不同返回冲突。version 冲突返回当前版本和可恢复错误，前端刷新后由用户重试，不自动覆盖。

### 8.4 WebSocket

聊天继续使用现有 unified WebSocket 和 StreamBus，不增加第二条聊天流。mastery 工具结果通过 tool metadata 通知前端刷新 map/attempt。页面刷新后 read APIs 恢复右侧证据面板。

### 8.5 知识卡片与 KB 发布 API

- `GET /api/v1/learning/progress/{path_id}/knowledge-cards`：返回 pending/published cards、来源摘要和发布状态。
- `POST .../knowledge-points/{kp_id}/knowledge-card`：服务端选择当前 latest valid stable assessment 并幂等创建或恢复草稿；请求不接收任意 assessment ID，自动生成失败时也返回可编辑空草稿。若最近一次撤回后没有 sequence 更大的 stable assessment，则返回 `new_stable_evidence_required`。
- `PATCH .../knowledge-cards/{card_id}`：保存标题、正文和 artifact 引用，使用 expected card revision。
- `POST .../knowledge-cards/{card_id}/retry-generation`：只为仍满足当前稳定资格、latest attempt 已终止且 `generation_locked_by_user_edit=false` 的草稿创建新 generation attempt；复用冻结模型并保留 retry lineage。用户已改标题或正文时返回 `generation_locked_by_user_edit`，手工内容保持不变。
- `POST .../knowledge-cards/{card_id}/discard`：丢弃未发布草稿，不改变学习证据或 mastery。
- `POST .../knowledge-cards/{card_id}/publish`：再次校验 card assessment 正是当前 latest valid stable assessment、当前 mastery 仍为 `stable_mastery`、revision、publication key 和 writable target KB；失配先写 `stale_evidence`，不触碰 KB。通过后创建持久化 publication 并立即返回状态。
- `POST .../knowledge-cards/{card_id}/retry-publish`：复用原 key、document path 和 content hash；不得创建第二份 KB 文档。
- `POST .../knowledge-cards/{card_id}/reconcile-publication`：只查询固定 path/hash、KB metadata 和既有 index task，不重新提交文档；确认失败后才允许 retry。
- `POST .../knowledge-cards/{card_id}/retract`：创建持久化 retraction，在同 volume 隔离原始文档并重建索引；只在新索引确认后标记 retracted。
- `POST .../knowledge-cards/{card_id}/reconcile-retraction`：检查固定 raw/quarantine path、document hash 和既有 index task，只完成“已恢复 published”或“已确认 retracted”之一，不重复删除或重索引。

WritableKbPolicy 复用现有 `_assert_kb_writable_or_409` 语义：目标必须是当前用户可访问、状态 ready、无需 reindex、具有本地 raw document 集的普通 indexed KB。`is_connected_kb=true` 的 Obsidian、linked、subagent、LightRAG server、IMA 等目标一律返回只读，直到对应 capability 将来声明并通过单独的写入合同。

KbWriteCoordinator 为每个本地 KB 提供一个持久化独占 lease，统一串行化知识卡片 publish/retract 与现有 upload/delete/reindex mutation。每个 operation 保存 operation ID、owner 和 lease expiry；崩溃后的新 holder 必须先 reconcile 前一 operation，才能开始新写入。lease 被占用返回可重试 `kb_busy`，绝不并发修改 raw 文件、hash registry 或 index。读取继续使用最近一次已确认索引；底层 provider 不支持原子切换时不声称新索引可见，直到结果明确。

KnowledgeCardPublisher：

1. 获取目标 KB 的 KbWriteCoordinator lease，并重新验证 card revision、当前 latest valid stable assessment、source citations、artifact ownership 和 writable KB。
2. 生成确定性 Markdown，在 `/app/data` 同一 volume 的 staging 目录写入并校验 SHA-256。
3. 以固定相对路径 `learning_cards/{card_id}-v{revision}.md` 放入目标 KB raw 目录，并以显式 `allow_duplicates=true` 调用现有 DocumentAdder/RAGService；卡片即使与其他资料文本相同，也必须保留自己的 provenance 文档路径。
4. 只有 DocumentIndexResult 明确包含该文档且 KB 回到 ready，才写 `published`。
5. 索引失败时保留草稿和 publication 诊断，清理未成功 raw 文件/哈希记录；若 provider 可能部分写入则标记 KB `needs_reindex`，禁止继续发布直到修复。
6. 服务重启后根据 publication key、document hash、KB metadata 和 index task 状态 reconcile；无法确认时写 `reconcile_required`，不自动创建新文件。只有显式 reconcile 证明原提交失败后，用户才可 retry。

KnowledgeCardRetraction：

1. 获取相同 KbWriteCoordinator lease，把原 raw 文档按固定 hash 原子移动到同 volume quarantine；card 进入 `retracting`，保留原 published provenance。
2. 触发不含该文档的完整 reindex。只有 raw 缺失、document hash 不在新索引输入且 index task 成功都可确认时，才提交 `retracted` 并删除 quarantine 副本。
3. 新索引失败时，把 quarantine 文档按原路径/hash 原子恢复并重建旧文档集；两项均确认后 card 回到 `published`，retraction 标为 failed，可显式重试。
4. 若删除或回滚任一侧无法确认，card 进入 `retract_reconcile_required`，既不宣称 published 也不宣称 retracted，并锁定该 card/KB 的后续 mutation。显式 reconcile 只依据固定路径、hash 和既有 task 完成恢复或撤回，不创建第二份文档。

## 9. 多模型与 API 协议

### 9.1 Profile 契约

在现有 model catalog profile 中新增显式 `api_protocol`，不要复用已有 `provider_mode`：

```json
{
  "id": "openai-responses-main",
  "binding": "custom",
  "api_protocol": "openai_responses",
  "strict_protocol": true,
  "base_url": "https://example.invalid/v1",
  "extra_headers": {},
  "models": [{"id": "gpt-main", "model": "gpt-5.6"}]
}
```

实际 profile 继续包含服务端保存的 `api_key`；示例有意省略凭据值。

允许值：

- `auto`：只用于兼容旧 profile，保留现有启发式和有限 fallback。
- `openai_chat_completions`：强制 Chat Completions schema。
- `openai_responses`：强制 Responses schema。
- `anthropic_messages`：强制 Anthropic Messages schema。

新建 profile 必须显式选择协议；旧 profile 迁移为 `auto`。`strict_protocol=true` 时不跨协议 fallback。

### 9.2 统一内部表示

Chat/learning 层只处理 provider-neutral 类型：

- `UnifiedMessage` / typed content blocks
- `UnifiedToolDefinition`
- `UnifiedToolCall` / `UnifiedToolResult`
- `UnifiedReasoning`
- `UnifiedUsage`
- `UnifiedResponseEvent`

每个 adapter 负责 system、messages、tools、tool result、reasoning、usage 和 stream event 的双向转换。不得把一个 provider 的原始响应对象泄漏到学习 gate。

### 9.3 评估模型策略

采用已批准的 A 方案：

- 教学模型选择沿用现有 ModelSelector，可按会话或每轮切换。
- 学习路径保存 `evaluator_profile_id/evaluator_model_id`。
- attempt 开始时保存 evaluator snapshot；中途切换教学模型不改变该 snapshot。
- evaluator 暂时不可用时暂停 finalize，不自动换模型。
- 用户显式迁移 evaluator 时写入 migration event；已有 assessment 不被覆盖。
- challenge 可选择另一模型交叉重评，结果通过 `supersedes_assessment_id` 或 challenge 链关联。

### 9.4 调用审计

- Chat、Teach-Back、评估、challenge 和知识卡片草稿都通过同一 ModelInvocationRecorder 写入第 7.8 节记录。
- UI 的消息详情显示 resolved provider/profile/protocol/model；Evidence Panel 额外显示 evaluator snapshot 和 assessment revision。
- `auto` profile 的实际协议必须可见；strict protocol 失败记录原协议和错误，不生成伪造的 fallback 调用。
- profile 配置修改会递增 `profile_revision`，历史 invocation 继续引用旧 revision 的脱敏快照。

## 10. 图像生成路由

### 10.1 统一接口

```text
ImageGenerationRequest
  -> ImageGenerationJob
  -> ImagegenAdapter
  -> GeneratedArtifact[]
```

`ImagegenAdapter` 的语义是“最终返回可验证的媒体内容和来源元数据”，而不是“必须 streaming”。

```text
ImageGenerationRequest
  operation: generate | edit
  prompt
  profile_id / request_model
  source_artifact_ids[]
  mask_artifact_id
  continuation_job_id
  size / quality / count / provider_options
```

`generate` 不接受 source/mask/continuation。`edit` 至少提供一个当前用户可访问的持久化 source artifact，或提供同一用户、同一 profile 的 `continuation_job_id`；客户端不能直接注入任意 remote response ID。服务端从已保存 job/artifact metadata 解析远端 continuation。mask 可选，但必须是当前用户可访问的持久化 artifact、尺寸与目标图一致且通过第 12 节图片校验。provider 不支持所请求的 edit/mask/continuation 能力时返回稳定的 `unsupported_operation`，不能静默退化为重新生成。

### 10.2 OpenAI Image API adapter

- 生成调用 `POST /images/generations`；编辑调用 Image edit endpoint 或 SDK 等价方法。
- `request_model` 可以直接配置 `gpt-image-2`。
- 适合单次生成或直接编辑。
- 解析 base64 或临时 URL，并在成功前下载到本地。

### 10.3 OpenAI Responses image adapter

- 调用 `POST /responses`，传入支持 `image_generation` 工具的主模型。
- 读取 `image_generation_call.result`、`revised_prompt`、response ID 和 image call ID。
- 保存 `previous_response_id` 或 image call reference，以支持多轮编辑。
- 官方 OpenAI profile 不把 `gpt-image-2` 当作 Responses 主模型；图像模型由工具选择。
- 自定义兼容 endpoint 允许自由配置 `request_model`，但 UI 标记为自定义协议，不冒充官方语义。

### 10.4 MCP media adapter

- 用户选择 MCP server 和 tool。
- 配置 `prompt_arg`，以及可选 `size_arg`、`count_arg` 和 `static_args`。
- edit 只有在工具配置显式声明 source/mask 参数映射时可用；否则 capability preflight 标记为 generate-only。
- MCP manager 增加 structured result 路径，保留 `TextContent`、`ImageContent`、`EmbeddedResource` 和 `ResourceLink`，现有普通文本工具行为保持兼容。
- ImageContent 直接解码；Resource/URL 经安全下载器物化。
- MCP progress notification 可以更新 job card，但不是完成判断的必要条件。

### 10.5 GeneratedArtifact

```text
id / job_id
session_id / turn_id / tool_call_id
provider / profile / protocol / model
original_prompt / revised_prompt
operation / parent_artifact_ids[] / mask_sha256
continuation_job_id
remote_response_id / remote_asset_id
sha256 / mime_type / width / height / size_bytes
original_path / thumbnail_path
created_at
```

密钥、完整鉴权头和 base64 图片不写入元数据 JSON。

Artifact 引用单独记录：

```text
ArtifactReference
  id / artifact_id / user_id
  owner_type: session | message | notebook | learning_material | knowledge_card
  owner_id
  version / created_at / deleted_at
```

保存 KnowledgeCardRecord 的 artifact IDs 时，在同一事务创建/关闭 `owner_type=knowledge_card`、`owner_id=card_id` 的 live ArtifactReference。除 discarded 和已确认 retracted 外，draft、stale_evidence、publishing、publish_failed、reconcile_required、published、retracting 与 retract_reconcile_required 均持续持有引用，GC 不能删除对应图片；discard 或已确认 retract 后关闭 live 引用。历史 card 仍保留 artifact ID/hash 供审计，但媒体在没有其他 live reference 且经过宽限期后才可 GC。

## 11. 异步任务、超时与恢复

### 11.1 非阻塞提交

`imagegen` 工具只负责创建持久化 `ImageGenerationJob`，立即返回 `job_id` 和 pending job card。后台 worker 执行 provider 请求。聊天 turn 可以完成，用户可以继续学习；job card 独立轮询状态。

### 11.2 Job 状态

```text
queued -> running -> polling -> validating -> saving -> succeeded
                  \-> failed
                  \-> cancel_requested -> cancelled
                                        \-> cancelled_unconfirmed
                  \-> timed_out
                  \-> unknown
```

`unknown` 表示 provider 可能已接单或计费，但本地无法确认结果。`cancelled_unconfirmed` 表示本地已停止，但 provider 不支持取消或未确认取消。两者都不会自动重试或恢复普通轮询。

### 11.3 ImageGenerationJob 记录

```text
id / user_id
session_id / turn_id / tool_call_id
status / status_version
provider / profile / protocol / model
request_snapshot / request_hash
idempotency_key
remote_response_id / remote_job_id
artifact_ids[]
retry_of_job_id
connect_timeout_seconds / read_timeout_seconds / deadline_at
poll_after / attempt_count
error_code / sanitized_error
created_at / started_at / updated_at / finished_at
```

第一版沿用 DeepTutor 的本地持久化模式，把 job metadata 放在现有 `/app/data` 用户空间中，并采用原子写入；不引入 Redis、Celery 或外部数据库。后台 worker 启动时按状态恢复：`queued` 可执行；`running/polling` 有 remote ID 时恢复 reconcile/poll、无 remote ID 时按第 11.5 节转为 `unknown`；`cancel_requested` 只恢复远端取消确认，provider 不支持取消或取消无法确认时转为 `cancelled_unconfirmed`，绝不恢复普通生成轮询。其余自动终态不重新执行。同一进程只允许一个执行租约处理一个 job；多副本部署不在本设计范围内。

Job API：

- `POST /api/v1/image-jobs`：幂等提交并返回 job card 数据。
- `GET /api/v1/image-jobs/{job_id}`：读取状态、耗时、脱敏错误和 artifacts。
- `POST /api/v1/image-jobs/{job_id}/cancel`：执行第 11.6 节取消语义。
- `POST /api/v1/image-jobs/{job_id}/retry`：显式创建关联的新 job，不重写旧记录。

### 11.4 分层超时

默认值可按 profile 修改：

- connect timeout：20 秒。
- 单次 blocking/read timeout：30 分钟。
- 整个 job deadline：60 分钟。
- polling interval：2 秒起步，退避到 15 秒。

浏览器请求和聊天 turn 不继承上述长超时。provider 不支持 streaming 时仍正常工作，UI 显示状态和已耗时。

### 11.5 Provider-specific recovery

- Responses 支持时使用 `background: true`，保存 response ID，轮询 retrieve，并在用户取消时调用远端 cancel。
- 仅 `running/polling` job 在已经返回 remote ID 后遇到网络错误时执行 reconcile/poll，不能自动重新提交。
- 没有 remote ID 且不能确定请求是否送达时进入 `unknown`。
- 服务重启后，只有 `running/polling` 且有 remote ID 的 job 恢复普通轮询；无 remote ID 的 `running/polling` job 转为 `unknown`。`cancel_requested` 只进入第 11.6 节取消确认，所有自动终态均不轮询、不重放。
- MCP 或同步 Image API 只有在明确“请求尚未被接受”的连接阶段错误才允许有限自动重试。
- 用户可以从 failed/timed_out/unknown 手动重试或选择其他 profile，新 job 通过 `retry_of_job_id` 关联旧 job。

### 11.6 取消语义

- 用户请求取消先写瞬时状态 `cancel_requested` 并停止普通结果轮询。
- provider 支持远端取消时只执行 cancel/retrieve 以确认取消；确认后写 `cancelled`，取消失败或超过确认期限写 `cancelled_unconfirmed`。
- provider 不支持取消时立即写 `cancelled_unconfirmed`，并明确提示远端任务可能继续。
- `cancelled` 和 `cancelled_unconfirmed` 都是自动终态。取消后的迟到结果不自动暴露为成功，不创建用户可见 artifact；只保留脱敏 remote metadata 供诊断。

## 12. 图片保存与生命周期

### 12.1 成功提交顺序

1. 接收 base64、ImageContent 或安全远程 URL。
2. 写入与最终目录同一持久化 volume 的临时文件。
3. 校验文件 magic、允许 MIME、字节上限、图像尺寸和解码完整性。
4. 计算 SHA-256。
5. 以内容寻址路径原子 rename。
6. 生成缩略图。
7. 写 GeneratedArtifact metadata 和 session/turn 引用。
8. 最后把 job 标记为 `succeeded`。

任何一步失败都不能产生 succeeded job。元数据不保存 base64；远程 URL 必须落地，不能依赖可能过期的 provider URL。

### 12.2 存储策略

- 使用现有 `/app/data` 持久化数据卷下的 user workspace/media 根目录。
- 原图以 SHA-256 内容寻址并去重，缩略图作为派生文件。
- 生成图片默认保留，直到用户明确删除。
- session、message、notebook 或 learning material 对 artifact 建立引用；删除一处引用不删除仍被其他对象引用的原图。
- 无引用对象进入可配置 GC 宽限期，而不是立即物理删除。
- 单文件大小、像素尺寸、用户总配额和并发 job 数可配置；超限任务失败并给出可操作错误。
- 远程 URL 下载必须使用现有 URL 安全策略，阻止私网探测、重定向绕过和非允许协议。

### 12.3 删除、引用与配额恢复

- `GET /api/v1/generated-artifacts`：列出当前用户 artifacts、占用字节、引用数量和 GC 状态，支持从设置中的“生成媒体”视图管理配额。
- `DELETE /api/v1/generated-artifacts/{artifact_id}/references/{reference_id}`：只移除一个上下文引用；使用 `expected_reference_version` 防止并发覆盖。
- `POST /api/v1/generated-artifacts/{artifact_id}/delete`：显式选择 `detach_current` 或 `remove_everywhere`。后者必须在 UI 展示受影响引用数并二次确认，然后软删除当前用户拥有的全部引用。
- `POST /api/v1/generated-artifacts/gc`：用户显式执行当前用户范围内的立即清理，只删除零引用且已进入宽限期的 artifacts，并提前结束这些对象的宽限期；默认定时 GC 仍等待宽限期结束。
- artifact 仍有引用时不进入 GC；最后一个引用删除后进入宽限期。宽限期内恢复引用会取消 GC，期满后才删除原图、缩略图和 metadata。
- 配额计算包含宽限期文件。配额不足错误返回 used/limit/reclaimable bytes，并提供进入“生成媒体”视图的操作；用户必须能够通过删除引用并等待或执行允许的立即清理来恢复可用空间。

## 13. 用户界面

### 13.1 学习会话

采用已批准的三栏工作台：

- 左栏：知识地图、当前目标、少量今日知识点、状态与优先级编辑。
- 知识点提供“测试跳过”动作，进入不展示教学内容的证据测试。
- 中栏：对话和 Teach-Back 主区，顶部显示“讲解 -> 追问 -> 迁移 -> 反馈”；语音转写以可编辑的待确认状态内联展示。
- 右栏：Evidence Panel，显示 rubric、来源、gap、帮助层级、服务端 gate 和“本轮只算暂时掌握”的提示。

移动端使用“知识地图 / 对话 / 证据”三个 tabs，composer 固定在当前视图底部；不把桌面三栏压缩到同一行。

### 13.2 Learning Space

- 显示待延迟复教队列、到期时间和失败 gap 优先级。
- 区分暂时掌握与稳定掌握。
- 所有 memory/concept/procedure/design 类型都从同一 scheduler 读取。
- 提供 evidence history、assessment revisions 和 challenge 入口。
- 汇总待确认/发布失败的知识卡片，但不把处理卡片变成继续学习的前置条件。

### 13.3 模型设置

- profile 编辑器显式显示 API protocol。
- 模型选择器显示 provider、model 和 protocol，长模型 ID 可查看完整值。
- 学习路径设置中单独选择 evaluator profile/model，但日常会话不常驻第二个选择器。
- attempt 右侧证据面板显示 evaluator snapshot。

### 13.4 图像任务卡

- 创建后立即显示 queued/running/polling 等状态和已耗时。
- 支持取消、手动重试、切换 profile 后重试。
- 页面刷新后从持久化 job 记录恢复。
- 完成后在原 session/turn 位置显示图片 preview/download artifact。
- 下一轮 context builder 可以引用已经完成的 artifact。
- provider 是否 streaming 只改变进度细节，不改变 card 生命周期。
- `cancelled_unconfirmed` 明确显示远端任务可能继续，但本地不会恢复等待或自动暴露迟到结果。
- 成功卡片菜单提供下载、从当前对话移除和“从所有位置删除”；全局删除显示引用数量并二次确认。
- 配额错误卡显示占用/上限和“管理生成媒体”动作；设置中的生成媒体视图可按大小、时间和引用数排序，并提供“立即清理可回收文件”。

### 13.5 知识卡片审核与发布

- 稳定掌握后，右侧 Evidence Panel 显示非阻塞的“知识卡片草稿”摘要、Pending 状态、来源/证据/媒体数量，以及“审核”和“丢弃”。学习者可以稍后处理。
- “审核”在桌面展开中栏编辑器，提供标题、正文、引用来源、可选图片引用、可写 KB selector、“保存草稿”和“发布”；不在窄右栏中塞入完整编辑器。
- KB selector 只允许 writable local indexed KB；connected/只读 KB 保留在列表中但禁用并显示锁定状态和原因。没有可写 KB 时只能保存草稿，并链接到现有 KB 创建/修复界面。
- 发布过程显示 queued/indexing/published/publish_failed/reconcile_required。失败状态显示脱敏原因和重试操作，并明确“草稿已保留、不会重复创建文档、稳定掌握不受影响”。
- 后续证据推翻当前稳定状态时，未发布卡片显示 `stale_evidence` 和“需要新的稳定掌握证据”，只提供查看/丢弃；生成、编辑和发布动作禁用。撤回中的卡片显示 retracting；无法判断删除或回滚结果时显示 retract_reconcile_required 和“修复并核对”，不显示错误的 published/retracted 结论。
- 移动端在“证据”tab 显示草稿摘要；审核进入全屏编辑器，而不是压缩桌面三栏。
- 已发布卡片显示目标 KB、document revision 和 provenance；撤回需要明确确认，且在 KB 删除/重索引成功前不提前显示 retracted。

### 13.6 已批准视觉原型

**prototype_revision：** `visual-companion-2026-08-04-r9`<br>
**原型证据：** `feynman-architecture-color-coded.html`、`feynman-mastery-state-flow.html`、`feynman-session-layout-options.html`、`feynman-session-workspace-detail.html`、`feynman-model-routing-options.html`、`image-generation-routing-design.html`、`image-generation-async-storage.html`、`feynman-knowledge-card-kb-promotion.html`（SHA-256 `c8cb3093bbbcb83833c09f277930a978069f3b227333e5ffadc3cab72e325f30`）<br>
**批准证据：** 当前任务用户通过终端回复确认颜色分区版架构、三栏方案 A、工作台细节、模型策略 A、图像路由、异步保存设计，以及知识卡片桌面/移动端审核发布流程<br>

覆盖范围：

- 桌面：三栏工作台、当前阶段、证据面板、来源/gap、模型身份、图片 job card，以及稳定掌握后的知识卡片摘要/展开编辑器。
- 移动端：知识地图/对话/证据 tabs、固定输入区和全屏知识卡片编辑器；不把三栏压缩到一行。
- 状态：讲解、追问、迁移、评估、暂时掌握、待延迟复教、稳定掌握；图片 queued/running/polling/unknown/succeeded/failed/cancelled/cancelled_unconfirmed；知识卡片 draft/stale_evidence/publishing/published/publish_failed/reconcile_required/retracting/retract_reconcile_required/retracted。
- 响应式验收视口：桌面宽度 1440px；移动宽度 390px。实施可以适配更多尺寸，但不能改变已经批准的信息层级和导航模式。

## 14. 来源、冲突与安全

- Evidence citation 必须解析到冻结的 source snapshot；模型提供的任意 URL 字符串不能自动成为有效引用。
- 用户资料和 Web 资料发生关键事实冲突时，同时展示双方依据；冲突未解决前，受影响的 correctness 项不能通过。
- 学习资料、Web 页面和 MCP 文本一律视为不可信数据，不能覆盖 system/tool policy。
- provider/MCP 错误正文在日志和 UI 中脱敏，不显示密钥或鉴权头。
- 媒体下载验证 Content-Type 和文件 magic，设置重定向、大小、时间和地址范围限制。
- 评估审计日志记录 ID、状态和版本，不默认记录完整私密学习内容到运行日志。
- 知识卡片正文仍视为用户编辑的非可信 Markdown：发布前移除危险 HTML/链接协议并防止路径穿越，不能把正文解释为 system/tool 指令。
- 卡片所有 source citations 必须命中 stable assessment 绑定的 SourceSnapshot；artifact 引用必须属于当前用户且已经持久化。
- 发布者必须拥有学习路径/card 并对目标 KB 有写权限。connected KB、非 ready KB 和 `needs_reindex` KB 在服务端再次拒绝，不能只依赖前端禁用。

## 15. 失败恢复

- LLM、RAG 或网络失败：attempt 保持草稿，不改变掌握状态，从下一证据步骤恢复。
- ASR 失败：允许切换文本输入；未经确认的转写不形成 EvidenceItem。
- evaluator 不可用：暂停 finalize；用户显式更换时记录迁移，不静默 fallback。
- schema 或引用错误：服务端拒绝 finalize，允许模型在同一 attempt 修复提交。
- 多窗口并发：expected version 冲突，不允许旧页面覆盖新进度。
- 学习中编辑知识点或资料：attempt 绑定版本；不兼容编辑使受影响 attempt 原子转为 `invalidated`，旧证据只读，确认新版本后必须新建 attempt。
- challenge：旧 assessment 保留；新 assessment 可以维持或推翻当前投影。
- 图片 provider 超时/断线：按第 11 节进入 timed_out/unknown/reconcile，不影响聊天或学习证据。
- 图片保存失败：job 失败且保留诊断 metadata，临时文件由安全清理任务回收。
- 知识卡片草稿生成失败：稳定掌握保持不变，保留带 provenance 的空草稿壳；失败可手工编辑或显式重试，无法确认的 provider 调用进入 `unknown` 且不自动重提。
- 未发布卡片的 stable assessment 被新 review/challenge 推翻：原子标记 `stale_evidence` 并禁止生成/发布；学习者取得更新的 stable assessment 后另建草稿。
- 目标 KB 在发布前被删除、变为只读或需要 reindex：publication 失败并保留草稿，不自动改选其他 KB。
- 知识卡片写文件或索引失败：不写 published；按第 8.5 节清理/标记 KB 并保留同一 publication key，重试不产生重复文档。
- 发布中服务重启：进入 reconcile；只有固定文档 hash 和索引结果均可确认时才恢复 published，否则进入 `reconcile_required` 等待修复/重试。
- 撤回新索引失败但 raw/旧索引回滚均确认：保持 published 和原 KB 引用，记录 failed retraction 后允许重试。
- 撤回或回滚无法确认：进入 `retract_reconcile_required`，锁定该 card/KB mutation；显式 reconciliation 在固定 path/hash/index task 上收敛到已恢复 published 或已确认 retracted，不能提前显示任一结论。
- 同一 KB mutation 并发或进程重启：KbWriteCoordinator 返回 `kb_busy` 或先 reconcile 过期 lease，publish/retract/upload/delete/reindex 不能并发破坏 raw/hash/index 一致性。

## 16. 迁移与回滚

### 16.1 学习数据

- 新 Pydantic 字段全部提供默认值，旧 JSON 可直接加载。
- 首次读取旧 `qualitative_mastery=true` 或达到旧定量门禁的知识点时，生成 `legacy_import` attempt/assessment，投影为 `provisional_mastery` 并加入延迟复教，而不是直接稳定掌握。
- 旧 `quiz_attempts`、`error_records`、`feynman_explanations` 和 review state 保留。
- 第一阶段保留旧字段写兼容或只读投影，以支持应用回滚；完成一个稳定发布周期后再单独决定清理。

### 16.2 模型配置

- 旧 LLM profile 缺少 `api_protocol` 时迁移为 `auto`，保持现有行为。
- 新建或编辑 profile 时要求显式协议。
- 严格协议是新增 opt-in；不改变未编辑的旧配置。

### 16.3 图像配置与文件

- 旧 imagegen profile 映射到 `openai_images` 或 `chat_completions_image` adapter。
- 现有媒体文件继续可访问；只有新生成文件要求 GeneratedArtifact metadata。
- 新 job 和 artifact metadata 位于现有持久化数据卷，容器镜像回滚不会删除文件。

### 16.4 知识卡片与 KB 文档

- 升级时不为历史 stable/mastered 数据批量生成草稿，避免未经用户意图产生大量卡片；用户可在旧稳定知识点手动创建。
- KnowledgeCardRecord/GenerationAttempt/Publication/Retraction 字段提供默认空集合和状态，不改变旧 LearningProgress JSON 的加载。
- 已发布卡片是目标 KB 中的普通 Markdown 文档。应用回滚后文档仍可检索；新版本 metadata 暂时只读，不能重复发布。
- connected KB 配置和内容不迁移、不写入。

## 17. 验证策略

### 17.1 学习 policy 单元与属性测试

- 没有延迟复教通过，任何路径都不能产生 stable mastery。
- provisional pass 同时保留 `mastery_state=provisional_mastery` 和独立的 scheduled review，不被排期状态覆盖。
- 缺少解释、两个追问中的任一个、迁移或有效 rubric 时 finalize 必须失败。
- full explanation 之后旧 chain 永远不能通过。
- challenge API 永远不能直接写 passed。
- 所有 knowledge type 的 provisional pass 都建立 repetition state 和 review task。
- 后续复习失败会重开 gap 并提高优先级。
- `reassess_existing` 只能复用冻结证据并追加 assessment；`collect_new_evidence` 必须创建关联的新 attempt。
- challenge pending 不改变投影，完成后只按服务端 assessment sequence 重算。
- 只有 stable mastery 会幂等创建一份 active knowledge-card draft；provisional/failed/review-only 事件不会创建。
- draft/publish/discard/retract 状态与 mastery/review 投影正交，任何发布错误都不能回滚掌握状态。

### 17.2 Tool/API 集成测试

- session/path/turn 身份只能由服务端注入。
- source/map 不兼容更新会原子 invalidated 受影响 attempt；invalidated attempt 不能 record/finalize/resume。
- event id 幂等、expected version 冲突和重试语义。
- attempt、map、conflict 和 image job 分别使用自己的 aggregate version/idempotency contract。
- citation 必须命中 source snapshot。
- conflict resolve/reopen 保留双方来源、创建新地图版本并正确阻塞或解除 correctness gate。
- mastery tool metadata 能驱动前端刷新 map/attempt。
- legacy JSON 和新增 JSON fixture 双向加载。
- knowledge-card edit 使用 expected revision；相同 publication key/hash 幂等，相同 key/不同内容冲突。
- 服务端拒绝 connected、非 ready、needs-reindex 或无权限 KB，即使客户端伪造目标。

### 17.3 Provider contract 测试

- OpenAI Chat Completions：非流式、流式、工具调用、tool result、usage、错误。
- OpenAI Responses：非流式、流式、reasoning、工具调用、strict protocol、background retrieve/cancel。
- Anthropic Messages：顶层 system、typed blocks、工具调用、tool result、streaming 和 thinking。
- 相同内部消息在三个 adapter 中保持语义一致。
- evaluator snapshot 在教学模型切换后不变。
- 每次 chat/teaching/evaluation 调用都保存 requested/resolved/provider-reported 模型信息；`auto` 保存解析理由。
- knowledge-card draft 调用同样保存模型审计；用户先编辑时，迟到模型结果不能覆盖新 revision。
- knowledge-card generation 首次调用与显式 retry 均复用冻结 evaluator snapshot；同 revision single-flight，重启后 unknown 不自动重提，retry 追加 invocation/attempt lineage。

### 17.4 图像任务与存储测试

- 慢速非 streaming provider 超过旧 120 秒后，聊天仍完成、job 仍运行。
- Responses background submit/poll/cancel/restart resume。
- MCP ImageContent、EmbeddedResource、ResourceLink 正确物化。
- generate/edit 请求验证 source ownership、mask 尺寸和 continuation profile；不支持编辑时不静默生成。
- remote ID 后断线不重复提交；unknown 必须人工重试。
- cancel_requested 重启后只恢复取消确认；unsupported cancel 进入 cancelled_unconfirmed，绝不恢复生成轮询。
- 原子保存中任一步失败不产生 succeeded。
- 损坏图片、MIME 欺骗、超大图片、重定向绕过和私网 URL 被拒绝。
- SHA-256 去重、缩略图、引用删除、GC 宽限和磁盘配额。
- 删除单个引用、全局软删除、宽限期恢复和配额不足后的空间回收路径。
- 服务重启后 job、artifact 和原 session 关联恢复。

### 17.5 知识卡片与 KB 集成测试

- stable mastery 后生成带正确 source/evidence/version 引用的草稿，且不自动调用 KB 写入。
- 模型草稿生成失败时返回空草稿壳，用户仍能手工编辑发布。
- 手动创建只能选择当前 latest valid stable assessment；撤回后复用旧 stable sequence 被拒绝，必须先获得更新的 stable assessment。
- 待发布 assessment 被失败复习/challenge 推翻时卡片进入 stale_evidence，发布和生成 API 均拒绝且不写 KB。
- 确定性 Markdown 不包含原始回答、rubric、gap 或未确认模型文本，只包含确认正文和 provenance。
- 本地 writable KB 发布成功后 document path/hash/index result 与 card 一致。
- connected KB 在 UI 禁用且 API 返回只读错误；无可写 KB 时草稿可长期保存。
- 索引失败、进程重启和重复点击发布不会创建第二个 raw 文件或 KB 文档。
- KnowledgeCard 的 live ArtifactReference 阻止 GC；discard/确认 retract 后释放引用，无其他引用且过宽限期才回收媒体。
- 撤回成功、失败后 raw/旧索引回滚成功、以及 retract_reconcile_required 三条路径均可恢复且不会谎报 published/retracted。
- KbWriteCoordinator 串行化 upload/publish/delete/retract/reindex；busy/restart reconciliation 不产生 raw/hash/index 竞态。
- 发布失败/撤回失败不改变 stable mastery；草稿和错误状态在刷新后恢复。
- GeneratedArtifact 只以已授权引用/caption 进入卡片，图片本身不成为 mastery evidence。

### 17.6 E2E

- 文本 Teach-Back 完整循环。
- 语音转写编辑确认后进入同一循环。
- 帮助升级到完整讲解后强制重新复教。
- 暂时掌握、延迟复教、稳定掌握和复习失败回流。
- 评估质疑和跨模型重评。
- 桌面三栏与移动 tabs。
- 多模型/多协议切换。
- 消息详情和 Evidence Panel 展示实际模型调用审计信息。
- 异步图片任务卡在刷新、取消、完成和失败状态下的行为。
- 图片编辑、引用删除、全局删除确认和配额恢复。
- 稳定掌握 -> 待确认知识卡片 -> 编辑 -> 选择本地 KB -> 发布 -> 后续 RAG 可检索。
- 发布失败保留草稿并幂等重试；桌面中栏编辑器与移动端全屏编辑器状态一致。

### 17.7 真实端点 preflight

在部署前用用户提供的实际配置分别验证：

- 至少一个 OpenAI Responses 文本模型。
- 至少一个 Anthropic Messages 模型。
- 用户的 `gpt-image-2` Image API 或兼容 endpoint。
- Responses image tool（若 endpoint 支持）。
- MCP image tool（若配置）。
- 至少一个 ready、可增量写入的本地 indexed KB；connected KB 必须在 selector 和 API 中表现为只读。

preflight 只使用小请求，明确显示协议、模型、延迟和返回类型，不记录明文 key。

## 18. 验收追踪与设计 Playback

| Story | 主要设计证据 | 发布验收 | 设计覆盖 |
|---|---|---|---|
| FT-01 | source snapshot、地图版本、冲突解决/重开门禁 | 用户资料优先且冲突可见、可显式解决 | Covered |
| FT-02 | evidence chain、ASR confirmed、help level | 文本/语音完成同一 Teach-Back | Covered |
| FT-03 | rubric、critical error、两类 challenge history | 未满足硬门禁不能掌握，重评不覆盖历史 | Covered |
| FT-04 | 正交 mastery/review projection、scheduler、test-out | stable 必须有延迟复教证据 | Covered |
| FT-05 | `api_protocol`、ModelSelector、ModelInvocationRecord、evaluator snapshot | 三协议可切换且教学/评估口径可追踪 | Covered |
| FT-06 | adapters、edit lineage、ImageGenerationJob、GeneratedArtifact/reference store | 慢速非流式生成不阻塞，文件可恢复和清理 | Covered |
| FT-07 | KnowledgeCardRecord、WritableKbPolicy、幂等 publication、r9 原型 | 只有确认卡片进入可写 KB，证据隔离且失败可恢复 | Covered |

**baseline_revision：** `feynman-personal-learning-v2`<br>
**subject：** 本设计文档及 `visual-companion-2026-08-04-r9`<br>
**corrections：** v1 自检/独立审查已解决测试跳过、来源/地图版本、job、正交状态、challenge、冲突、并发键、模型审计、图片编辑、取消和删除合同；v2 新增经确认知识卡片、可写 KB policy、幂等发布，并补齐生成 attempt、媒体引用、当前稳定资格、可恢复撤回与 per-KB 写协调合同<br>
**independent_review：** v1 `Approved`；v2 `Approved`，独立复核 subject SHA-256 `772c5e318392f833c19fa3be652c63da68e5f87d309b2c022d39023293231d3a`，无阻塞项<br>
**drift score：** `0`<br>
**Gate：** `DESIGN_ALIGNED`

## 19. 设计决定记录

- 采用现有 Mastery Path 内扩展，而不是新 Capability。
- 采用三栏学习工作台；移动端使用 tabs。
- 本轮通过只算暂时掌握，延迟复教通过才算稳定掌握。
- rubric 使用四维 0-2 分和服务端硬门禁。
- 教学模型可切换，评估模型按路径固定并按 attempt 快照。
- LLM profile 显式声明 API protocol。
- 图像生成支持 Image API、Responses 和 MCP 三 adapters。
- 图像生成采用持久化异步 job，streaming 非必需。
- 图片完成状态以本地安全、原子保存为准。
- 学习过程证据不自动进入 KB；稳定掌握后生成草稿，只有用户确认的卡片发布到 writable local indexed KB。
- connected KB 第一版只读；知识卡片发布失败与 mastery 解耦，并通过 publication key 防止重复文档。
- 交付计划按学习状态、多模型协议、媒体任务、知识沉淀四个依赖 wave 拆分，但每个 wave 和最终发布继续使用 FT-01 至 FT-07 的端到端 Gate。

## 20. 待后续确认但不阻塞本设计的事项

- 本地 ASR 服务的地址、鉴权、音频格式、分段与置信度协议。
- 用户所称 ChatGPT API 的实际 base URL、鉴权方式和是否严格兼容官方 Responses/Image API。
- 真实 provider 的并发额度、图片大小和最长生成时间，用于调整 profile 默认超时与配额。

这些事项由 adapter/preflight 吸收，不改变已批准的学习状态机、评估门禁、模型快照、异步媒体架构或“确认后才写入 KB”的边界。
