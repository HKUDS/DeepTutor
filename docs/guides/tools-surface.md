# DeepTutor `tools` 工具面全景导读

- 基线：origin/dev @ `fe003ddce`（v1.6.12）。
- 范围：`deeptutor/tools/` 全部顶层模块 + `vision/` 子包 + `builtin/` 注册集 + 与 `deeptutor/capabilities/` 的调用关系 + `tests/tools/` 覆盖对照。
- 所有锚点形如 `path:line`，相对仓库根。

## 1. 这一层是什么：四段注册链

工具从"一个 Python 类"走到"模型这一轮真正能调用"，经过四段链路：

```
BaseTool 协议            BuiltinToolSpec 目录              ToolRegistry 进程表                每轮 compose
(核心协议，谁都能实现) → (启动期零导入的"花名册")      → (按名懒加载实例 + 别名解析)   → (per-turn 决定挂哪些)
deeptutor/core/tool_protocol.py:220   deeptutor/tools/builtin_specs.py:20   deeptutor/runtime/registry/tool_registry.py:26   deeptutor/agents/_shared/tool_composition.py:170
```

1. **协议层** `deeptutor/core/tool_protocol.py`
   - `ToolParameter:17`（单个参数，含 `sensitive:43` 脱敏、`items:36` 数组内层 schema）、`ToolDefinition:56`（OpenAI function-calling schema，`raw_parameters:69` 支持整段 JSON-Schema 直通）、`ToolResult:130`（`content` 给模型、`sources` 给引用、`pause_for_user:164` 让 `ask_user` 暂停回合等用户、`model_message:167` 只进模型上下文的私有多模态附件）、`BaseTool:220`（`deferred:246` 标记渐进披露工具）、`ToolLookup:184`（注册表只读面）。
2. **目录层** `deeptutor/tools/builtin_specs.py:20` `BuiltinToolSpec`
   - 只存 `name + "module:Class"` 字符串，`load_class():24` / `create():32` 时才 import，并在 `create()` 里校验类名与目录名不漂移。`BUILTIN_TOOL_SPECS:46` 是唯一的内置工具花名册（共 **94 个**名字，见 §5），`BUILTIN_TOOL_NAMES:207`、`TOOL_ALIASES:217`（`pdf→read_source`、`rag_hybrid→rag{mode:hybrid}` 等 4 条）、`LazyBuiltinToolTypes:228`（给 Settings API 的惰性类序列）。
3. **进程注册表** `deeptutor/runtime/registry/tool_registry.py:26` `ToolRegistry`
   - `load_builtins():55` 只把目录 dict 拷进来（零导入）；`get():96` / `execute():151` 命中时才 `_load_builtin():59` 实例化；`_resolve_request():75` 做别名合并；`get_tool_registry():170` 进程级单例。
   - 多用户外部工具（MCP 等）不进进程表，走 `deeptutor/runtime/registry/scoped_registry.py:40` `ScopedToolRegistry`：per-turn overlay + 派发时授权（`execute` 拒绝未授权 provider 工具，注释见文件头 1-21 行）。
4. **每轮组合** `deeptutor/agents/_shared/tool_composition.py:170` `compose_enabled_tools`
   - 纯函数，chat 与 quiz 共用。顺序：用户开关工具 → 条件自动挂载 → 能力自有工具 → 常开工具（`write_memory/web_fetch/github/ask_user/cron`，`deeptutor/agents/_shared/tool_composition.py:262`）→ `forced`/`suppressed` 修正（`_finalize:268`）。`AUTO_MOUNTED_TOOLS:40` 直接由 `CONFIGURABLE_BUILTIN_TOOL_NAMES` 派生，两个面永不漂移。

## 2. 能力选择点（这一轮挂什么、参数从哪来）

