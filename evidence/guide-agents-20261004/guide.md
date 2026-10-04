# deeptutor/agents 能力编排代码导读

- 基线：`origin/main` @ `f07029cfc`（v1.6.13），只读 worktree，未改任何产品代码。
- 范围：`deeptutor/agents/**`（base_agent、loop、_shared、chat、question、research、vision_solver、visualize、math_animator、notebook），及其注册点与消费方。
- 本文所有行号锚均为上述 commit 下的 `path:line`。

## 0. 全景：agents 包在系统里的位置

DeepTutor 是 agent-native 架构：一轮对话（turn）由 `TurnApplicationService` 持久化后交给 `TurnEngine → ChatOrchestrator`，路由到某个 Capability（Level 2）。`deeptutor/agents` 就是内置 capability 的实现层：

```text
入口(CLI/WebSocket/SDK) → TurnApplicationService → TurnEngine/ChatOrchestrator
        → CapabilityRegistry ──> agents 包内的 Capability 类
                chat            → AgenticChatPipeline(=AgenticLoopPipeline) → AgentLoop
                deep_question   → QuestionPipeline / FollowupAgent
                deep_research   → ResearchPipeline
                visualize       → 复用 chat loop 或 MathAnimatorPipeline
                math_animator   → MathAnimatorPipeline
        → ToolRegistry (Level 1)：geogebra_analysis 工具 → VisionSolverAgent
```

注册点：`deeptutor/runtime/bootstrap/builtin_capabilities.py:35-48` 的 `BUILTIN_CAPABILITY_CLASSES` 以字符串路径登记
`chat / deep_question / deep_research / math_animator / visualize` 等能力类；`ask_questions / deep_solve / mastery_path / immersive_reading / course_study / immersive_watching` 等在 `deeptutor/capabilities/` 下，但其中多数（solve、ask_questions、reading、watching、course_study）复用本包的 `AgenticChatPipeline`（见 4.2）。

包自述：`deeptutor/agents/__init__.py:1-25`。注意 `co_writer`、`book` 是 `deeptutor/` 下的独立顶层模块，继承 `BaseAgent` 但不属于本包。

## 1. base_agent.py —— 所有"单 LLM 调用型"agent 的基类

| 项 | 内容 |
| --- | --- |
| 职责 | 统一 LLM 配置管理（api_key/base_url/model/binding）、从 `agents.yaml` 读温度/max_tokens（`deeptutor/agents/base_agent.py:97`）、PromptManager 双语提示词加载（`:137`）、统一 LLM 调用接口、token 统计、trace 回调 |
| 入口 | 子类实现 `process()`（抽象方法 `deeptutor/agents/base_agent.py:769`）；两个统一调用面：`call_llm()`（非流式，`:349`）与 `stream_llm()`（流式，`:519`） |
| 输出契约 | `call_llm` 返回完整文本；`stream_llm` 是 `AsyncGenerator[str]`，可用 `outcome: StreamOutcome` 带回终止原因与 usage（`:553-557`，区分完整回复与被 `max_tokens` 截断，#1545） |
| 衔接 | 下游经 `deeptutor.services.llm` 工厂路由到 cloud/local provider；`refresh_config()`（`:208`）支持运行中热更新模型配置；trace 事件经 `set_trace_callback`（`:234`）桥接到 StreamBus |

直接子类：`FollowupAgent`、`VisionSolverAgent`、visualize 三agent、math_animator 五 agent，以及包外的 co_writer/book agents。

## 2. loop/ —— 单循环引擎与它的宿主（编排核心）

包自述 `deeptutor/agents/loop/__init__.py:1-13`：**一轮 = 一个不断增长的会话上的一个循环**。两个角色分离：

- `AgenticLoopPipeline`（宿主，`deeptutor/agents/loop/pipeline.py:200`）：组装一轮所需的一切——LLM client、轮次/ token 预算、工具面、消息列表、工具分发、capability 钩子；
- `AgentLoop`（引擎，`deeptutor/agents/loop/agent_loop.py:251`）：跑循环本身，不含任何"这是 chat"的语义。