- **条件挂载表** `_CONDITIONAL_MOUNT_FLAGS`（`deeptutor/agents/_shared/tool_composition.py:47`）：`rag/kb_files/knowledge_frontier ← has_kb`、`read_source ← has_sources`、`read_memory ← has_memory`、`list_notebook/write_note ← has_notebooks`、`question_bank ← has_question_bank`、`read_skill ← has_skills`、`load_tools ← has_deferred_tools`、`exec ← has_exec`、四个 `mastery_*` 导航工具 ← `has_mastery_nav/has_mastery_topics`。探测函数（`user_has_memory:287`、`user_has_notebooks:307`、`user_has_mastery_topics:324`、`user_has_question_bank:340`）一律 fail-closed。
- **管线装配点** `deeptutor/agents/loop/pipeline.py:726` `AgenticLoopPipeline._compose_enabled_tools`：逐项填 `ToolMountFlags:142`（`has_kb` 只统计"能力不持有的共选 KB"——纯 Obsidian 回合不挂 rag，issue #650；`has_sources` 在答案环恒为 False，`read_source` 由 explore_context 前置阶段持有，`deeptutor/agents/loop/pipeline.py:739-742`）；随后 `drop_unconfigured_generation_tools`（`deeptutor/agents/_shared/tool_runtime.py:20`）摘掉没配模型的 `imagegen/videogen`，`workspace_export` 在注册表存在时追加（`deeptutor/agents/loop/pipeline.py:778-781`）。
- **服务端注入参数缝** `deeptutor/agents/loop/pipeline.py:1323` `_augment_tool_kwargs`：模型永远不填的参数都在这里注入——`rag` 的 `mode:"hybrid"` 与 `_vision_supported`、`cron` 的 `_cron_owner`（路由归属，`deeptutor/agents/loop/pipeline.py:1366-1395`）、`write_note` 的真实 `conversation_history`、`geogebra_analysis` 的首图 base64、`web_search` 的 output_dir 等。读任何工具的"输入契约"时要意识到：schema 是模型可见的一半，这一层是另一半。
- **Prompt 提示层** `deeptutor/tools/prompting/__init__.py:52` `load_prompt_hints` 从 `prompting/hints/<zh|en>/<tool>.yaml` 读每工具的 when_to_use/guideline；`compose_prompt_text:203` 提供 5 种渲染格式。这是"能力选择"的软一半：模型看到什么决定它挑什么。
- **渐进披露** `BaseTool.deferred`（`deeptutor/core/tool_protocol.py:246`）+ `load_tools` 工具（`deeptutor/tools/builtin/__init__.py:1731`）：MCP 等外部工具只以一行清单进系统提示，模型用 `load_tools` 拉全 schema；`DeferredToolLoader` 在 `deeptutor/runtime/registry/deferred_tools.py:116`。

## 3. 顶层模块一览表

`deeptutor/tools/` 下 29 个顶层模块，按角色分组（锚点为模块入口/核心函数）：

| 模块 | 角色 | 挂载类别 | tests/tools 覆盖 |
|---|---|---|---|
| `builtin/`（`__init__.py`） | 21 个内置工具的 BaseTool 包装层 | 见 §5 | 部分（见 §7） |
| `builtin_specs.py` | 注册目录（§1） | — | 间接（tests/core） |
| `ask_user.py` | 澄清卡 payload 构建 | 内置 ask_user 的实现体 | ✅ test_ask_user.py |
| `brainstorm.py` | 发散式一次 LLM 调用 | 用户可开关 | ❌（包装层在 tests/core） |
| `reason.py` | 深推理一次 LLM 调用 | 用户可开关 | ❌（包装层在 tests/core） |
| `rag_tool.py` | RAGService 薄包装 | 条件自动挂 | ✅ test_rag_tool.py |
| `web_search.py` | 纯 re-export services.search | 用户可开关 | ✅（测的是 services 层） |
| `web_fetch.py` | 抓 URL→markdown（含 SSRF 防护） | 常开 | ✅ test_web_fetch.py |
| `exec_tool.py` | 唯一沙箱执行面 | 条件（has_exec） | ✅ 三个测试文件 |
| `cron_tool.py` | 定时任务 schedule/list/cancel | 常开 | ❌（tests/services/cron 覆盖） |
| `github_query.py` | gh CLI 只读查询 | 常开 | ✅ test_github_query.py |
| `knowledge_frontier.py` | KB 前沿论文发现 | 条件（has_kb） | ✅ test_knowledge_frontier_tool.py |
| `paper_search_tool.py` | arXiv 搜索 | 用户可开关 | ❌（包装层在 tests/core） |
| `zotero_search.py` | Zotero Web API 检索 | 用户可开关 | ✅ test_zotero_search.py |
| `read/list/write` 笔记三件套：`list_notebook.py`、`write_note.py` | 笔记索引/读写 | 条件（has_notebooks） | ✅ 两文件均有 |
| `question_bank.py` | 错题库六动作 | 条件（has_question_bank） | ✅ test_question_bank_tool.py |
| `mastery_nav.py` | mastery 图谱四个只读导航工具 | 条件（has_mastery_nav） | ⚠️ tests/tools 无（`deeptutor/learning/tests/test_mastery_navigation.py` 有 19 例） |
| `mastery_tool.py` / `solve_tool.py` | 兼容 re-export（实现已迁 capabilities） | — | 随 capabilities 测试 |
| `media_gen_tool.py` | imagegen/videogen | 用户可开关 + 模型配置门 | ❌（tests/services/test_media_gen 覆盖服务层） |
| `partner_memory.py` | 伙伴三分区记忆/历史 | 伙伴回合强制挂载 | ❌（tests/services/partners 覆盖） |
| `workspace.py` | 工作区 list/read/search/present/export | 基线常挂 | ⚠️ 仅 flow 级（test_pptx_workspace_flow 间接） |
| `file_tools.py` | read_file/write_file/edit_file/list_dir | **未注册（休眠模块）** | ✅ test_file_tools.py |
| `vision/` | 图像/GGB 子包 | 供 geogebra/可视化链路 | ❌ tests/tools 无（tests/visualizers 有 ggb_validator） |
| `question/` | MinerU 解析 + 出题 | research/question 管线专用 | ✅ test_question_extractor.py、test_mineru*.py |
| `tex_chunker.py` / `tex_downloader.py` | arXiv LaTeX 下载与分块 | research 管线专用 | ❌ 薄弱 |
| `prompting/` | 提示 hints 加载/渲染 | 全工具共用 | ⚠️ 仅经 exec 提示测试间接覆盖 |
| `__init__.py` | 顶层 lazy export（`_LAZY_EXPORTS:7`） | — | — |