### 2.1 一轮 chat 的编排时序

```text
ChatCapability.run (chat/capability.py:25)
  └─ AgenticChatPipeline(language).run(context, stream)     # loop/pipeline.py:397
       1. 确保 runtime workspace（:398-405）
       2. _prepare_deferred_tools (:590)   → MCP/CLI 渐进加载 ToolView + PageIndex SDK 工具包
       3. _prepare_kb_manifests (:1812)    → 选中 KB 的清单注入系统提示
       4. _exec_allowed (:693)             → 沙箱策略决定 exec 是否挂载
       5. _compose_enabled_tools (:726)    → 用户开关 + 自动挂载 + capability 自有工具
       6. _build_llm_tool_schemas (:1014)  → OpenAI 工具 schema（rag minLength、geogebra 去掉 image_base64）
       7. 构造 AgentLoop 并 loop.run()     # agent_loop.py:282
            a. _capability_pre_loop_briefings (:287→pipeline:981)  # 如 explore_context 前置调查
            b. KB 种子块 _retrieve_kb_seed_block (pipeline:1473) + capability 种子 (:843)
            c. _build_loop_messages (pipeline:466)                  # 系统提示 + 历史 + runtime 快照 + 带 seed 的用户消息
            d. _run_loop (agent_loop.py:376) —— 核心循环：
                 while True:
                   - 探索预算 effective_max_rounds（默认 8 轮，pipeline:106/363）
                   - 预算耗尽 → settlement 阶段（≤3 轮，agent_loop.py:90）→ 仍要工具则强制无工具收尾 _forced_finish (:809)
                   - _call_llm (:1009)：流式消费 delta（reasoning/ content/ tool_calls）、
                     think 过滤、DSML 文本工具调用解析 (:1494)、ask_user 卡片边写边预览 (:1119)、
                     无输出前的瞬时传输错误重试 (:1105/:1382)
                   - 本轮无工具调用 = finish：截断续写 (:455)、reasoning-only 纠偏（≤2 次，:95/:547）、
                     capability finish 守卫 (:601) / final_text_override (:613) → _finalize_finish (:911)
                   - 本轮有工具调用 = narration：assistant 消息入会话 → _dispatch_tool_calls (pipeline:1115)
                     → role=tool 结果回填；ask_user 触发 pause → _await_user_reply_and_resolve (pipeline:1184)
                     → 用户答复替换进协议内继续；terminator 工具直接终结 turn (:736-743)
                 finally：normalize_model_turn 把本轮完整输入/消息/工具持久化到 context.runtime.model_turn (:321-339)
            e. emit sources / rounds / context_budget；emit_capability_result 补 cost_summary (:362-368)
```

关键不变量（`agent_loop.py:1-30` 模块 docstring）：

- 每轮文本按书写顺序流给用户并留在答案里；工具轮的文本是"注释/旁白"，无工具轮即 finish；
- `call_status` 元数据带两个独立事实：`call_role`（narration/finish）与 `answer_visible`；唯一能让文本离开答案的路径是 capability 撤回（`_discard_deferred_output`，`agent_loop.py:974`）；
- 轮次上限 = 探索预算 + settlement(3) + 1 次硬收尾。

### 2.2 宿主的三条子类化缝（非 chat 协议的接入点）

`pipeline.py:208-228` 的类属性：`prompt_module/prompt_agent`（读哪个提示词包）、`prompt_base_module`（下层继承包）、`prompt_assembler_class`（如何拼系统提示）。工具面**不是**缝：专用循环拿到与 chat 相同的面（用户开关 + 自动挂载 + capability 自有工具），想收窄须覆写 `_compose_enabled_tools`。

capability 钩子（`LoopExtension` 协议，宿主侧转发）：`owned_tools`(:811)、`system_block`(:831)、`pre_loop_seed`(:843)、`skip_kb_seed`(:851)、`finish_instruction`(:874)、`tool_round_output_policy`(:899)、`final_text_override`(:923)、`buffers_visible_output`(:953)、`pre_loop`(:981)。

### 2.3 loop/ 其余文件

| 文件 | 职责 | 锚 |
| --- | --- | --- |
| `prompt_blocks.py` | `LoopPromptAssembler`：把系统提示拆成命名 PromptBlock（runtime/memory/sources/notebooks/tools…），可变事实走 runtime 快照重放（`RUNTIME_BLOCK_NAMES`，`loop/prompt_blocks.py:27`） | `:42` |
| `context_budget.py` | 对"已组装完毕"的请求做上下文窗口占比核算（PromptBlock 列表 + 工具 schema + 最终消息），只度量不重建 | 模块头 `:1-12` |
| `dsml_tool_calls.py` | DeepSeek 无原生函数调用时，从 content 通道的 DSML 标记恢复结构化工具调用（#666） | `:1-22` |
| `ask_user_drafts.py` | `AskUserDraftEmitter`：ask_user 参数边流边发卡片预览，纯渲染提示不影响分发 | `:1-24` |

## 3. _shared/ —— 跨管线公共件

包自述 `deeptutor/agents/_shared/__init__.py:1-7`：放"不属于通用引擎、也不属于单一管线"的横切策略。

| 文件 | 职责 | 主要消费方 |
| --- | --- | --- |
| `tool_composition.py` | 每轮工具面组合策略：`AUTO_MOUNTED_TOOLS`(:40)、`_CONDITIONAL_MOUNT_FLAGS`(:47-64，rag←has_kb、read_memory←has_memory、exec←has_exec…)、`ToolMountFlags`(:142)、纯函数 `compose_enabled_tools`(:170) | loop 宿主(`pipeline.py:726`)、question(`question/pipeline.py:1596`)、research(`research/pipeline.py` 同名挂载) |
| `tool_runtime.py` | 服务端运行时绑定：`bind_workspace_tool_runtime`(:44) 给 workspace_*/exec/生成类工具注入受信路径与沙箱挂载；`drop_unconfigured_generation_tools`(:20) 隐藏未配置模型的 imagegen/videogen | 各管线的 `_augment_tool_kwargs` |
| `capability_result.py` | `emit_capability_result`(:21)：所有 capability 收敛到同一个 `stream.result` 信封，附 `cost_summary`(UsageTracker) 与 `usage_summary` | chat loop、question、research、visualize、math_animator |
| `json_output.py` | `extract_json_object`(:10)：从模型原始输出抠第一个可用 JSON 对象（剥 think 前导/围栏/尾随散文） | 依赖结构化输出的 agent |
| `workspace_prompt.py` | `workspace_system_note`(:8)：面向模型的 workspace 说明（中/英），只讲逻辑路径不暴露宿主路径 | loop 系统提示的 workspace 块 |

## 4. 各能力子目录

### 4.1 chat/ —— chat 对循环的绑定

- 职责：chat 就是基础宿主描述的那个循环，因此 `AgenticChatPipeline` 只是个名字（`chat/agentic_pipeline.py:36`），提示词包/工具面/预算全部继承默认值。
- 入口：`ChatCapability.run`（`chat/capability.py:25`）→ `AgenticChatPipeline(language).run(context, stream)`；manifest 声明 stages `exploring → responding`（`:13-23`）。
- 输出契约：走 `emit_capability_result` 的统一信封（response/completed/rounds/tool_steps + cost_summary）。
- 衔接（谁在复用 chat 协议）：`capabilities/solve/capability.py`、`capabilities/ask_questions/capability.py`、`capabilities/reading/mode.py`、`capabilities/watching/mode.py`、`capabilities/course_study/mode.py`、`services/partners/runtime.py` 直接构造 `AgenticChatPipeline`，只覆写预算与流命名空间；协议不同的 mastery 则子类化宿主（`capabilities/mastery/pipeline.py` 的 `MasteryLoopPipeline`）。