## 4. 每个顶层工具一卡（输入 / 输出契约 / 失败语义）

### 4.1 内置包装层 `builtin/`（21 个工具的 BaseTool 面孔）

每个卡 = 一个 BaseTool 子类，`get_definition` 给 schema、`execute` 委托给同目录实现模块。共同基类 `_PromptHintsMixin:26`（`builtin/__init__.py`，下同）接上 §2 的提示层。

- **brainstorm**（`BrainstormTool:33`）：入参 `topic`（必填）+ `context`；输出 `ToolResult(content=answer, metadata={topic, answer, model})`。失败：无模型配置时实现体抛 `ValueError`（`deeptutor/tools/brainstorm.py:69`），由循环兜成工具错误。
- **rag**（`RAGTool:105`）：入参 `query`+`kb_name`（二者非空否则 `raise ValueError:127-132`）；输出正文+`sources`（`_rag_sources:68` 用检索自身 provenance，仅成功非空答案才回退 query echo，issue #694/#1500）+ `success=not failed`。失败语义：`error_type`/`needs_reindex` 转成给模型的一句话正文；命中视觉素材时按 `_vision_supported` 决定注入像素（`_rag_visual_model_message:182`，多用户作用域先解析再读文件）或提示模型"没看图别装看过"。
- **kb_files**（`KbFilesTool:227`）：`kb_name` 必填，`pattern` glob/子串、`limit` 由 `_kb_files_limit:312` 钳制；KB 不可访问抛 `ValueError:289`。语言由服务端注入（§2）。
- **knowledge_frontier**（`KnowledgeFrontierTool:323`）：`kb_name` 必填 + `focus/max_papers≤10/years_limit≤10`；输出报告 + `sources`（kb_sources + arxiv 论文行）。KB 不可访问抛 `ValueError:377`；只推荐不导入。
- **web_search**（`WebSearchTool:406`）：`query`（缺省由 §2 注入用户消息）；`asyncio.to_thread` 包同步搜索（`asyncio.to_thread` at `deeptutor/tools/builtin/__init__.py:422`）；dict 结果取 `answer/citations`，非 dict 兜成字符串。无显式失败分支——搜索服务异常会上抛由循环兜底。
- **reason**（`ReasonTool:446`）：`query`+`context`；一次 LLM 调用（`deeptutor/tools/reason.py:42`）。无模型配置抛 `ValueError`（`deeptutor/tools/reason.py:81`）。
- **paper_search**（`PaperSearchToolWrapper:484`）：`query/max_results≤20/years_limit/sort_by`；**失败软着陆**：任何 arXiv 异常→`ToolResult("arXiv search is temporarily unavailable…", error:True)`（`:526-531`），空结果给"No arXiv preprints found"。
- **zotero_search**（`ZoteroSearchToolWrapper:564`）：`query/user_id` 必填 + `api_key(sensitive=True)/max_results≤25`；`ZoteroSearchError` 码表（`:567-573`）把 invalid_api_key/library_not_found/rate_limited/network_unavailable/invalid_response 翻成模型可读文案，`success=False`。`api_key` 走 `sensitive` 不进 trace。
- **read_source**（`ReadSourceTool:821`）：`source_id`（`nb-/bk-/rd-/hs-/qb-/at-` 前缀）从注入的 `source_index` 取全文；id 缺失时唯一来源自动补齐，多来源报错；未知 id 回显合法 id 列表（`:872-881`）。工具本身无状态、无 IO。
- **read_memory / write_memory**（`ReadMemoryTool:888` / `WriteMemoryTool:918`）：read 无参、读 L3 四文档拼接；write 校验 `op∈{add,edit}` 与非空 `text`（`:973-980`），先落 L1 trace 再 `write_preference`；拒绝时 `content="write_memory rejected: …"`，去重时显式回 "already saved"（issue #647）。
- **read_skill**（`ReadSkillTool:1637`）：`name` 必填 + `file` 默认 SKILL.md；技能名不存在→列可用技能；文件不存在→列出该技能前 40 个文件（`_SKILL_FILE_LIST_LIMIT:309`）终止重试环；非法名/路径转 `success=False` 文案。
- **load_tools**（`LoadToolsTool:1731`）：`names` 数组；`_tool_loader` 服务端注入，缺失时返回"(unavailable)"；未知名单独列出，`success` 规则见 `:1784`。
- **web_fetch**（`WebFetchTool:1023`）：`url` 必填 + `max_chars`（默认 50000，解析失败兜默认）；`FetchOutcome.ok=False` 原样转 `success=False`。实现卡见 §4.2 web_fetch。
- **list_notebook / write_note**（`ListNotebookTool:1087` / `WriteNoteTool:1304`）：实现契约见 §4.2。write_note 的 append 默认正文=真实转录（注入 `conversation_history`），只有显式给 `content` 才写 agent 正文。
- **question_bank**（`QuestionBankTool:1137`）：`action` 六枚举 + 场景参数（`question/answers/category/entry_ids/limit`）；`outcome.ok=False` 时 `content=error`。实现卡见 §4.2。
- **github**（`GithubTool:1430`）：`query_type∈{pr,issue,run,repo,api}` + `target`；只读构造（见 §4.2 github_query）；gh 缺失/超时/非零退出都转 `success=False` 文案。
- **ask_user**（`AskUserTool:1493`）：`questions` 1-4 条 + `intro`；payload 校验失败转 `success=False`（`:1620-1621`）；成功时返回占位正文 + `pause_for_user` 暂停回合等回复。实现卡见 §4.2。
- **cron**（`CronTool:1789`）：`action∈{schedule,list,cancel}` + 排程三选一（`at/every_seconds/cron_expr`，`deeptutor/tools/cron_tool.py:59-68` 强制恰一个）；`_cron_owner` 缺失→"not available in this context"（`deeptutor/tools/cron_tool.py:77-82`）；在定时任务上下文里禁止再排程（`:107-111`）；时间解析失败/未知 job 均为 `ok=False` 文案。
- **geogebra_analysis**（`GeoGebraAnalysisTool:687`）：`question` + `image_base64`（无图→`success=False:729-733`；非 data URI 防御性补前缀 `:739-740`）；240s 视觉调用上限（`_VISION_ANALYSIS_TIMEOUT_S:693`，超时/管线异常都转 `success=False`）；`language` 服务端注入、拒绝模型覆盖（`:726-727`）。