### 4.2 question/ —— 出题（deep_question）

- 职责：一条用户请求走三条路径之一（`question/capability.py:29-181`）：
  1. **followup**：针对单道题的追问 → `FollowupAgent` 单次 LLM 调用（`capability.py:74-108`，agent 在 `agents/followup_agent.py:15`，基于 `BaseAgent.stream_llm`）；
  2. **custom**：`QuestionPipeline` 三阶段（`question/pipeline.py:1-24` 相位说明）：
     - Phase 1 Explore（`:619`）：一个 THINK/TOOL/FINISH 的 agentic 循环（协议常量 `:110-137`），FINISH 文本流进聊天气泡做前导说明；每个工具结果可被 `_summarize_tool_result`（`:1045`）压缩回填；
     - Phase 2 Plan（`:708`）：单次 PLAN 标注步，产出 JSON 模板 `[{question_id, topic, question_type, difficulty}]`；
     - Phase 3 Quiz（`:876`）：每模板一个循环，FINISH 是严格 JSON 题目负载，违规走 `_repair_quiz_payload`（`:969`）一次性修复，逐题发 `quiz_question_emitted` 事件（`:1290`）让前端即时刻卡片。
  3. **mimic**：试卷 PDF → MinerU 解析 + LLM 抽题 → `templates_override` 跳过 Explore/Plan 直达 Quiz（`capability.py:183`，适配器 `mimic_source.py:1-13`）。
- 入口：`DeepQuestionCapability.run`（`capability.py:39`）；历史感知：`history.py` 的 `load_session_quiz_history` 从 `notebook_entries` 表读已考题目避免重复。
- 输出契约：`_build_result_payload`（`:1320`）+ `emit_capability_result`。
- 衔接：工具面复用 `_shared.tool_composition`（`pipeline.py:1596-1618`）；`coordinator.py:31` 的 `AgentCoordinator` 是遗留门面，转发到新管线，仍被 `api/routers/question.py`、`book/blocks/quiz.py`、`tools/question/exam_mimic.py` 引用。

### 4.3 research/ —— 深度研究（deep_research）

- 职责：四阶段管线（`research/pipeline.py:1-30` 相位说明，类 `:338`，入口 `run` `:524`）：
  1. **Rephrase**（`:762`）：mini agentic 循环，唯一工具 `ask_user`，≤3 轮澄清卡（每卡 1-4 问），FINISH 出精炼主题；
  2. **Decompose**（`:848`）：单次 OUTLINE 步拆 N 个子课题；`confirmed_outline=None` 时返回 `outline_preview` 提前退出，用户确认后二次调用续跑（capability 侧两段式编排，`research/capability.py:58-98`）；
  3. **Research blocks**（`:937`）：每个 `TopicBlock` 一个 THINK/TOOL/APPEND/FINISH 循环；`APPEND` 中间标签经 `_BlockLoopHost.on_intermediate` 动态扩队列（`data_structures.py` 的 `DynamicTopicQueue`，相似度阈值 0.85 防重，`:19`）；外层 `_drive_queue`（`:1164`）串行/并行排空；块级工具收敛到证据型 allowlist（`RESEARCH_BLOCK_TOOL_ALLOWLIST`，`pipeline.py:123-135`，含 Obsidian 只读三件套 `:118-122`）；
  4. **Reporting**（`:1282`）：OUTLINE→INTRO→逐节 SECTION→CONCLUSION 的一串单步标注调用（`:1555/:1737/:1771/:1818`），引文锚点由 `CitationManager`（`utils/citation_manager.py:62`）分配与注入。
- 模式策略：`mode_strategy.py:31` 的 `ModeStrategy` 定义 notes/report/comparison/learning_path × quick/standard/deep/manual 的行为参数。
- 入口：`DeepResearchCapability`（`capability.py:37`）→ 请求校验（`request_config.py`）→ 管线。
- 输出契约：报告 Markdown + 引文，经 `emit_capability_result`；中途失败抛 `IncompleteReportError`（`pipeline.py:306`）可带部分产物。

### 4.4 vision_solver/ —— 图像→GeoGebra 单次求解

- 职责：把旧四段管线压缩为**一次**视觉调用直出 GeoGebra 命令 + 一次门控修复（`vision_solver/vision_solver_agent.py:1-9`）。
- 入口：唯一活消费方是内置工具 `geogebra_analysis`（`tools/builtin/__init__.py:697` 定义、`:720` 导入、`:743` 实例化），chat 与 solve 都经该工具触达。
- 输出契约：`process()`（`vision_solver_agent.py:48`）返回 `{has_image, final_ggb_commands:[{command,description}], analysis_output, image_is_reference}`；`format_ggb_block`（`:82`）包成 ```ggbscript[page;title] 围栏给前端渲染。
- 衔接：修复仅在首轮 commands 为空时触发一次（`:66-72`）；JSON 抽取容忍 think 前导/尾随逗号（`:143-171`）；多模态消息走 `BaseAgent.stream_llm`（`:117-141`）。

### 4.5 visualize/ —— 可视化

- 职责：`VisualizeCapability`（`visualize/capability.py:89`）按 `render_mode` 分两条路：
  1. **manim_video/manim_image** → `_run_manim_path`（`:270`）：包装 `MathAnimatorPipeline` 走概念分析→设计→代码→渲染→总结的子进程管线，结果以 `render_type` 鉴别发统一前端分发器；
  2. **svg/chartjs/mermaid/html/auto** → **复用 chat 循环**：标记 `context.metadata[VISUALIZE_MODE_KEY]`（`:168`）、把本轮内建工具收窄到只读安全集 `_VISUALIZE_SAFE_BUILTINS`（`:77-86/:171-177`），然后构造 `AgenticChatPipeline(max_rounds=5, emit_result=False)`（`:188-197`）跑完循环；画布载荷只能经 `submit_visualization` 工具调用落桶（`VISUALIZATION_RESULT_KEY` 信封，`:198-218`），拿不到信封则抛出面向用户的诊断错误（工具调用被禁/推理耗尽 #1546）。
- 另有 `VisualizePipeline`（`visualize/pipeline.py:13`）：Analysis→CodeGenerator→Review 三 agent 顺序编排（`agents/analysis_agent.py:13` 等，均基于 `BaseAgent`），当前主要消费方在 book 模块（`book/blocks/figure.py:70-75`、`book/blocks/interactive.py:69-74` 的图/交互块生成）。
- 入口：manifest `tools_used=["submit_visualization"]`，stages 覆盖文本路径三段 + manim 六段（`:59-69`）。
- 输出契约：renderer/payload/presentation 信封 + 兼容旧字段 `response/code/analysis`（`:220-230`）。

### 4.6 math_animator/ —— Manim 数学动画

- 职责：六阶段顺序管线（`math_animator/pipeline.py:26`，`run()` `:259`）：
  `concept_analysis`（ConceptAnalysisAgent，`agents/concept_analysis_agent.py:14`）→ `concept_design`（ConceptDesignAgent）→ `code_generation`（CodeGeneratorAgent `:31`，产出 Manim 代码；时长目标从用户输入/风格提示解析，`duration_utils.py`）→ `code_retry`（`:146` `run_render`：`ManimRenderService`（`renderer.py:35`）子进程渲染 + `CodeRetryManager`（`retry_manager.py:21`，≤4 次重试，修复回调 `code_agent.repair`）+ 可选 `VisualReviewService`/`VisualReviewAgent` 看图审查）→ `summary`（SummaryAgent）→ `render_output`；产物快照发布到 workspace 展示层（`_publish_workspace_artifacts`，`:216-240`）。
- 入口：`MathAnimatorCapability.run`（`capability.py:41`）做 manim 可选依赖探测（`:42-47`）、逐 stage 包 `stream.stage` 并转发进度；也被 `visualize` 的 manim 路径（4.5）和 `book/blocks/animation.py:72-84` 复用。
- 输出契约：`{analysis, design, code, render_result(RenderResult 含 artifacts/workspace_items), summary, timings}` + `emit_capability_result`。
- request 配置：`request_config.py`（output_mode video/image、quality、style_hint）。

### 4.7 notebook/ —— 笔记 grounding 与摘要（含"落点"）

- 职责：两个不走 BaseAgent 的轻量 agent：
  - `NotebookAnalysisAgent`（`notebook/analysis_agent.py:21`）：对选中的笔记记录做 thinking→acting→observing 三段推理（`:39-75`），产出跨记录观察结论；事件经 `emit` 回调以 StreamEvent 形式进 trace。
  - `NotebookSummarizeAgent`（`notebook/summarize_agent.py:13`）：为单条笔记记录生成 ≤300 token 摘要（`:32-51` 流式）。
- **落点（谁在调、产物去哪）**：
  1. **turn 前置 grounding**：`services/session/turns/executor.py:646-658` —— 用户在请求里带 `notebook_references` 时，先取记录再 `NotebookAnalysisAgent.analyze` 得 `notebook_context`；`:718-726` 对 `history_references`（跨会话历史）同样产 `history_context`；两者在 `:756-764` 以 `[Notebook Context]/[History Context]` 段拼进**本轮 effective_user_message**（用户消息前缀），随后所有能力（chat loop / question / research / visualize / math_animator）都在各自首轮读到。
  2. **写路径摘要**：`api/routers/notebook.py:120/:136` 在记录写入/更新接口里用 `NotebookSummarizeAgent` 生成 summary 字段。
  3. **book 上下文蒸馏**：`book/inputs.py:203-208` 生成书块上下文时用 `NotebookAnalysisAgent`，失败降级为原始记录摘要。
  4. loop 侧另有常驻挂载的 `list_notebook/write_note` 工具与系统提示里的笔记本清单块（`loop/pipeline.py:1041-1056`，`prompt_blocks.py:33`），与上述引用式 grounding 互补。

## 5. tests/agents —— 测试落点

| 目录/文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `tests/agents/chat/` | 14 个文件 | AgentLoop 轮次/暂停/预算、ask_user 预览、DSML、context budget、KB 种子、提示词身份、workspace 提示 |
| `tests/agents/question/` | 4 | 管线相位、mimic 适配、双语提示 |
| `tests/agents/research/` | 11 | APPEND 队列、块工具策略、引文、请求配置、Obsidian 工具 |
| `tests/agents/visualize/` | 5 | agent 调用契约、回退、工具调用诊断 |
| `tests/agents/math_animator/` | 7 | 代码生成、重试管理、渲染错误、时长单位 |
| `tests/agents/notebook/` | 1 | 摘要 agent |
| `tests/agents/vision_solver/` | 1 | agent 单测 |
| 根：`test_base_agent_binding.py` 等 | 3 | BaseAgent binding、失败提示命名、_shared JSON |

共 46 个测试文件；外加 `tests/core/test_builtin_tools.py`（geogebra→VisionSolverAgent 装配）与 `tests/core/test_capabilities_runtime.py`（capability 注册与 chat 管线复用）在包外兜底。

## 6. 验收对照

1. **loop 编排 + ≥4 个能力子目录调用关系**：§2 给出 chat turn 全时序；§4.1-4.7 覆盖 chat、question、research、vision_solver、visualize、math_animator、notebook 共 7 个子目录的职责/入口/输出契约/衔接。
2. **只读**：本卡仅新增 `evidence/guide-agents-20261004/` 文档，`git diff` 对产品代码为零改动。