### 4.2 实现模块卡

- **ask_user.py**：`build_ask_user_payload:102` 把 v2 `{questions[]}` 与 legacy `{question, options}` 归一成 `AskUserPayload`；上限常量 `MAX_QUESTIONS=4/MAX_OPTIONS=8:30-31`；丢弃截断流修复出的"半个 option"（`_drop_half_written_options:217`）、去重 label/body（#1409）、去模型自加的 "Other"；错误一律 `(None, error_message)` 返回而非抛出。`build_ask_user_preview:160` 用 json_repair 把流式半截参数画成卡片预览（best-effort，不影响真实派发）。
- **brainstorm.py / reason.py**：同构的一次 LLM 调用（`brainstorm:45` / `reason:42`），agent 参数取自配置（`get_agent_params("brainstorm")/("solve")`），返回 `{topic|query, answer, model}`。失败：`ValueError("No model configured…")`；LLM 异常上抛。
- **rag_tool.py**：`rag_search:15` 校验非空 query/kb_name，多用户走 `resolve_for_rag`（无显式 base_dir 时），KB 不可访问抛 `ValueError:41`；同文件还有 `initialize_rag:54` / `delete_rag:66`（索引生命周期，非 chat 工具）。
- **web_search.py**：纯 re-export（`:26-42`）；真身在 `deeptutor/services/search/__init__.py:131`。
- **web_fetch.py**：`fetch_url_as_markdown:73` → `FetchOutcome:57`。安全姿态（文件头 10-22 行自述）：仅 http/https；私网/环回/链路本地地址拒绝且 pre-flight + 每一跳重定向后复查（`_is_disallowed_host:177`，DNS 失败 fail-closed）；响应硬顶 4MB（`MAX_RESPONSE_BYTES:39`）、正文截断 `max_chars`；15s 超时、最多 5 跳。正文抽取优先复用 html_extractor，失败退正则路径（`_extract_readable:242`）。
- **exec_tool.py**：`ExecTool:36` 是**唯一**沙箱执行面。`_execute_shell:192` 过 `_DENY_PATTERNS:19`（rm -rf、mkfs、fork 炸弹等→`sandbox.command_blocked`）；`_execute_source:223` 把 python/c/cpp 源码落盘再跑（平台命令拼装 `_command_for_platform:106`）；超时 30s 默认、300s 上限（`_DEFAULT_TIMEOUT/_MAX_TIMEOUT:32-33`）；产物经 `_render_result:301` 快照-收集-渲染，`success=ok and exit_code==0:366`。`_sandbox_*` kwargs 全部服务端注入。
- **cron_tool.py**：`run_cron_action:76` 纯函数；三动作 + `add/remove` 旧别名（`:86-89`）；schedule 参数构造 `_build_schedule:59`（恰一个时间源，否则 ValueError）；无 `_cron_owner` 即拒绝。输出给模型的是渲染文本。
- **github_query.py**：`run_github_query:66` → `GithubOutcome:49`。argv 白名单 `_build_argv:152` 只有 view/list，`api` 分支固定 GET、不经过 shell（`:192-196`）；gh 不安装→友好 `ok=False`；20s 超时、16k 输出截断。
- **knowledge_frontier.py**：`discover_frontier:26` 三步：KB 摘要（内部调 rag）→ LLM 派生 ≤3 个 arXiv 查询（失败时退化用文档名）→ 搜索去重渲染。参数钳制 `_clamped_int`，文档名 fallback 保证"删掉 LLM 也还有结果"。
- **list_notebook.py**：`list_notebooks_or_records:49` 双模式（索引/下钻）；上限 50 笔记本/80 记录（`:31-32`）；未知 notebook_id 回显合法 id（`:121-126`）；错误返回 `ListOutcome(ok=False, error=…)` 不抛。
- **write_note.py**：`write_note:61` 双模式 append/edit；长度帽 title 200/note 4k/content 200k（`:37-39`）；`turns_to_include` 默认 3 或 "all"（`:43-44`）；依赖注入 `notebook_manager/conversation_history` 便于测试；一切失败走 `WriteOutcome(ok=False)`。
- **question_bank.py**：`run_question_bank:470` 六动作（`ACTIONS:45`）；`_coerce_ids:77` 把模型给脏的 entry_ids 拆成"可用+拒绝"两份，绝不静默丢弃；list 上限 20/100（`:52-53`）；伙伴回合把写路径解析到 learner 真实库（`_partner_bank_paths:137`）；全部依赖注入 `store`。
- **mastery_nav.py**：四工具（`MASTERY_NAV_TOOL_NAMES:56`）`mastery_topics/sessions/open_session/new_session`。两条安全线（模块头 18-32 行）：**只读**（不租约、不登记、不动 mastery 等级）与**不导航**（后两者只产 `mastery_handoff` 卡，`HANDOFF_META_KEY:54`，学习者点击才跳）。所有 id 先对 store 校验（`_topic_or_error:80`）；在当前话题自己的会话里拒绝发"开新会话"卡（`_handoff_lands_where_we_already_are:94`，#1412/#1411）。
- **media_gen_tool.py**：`ImagegenTool:135`（`prompt` 必填、`n≤4`）与 `VideogenTool:217`（`aspect_ratio/duration`）。未配置模型→`ValueError` 转 `success=False`；`GenerationProviderError`→失败文案；产物写进工作区 outputs/ 并以 artifacts 返回，**呈现必须再走 workspace_present**（模块头 10-15 行）。
- **partner_memory.py**：三工具 `partner_read/memorize/search`（`PARTNER_BUILTIN_TOOL_NAMES:26`）。分裂记忆模型（模块头 3-15 行）：owner 的 L3 只读 + 伙伴自有分区可写；产品 chat 中被抑制、伙伴回合强制挂载。search 是伙伴会话历史的关键词扫描（snippet 140 字、上限 300 命中，`:32-33`）。
- **workspace.py**：五工具 `WorkspaceListTool:25 / ReadTool:73 / SearchTool:116 / PresentTool:156 / ExportTool:219`。前三只读（`WorkspaceError` 统一转 `_failure:21`）；present 是"把文件以卡片呈现给用户"的唯一正当路径；export 是**唯一**越出 outputs/ 的写，且必须经 ask_user 授权卡一次一签（`:269-327`）。前四个是 `WORKSPACE_BASELINE_TOOLS`（`deeptutor/agents/_shared/tool_composition.py:73`）——独占能力回合与伙伴过滤都摘不掉的基线。
- **paper_search_tool.py**：`ArxivSearchTool:24`；抓取量 = 2×需求（上限 30）再按年过滤截断（`:72`、`:116`）；30s 超时、429 退避重试一次（`:94-107`）；一切异常→空列表（由包装层转文案）。
- **zotero_search.py**：`ZoteroSearchClient:33` + 码化异常 `ZoteroSearchError:24`；401/403→invalid_api_key、404→library_not_found、429→rate_limited、网络→network_unavailable、非 JSON→invalid_response（`:81-97`）；user_id 白名单正则（`:19`）。
- **file_tools.py**：`ReadFileTool:41/WriteFileTool:109/EditFileTool:134/ListDirTool:189`。路径必须在 `_allowed_dir` 内（`_resolve_workspace_path:13`，越界 `PermissionError`）；edit 的 not-found 会给最相似片段的 unified diff（`_not_found_message:266`）。**注意：该模块当前未进入 BUILTIN_TOOL_SPECS，也没有任何管线挂载它——注册表视角是休眠代码**（仅 tests/tools/test_file_tools.py 引用）。
- **mastery_tool.py:9 / solve_tool.py:8**：纯兼容 re-export，实现已迁 `deeptutor/capabilities/mastery/tools` 与 `deeptutor/capabilities/solve/tools`。
- **tex_downloader.py**：`TexDownloader:44`——arXiv e-print 下载→解包→定位主 tex；`TexDownloadResult(success, tex_path, tex_content, error)`（`:28`）。requests 同步 30s 超时（`:83`）。
- **tex_chunker.py**：`TexChunker:21`——按 section/token 分块（tiktoken，模型不支持时退 cl100k_base，`:37-45`）；token 估算失败退 len/4（`:62-65`）。
- **question/**：`deeptutor/tools/question/question_extractor.py:321` `extract_questions_from_paper`（MinerU 产物→LLM 抽题）；`deeptutor/tools/question/exam_mimic.py:18` `mimic_exam_questions` 是出题协调器的薄入口（pdf_path / paper_dir 二选一，`:29-32`）；`deeptutor/tools/question/__init__.py:10-16` 把 MinerU 解析 re-export 成历史 API。
- **prompting/**：见 §2 末条。`ToolPromptComposer:89` 五种格式（list/table/aliases/phased/list_with_usage）。
- **vision/**：见 §6。

## 5. builtin 集：94 个注册名与四种挂载类别

`BUILTIN_TOOL_SPECS`（`deeptutor/tools/builtin_specs.py:46-205`）共 94 个名字，按宿主分：`tools/builtin` 21 + `exec` 1 + `workspace` 5 + `submit_visualization` 1 + `imagegen/videogen` 2 + `mastery_nav` 4 + capabilities 持有的 60（mastery 14、solve 3、obsidian 9、marginnote4 7、subagent 1、ima 5、reading 8、setup 4、partner_authoring 1、partner_group 1、course_study 4）+ `partner_memory` 3。

挂载类别（决定谁有权开关它）：

| 类别 | 名单锚点 | 机制 |
|---|---|---|
| 用户开关（/settings/tools "体验增强"） | `USER_TOGGLEABLE_TOOL_NAMES`（`deeptutor/tools/builtin/__init__.py:1907`）：brainstorm、web_search、paper_search、zotero_search、reason、geogebra_analysis、imagegen、videogen | composer 开关 + 管理员全局白名单（`admin_enabled_optional_tools:98`） |
| 条件自动挂载（对用户"锁定"） | `CONFIGURABLE_BUILTIN_TOOL_NAMES:1932` 共 20 个 | `_CONDITIONAL_MOUNT_FLAGS`（§2） |
| 常开自动挂载 | write_memory、web_fetch、github、ask_user、cron（`deeptutor/agents/_shared/tool_composition.py:262`） | 无条件（伙伴白名单仍可减） |
| 能力自有 | capabilities 的 `owned_tools`（§7） | 能力激活即加挂 |
| 伙伴强制/抑制 | `PARTNER_BUILTIN_TOOL_NAMES:208`；chat 记忆工具被 `_PARTNER_SUPPRESSED_TOOLS` 抑制 | `forced/suppressed`（`deeptutor/agents/_shared/tool_composition.py:219-228`） |
| 基线（不可摘） | `WORKSPACE_BASELINE_TOOLS`（`deeptutor/agents/_shared/tool_composition.py:73`）workspace_list/read/search/present | 独占回合也保留（`compose_enabled_tools:247`） |
| 占位（暂停上架） | `COMING_SOON_TOOL_TYPES:1896`（当前为空） | Settings 显示 "Coming soon"，不进注册表 |

## 6. vision 子包

`deeptutor/tools/vision/`（`deeptutor/tools/vision/__init__.py:1-41` 一次导出四组），服务 GeoGebra 可视化链路（`geogebra_analysis` 工具 + `agents/vision_solver` + `visualizers`）：

- **image_utils.py**：URL→base64 下载与校验（`is_valid_image_url:33`、`is_base64_image:49`），10MB 上限、30s 超时（`:21-24`）；`ImageError:27`。
- **coord_transform.py**：BBox 像素坐标 ↔ GeoGebra 数学坐标（文件头 1-14 行写明两坐标系差异）；`GGBCoordSystem:29`、`bbox_to_ggb`/`ggb_to_bbox`/`suggest_coord_system` 等。
- **ggb_validator.py**：`validate_command/validate_ggbscript` + `ValidationResult:12`（original/fixed/warnings/errors）；内置"该用方括号"的命令白名单修复 LLM 常见笔误。
- **block_parser.py**：从 LLM 流式输出里抽 ```ggbscript[page-id;title] 围栏块（`parse_ggb_blocks:47`、`StreamingBlockParser`），块内容过 ggb_validator 校验并保留原文。
- 测试现状：`tests/tools/` 无 vision 测试；`tests/visualizers/test_ggb_validator.py` 覆盖 validator；`tests/agents/vision_solver/` 覆盖 agent 侧。coord_transform/block_parser/image_utils 全测试树无直接单测（见 §8 缺口 3）。

## 7. 与 capabilities 的调用关系

- **两种能力协议**（`deeptutor/capabilities/protocol.py`）：
  - `LoopExtension:38`（普通能力）：复用 chat 全量工具面，只在激活时把 `owned_tools:104` **加**在面上（`deeptutor/agents/loop/pipeline.py:811-816` 汇集）。可选钩子：`pre_loop:53`（回合前预 pass）、`augment_kwargs:118`（给自有工具注入服务端 kwargs）、`rebinding_tools:81`（如 `mastery_switch`，先执行并重绑本轮其余调用）。
  - `KnowledgeCapability:130`：**独占**面。激活时 `exclusive_tools:145` 生效，回合只剩 `owned_tools + ask_user 地板`，外加共选 KB 的 `rag/kb_files/knowledge_frontier` 三件（`_KB_COEXISTING_TOOLS`，`deeptutor/agents/_shared/tool_composition.py:68`、`compose_enabled_tools:230-248`，#650）。obsidian、marginnote4、ima 是此类。
- **能力注册** `deeptutor/capabilities/registry.py:28` `LoopCapabilitySpec`（class_path + 惰性工厂 + 漂移校验）；插件 entry-point 亦可在运行期并入（registry.py 内 `_LegacyLoopCapabilitiesView:107` 一带）。
- **tools/ 与 capabilities/ 的边界**：通用工具住 `tools/`；一种能力专属、跟随能力激活的工具住 `capabilities/<name>/tools.py`，但仍登记进同一张 `BUILTIN_TOOL_SPECS` 目录（`deeptutor/tools/builtin_specs.py:96-204`），注册与挂载机制完全一致——差别只在"谁决定挂"（§2 的 flags vs §7 的 owned_tools）。
- **搜索/研究等固定管线**（research、question 管线）不经过 chat 组合器，直接 import `tools/` 的函数（如 `tex_downloader`、`paper_search_tool.ArxivSearchTool`、`question/`）——这也是 tex/question 两族缺 chat 测试的原因：它们的调用方在 `agents/research`、`agents/question`。

## 8. tests/tools 覆盖对照（薄弱工具标注）

`tests/tools/` 现有 21 个测试文件（含 `builtin/test_read_skill_tool.py`）。按"模块 → 测试"映射：

**有直接覆盖**：ask_user（563 行，最厚）、write_note（368 行）、web_fetch（323 行）、question_bank（298 行）、exec_tool（test_code_execution_guidance + test_exec_prompt_hints + test_pptx_workspace_flow + test_office_artifact_execution，含 workspace_present 联动）、github_query（187 行）、zotero_search（195 行）、kb_files（196 行）、read_source（85 行）、list_notebook（147 行）、knowledge_frontier（175 行）、rag_tool（127 行，测 services.factory + rag_tool 契约）、question_extractor（75 行）+ mineru 两文件、file_tools（60 行）。

**tests/tools 缺口**（括号内为树内其他位置的既有覆盖，若无标注则全仓测试树内也无直接单测）：

1. **cron_tool** — `tests/services/cron/test_cron_tool.py` 有；`tests/tools/` 无（可接受，位置合理）。
2. **mastery_nav.py（500 行）** — `tests/tools/` 无，但 `deeptutor/learning/tests/test_mastery_navigation.py`（372 行、19 例）直接覆盖全部四工具：id 解析、跨话题拒绝、自我会话拒绝（#1412/#1411）、空图谱。覆盖充分，只是位置在 learning 包内。
3. **vision/coord_transform.py（436 行）、block_parser.py（251 行）、image_utils.py（210 行）** — ❗ 薄弱：全测试树（tests/、deeptutor/**/tests/）零直接引用。坐标换算与围栏解析是纯函数、易测；目前 vision 子包只有 ggb_validator 有专测（`tests/visualizers/test_ggb_validator.py`）。
4. **tex_downloader.py / tex_chunker.py** — ❗ 薄弱：下载/解包/主文件定位、按 token 分块全树无单测（research 管线消费方亦无）。
5. **paper_search_tool.py** — 包装层被 `tests/core/test_builtin_tools.py:616` 用 fake 覆盖；**ArxivSearchTool 本体**（年过滤、429 重试、抓取量放大）无直接单测（knowledge_frontier 测试同样只 fake 它）。
6. **media_gen_tool.py** — `tests/services/test_media_gen.py` 覆盖服务层 + 包装层的提示语与 `ImagegenTool().execute` 主路径（`:584-599`）；参数钳制边界（n≤4、size 透传）与 videogen 失败分支覆盖较薄。
7. **partner_memory.py** — `tests/services/partners/test_partner_memory_tools.py` 有；`tests/tools/` 无（位置合理）。
8. **brainstorm.py / reason.py 本体** — 包装层在 tests/core 有 fake 级覆盖；实现体（agent 参数回退、无模型 ValueError）无专测。
9. **workspace.py** — 仅 `test_pptx_workspace_flow.py` 以流式集成路径触达 exec+present；`WorkspaceListTool/ReadTool/SearchTool/ExportTool` 的参数钳制与 `_failure` 转换无直接单测。export 的授权卡流程值得补。
10. **file_tools.py** — 有测试但**工具本身未注册**（§4.2）：要么补进目录并挂载，要么明确标注弃用——二选一，当前状态最容易误导读者。
11. **prompting/** — `load_prompt_hints` 的 zh/en 回退仅经 `test_exec_prompt_hints.py` 间接触达；`ToolPromptComposer` 五种格式无格式级单测。
12. **web_search.py** — 测试都在 services 层（provider 白名单等）；顶层 re-export 无需独立测试，正常。

**覆盖强度排序（最需补）**：vision(coord_transform/block_parser/image_utils) > tex_downloader/tex_chunker > ArxivSearchTool 本体 > workspace 四工具 > prompting 格式渲染 > media_gen 边界分支。

## 9. 读代码的推荐路径

1. 先读协议：`deeptutor/core/tool_protocol.py:220`（BaseTool）与 `:130`（ToolResult 的 pause_for_user/model_message 两个特殊通道）。
2. 再读目录与注册表：`deeptutor/tools/builtin_specs.py:46` + `deeptutor/runtime/registry/tool_registry.py:96`（get 的懒加载与别名）。
3. 然后读组合器：`deeptutor/agents/_shared/tool_composition.py:170` 的 docstring 就是本层最完整的语义说明。
4. 挑三个代表工具精读：`rag`（builtin/__init__.py:105，多用户+视觉+失败语义最复杂）、`ask_user`（ask_user.py:102 + AskUserTool:1493，暂停-恢复回合）、`exec`（exec_tool.py:36，沙箱+产物）。
5. 最后按需进 capabilities：`deeptutor/capabilities/protocol.py:38/130` 理解"加挂"与"独占"两族。
