---
title: 命令参考
description: 常用 deeptutor 命令 —— flag、输出 schema、示例。
quadrant: reference
---

本页列出常用 `deeptutor` 子命令和 flag。交互式 REPL 用法见 [**交互式 REPL**](/zh-cn/cli/chat-repl/)。自动化模式见 [**代理交接**](/zh-cn/cli/agent-handoff/)。

## `deeptutor run` —— 单次 capability 执行

执行一次 capability turn 然后退出。这是 agent 和脚本最基础的 "干活" 命令。

```bash
deeptutor run <capability> "<message>" [options]
```

内置 capability：`chat`、`ask_questions`、`deep_solve`、`deep_question`、`deep_research`、`visualize`、`math_animator`、`mastery_path`、`immersive_reading`、`video_lesson`（别名 `lesson`）、`audio_overview`（别名 `audio-overview`、`overview`）。

### Flag

| Flag | 类型 | 默认值 | 作用 |
|------|------|--------|------|
| `--session <id>` | string | *(新建)* | 续上一个已有 session |
| `-t / --tool <name>` | 可重复 | `[]` | 仅选择八个用户可开关工具；仍受上下文及能力门控约束 |
| `--kb <name>` | 可重复 | `[]` | 挂载一个知识库 |
| `--notebook-ref <id[:record,...]>` | 可重复 | `[]` | 挂载 notebook 记录 |
| `--history-ref <session_id>` | 可重复 | `[]` | 引用一个历史 session |
| `-l / --language <code>` | string | `en` | 回复语言 |
| `--config <key=value>` | 可重复 | `[]` | 单个 capability 的 config 覆盖 |
| `--config-json <json>` | string | —— | 以 JSON 形式提供 base config；后续 `--config key=value` 会覆盖同名 key |
| `-f / --format <value>` | string | `rich` | 仅精确 `json` 输出 NDJSON；其余走 rich |

### 示例

```bash
# 简单 chat turn
deeptutor run chat "用大白话解释量子纠缠"

# Deep Solve，带 reasoning + 针对某个 KB 自动挂载的 RAG
deeptutor run deep_solve "求 d/dx [sin(x²)]" --tool reason --kb math

# 生成 5 道测验题
deeptutor run deep_question "线性代数的特征向量" \
  --config num_questions=5 --config difficulty=hard

# Deep Research，JSON 流
deeptutor run deep_research "检索增强生成最近有什么新进展？" \
  --tool web_search --kb papers \
  --config mode=report --config depth=standard \
  --format json

# 续上一个 session
deeptutor run chat "接着刚才的继续" --session sess_abc123
```

### 输出 —— `--format rich`（默认）

Markdown 富文本。Deep Solve 仅 `responding`，chat 隐藏 banner：

```text
  ✻ thinking…
  ● rag(query=chain rule, kb_name=math)
  │ Chain rule: d/dx[f(g(x))] = f'(g(x)) · g'(x)
  └ #1 rag — +5 more lines; run /show 1 to expand

  ✻ thinking…

The derivative of sin(x²) is:

**2x · cos(x²)**

[dim]session=sess_abc123 turn=turn_xyz789 capability=deep_solve rounds=2 tools=1[/]
```

### 输出 —— `--format json`

每行一个 JSON 对象。方便管道给其他工具：

```text
{"type": "stage_start", "stage": "responding"}
{"type": "tool_call", "content": "rag", "metadata": {"args": {"query": "chain rule", "kb_name": "math"}}}
{"type": "tool_result", "content": "Chain rule: ...", "metadata": {"tool": "rag"}}
{"type": "content", "content": "The derivative of sin(x²) is **2x · cos(x²)**", "metadata": {"call_id": "round-2", "trace_kind": "llm_chunk"}}
{"type": "progress", "content": "", "metadata": {"call_id": "round-2", "trace_kind": "call_status", "call_state": "complete", "call_role": "finish"}}
{"type": "stage_end", "stage": "responding"}
{"type": "result", "metadata": {"response": "The derivative of sin(x²) is **2x · cos(x²)**"}}
{"type": "done", "session_id": "sess_abc123", "turn_id": "turn_xyz789", "metadata": {"status": "completed"}}
```

事件类型：`stage_start`、`stage_end`、`thinking`、`observation`、`content`、`tool_call`、`tool_result`、`progress`、`sources`、`result`、`error`、`session`、`session_meta`、`done`、`wait_for_input`。

## `deeptutor chat` —— 交互式 REPL

进入一个交互式 chat session，用 `/slash` 命令在会话内做配置。

```bash
deeptutor chat [options]
```

flag 和 `run` 里塑形 turn 的那一组一样：`--session`、`--tool / -t`、`--capability / -c`、`--kb`、`--notebook-ref`、`--history-ref`、`--language / -l`、`--config`、`--config-json`。完整说明见 [**交互式 REPL**](/zh-cn/cli/chat-repl/)。

## `deeptutor init` —— 引导式初始化向导

```bash
deeptutor init                # 完整配置（询问端口 + LLM + embedding + 搜索）
deeptutor init --cli          # 仅 CLI（跳过端口问题）
deeptutor init --home /path   # 使用非默认工作区
```

完整流程见 [**Get Started**](/zh-cn/get-started/)。

## `deeptutor doctor` —— 这个工作区能跑起来吗？

在你去翻症状之前先回答一个问题：DeepTutor 在这里能不能开一轮会话？所有判断都读本地配置，因此默认这次运行完全不联网。

```bash
deeptutor doctor                  # 只读本地配置
deeptutor doctor --online         # 额外向 provider 发一个很小的请求
deeptutor doctor --format json    # 同一份报告，机器可读（--format / -f）
deeptutor doctor runtime          # 另一份报告：v2 turn 协调 + 仓储
```

一共六项检查。这四项通常是 **必需项**：`LLM configuration`、`LLM credentials`、`LLM endpoint` 和 `Runtime storage`（数据根目录可写）。`RAG prerequisites` 是可选项，失败报 `WARN`。`Provider response` 跳过时是可选项；真正执行 `--online` probe 后就是必需项，失败报 `FAIL` 并以退出码 1 结束。

| 状态 | 含义 |
|:---|:---|
| `PASS` | 该项通过。 |
| `FAIL` | 必需项失败——启动前先修掉。 |
| `WARN` | 可选项失败；它覆盖的那个功能不可用。 |
| `SKIP` | 没什么可查的（没有配置知识库，或没加 `--online`）。 |

**任一必需项失败时退出码为 1**，所以 `deeptutor doctor` 可以直接当作容器 entrypoint 或 CI 步骤里的门禁。`--format json` 输出 `{"ok", "online", "checks": [{"key", "label", "status", "detail", "required"}]}`——读 `ok` 就好，不要去解析那张表。

## `deeptutor start` / `deeptutor serve`

```bash
# 同时启动后端 + 前端（阻塞；Ctrl+C 同时停掉）
deeptutor start
deeptutor start --home /path
deeptutor start --dev                   # 前端热更新（HMR），而非生产构建
deeptutor start --detach                # 转后台运行；之后用 deeptutor stop 停掉

# 仅后端
deeptutor serve --host 0.0.0.0 --port 8001
deeptutor serve --reload                # 文件变动时热重载（仅开发用）
```

## `deeptutor kb` —— 知识库管理

### `kb list`

```bash
deeptutor kb list                # Rich 表格
deeptutor kb list --format json    # --format / -f
```

JSON 输出：

```json
[
  {
    "name": "physics",
    "status": "ready",
    "documents": 12,
    "rag_provider": "llamaindex",
    "is_default": true
  },
  {
    "name": "math",
    "status": "indexing",
    "documents": 4,
    "rag_provider": "llamaindex",
    "is_default": false
  }
]
```

### `kb info <name>`

```bash
deeptutor kb info physics
```

返回这个 KB 的元数据、文档列表、统计信息和索引状态。

### `kb create <name>`

```bash
# 单个文档
deeptutor kb create physics --doc chapter1.pdf       # --doc / -d

# 多个文档
deeptutor kb create physics --doc chapter1.pdf --doc chapter2.pdf --doc exercises.docx

# 整个目录
deeptutor kb create textbooks --docs-dir ./my-pdfs

deeptutor kb connect-kiwix wiki --server-url http://localhost:8080 --zim-name wikipedia_en
```

`kb create` 支持文本、PDF、Office 与 EPUB；图片要求 embedding 和 LLM 都支持多模态。`connect-kiwix` 连接 ZIM，不复制或建索引。

### `kb add <name>`

往已有 KB 里增量添加文档：

```bash
deeptutor kb add physics -d chapter3.pdf
deeptutor kb add physics --docs-dir ./supplements
```

### `kb delete <name>`

```bash
deeptutor kb delete physics              # 要求确认
deeptutor kb delete physics --force      # 跳过确认（--force / -f）
```

### `kb set-default <name>`

```bash
deeptutor kb set-default physics
```

这会标记工作区默认 KB。CLI REPL 仍从无 KB 开始，只发送 `--kb` 或 `/kb` 选择。

### `kb search <name> <query>`

```bash
deeptutor kb search physics "什么是角动量？"
deeptutor kb search physics "..." --mode hybrid --format json  # --format / -f
```

`--mode` 取决于引擎：LlamaIndex 忽略；LightRAG=`naive|local|global|hybrid|mix`（默认 `hybrid`）；GraphRAG=`local|global|drift|basic`（默认 `local`）。

### `kb add-github-source <name>`

把仓库中的 Markdown 登记为可追踪来源：

```bash
deeptutor kb add-github-source physics --repo owner/repo \
  --branch main --path docs/ --glob '*.md'
```

`--repo / -r` 必填；`--branch / -b` 默认 `main`，`--path / -p` 默认仓库根目录，`--glob / -g` 默认 `*.md`。

### `kb remove-github-source <name>`

```bash
deeptutor kb remove-github-source physics --source-id <id>
```

`--source-id / -s` 指定已登记的来源。

### `kb add-web-source <name>`

登记一次有界的文档站点抓取：

```bash
deeptutor kb add-web-source physics --url https://docs.example.com \
  --max-depth 3 --max-pages 200
```

`--url / -u` 必填；抓取深度默认 `3`，页面预算默认 `200`。

### `kb remove-web-source <name>`

```bash
deeptutor kb remove-web-source physics --source-id <id>  # --source-id / -s
```

### `kb list-sources <name>`

```bash
deeptutor kb list-sources physics
```

列出已登记的 GitHub 与 Web 来源、最近状态，以及已同步的文件/页面数。

### `kb sync <name>`

```bash
deeptutor kb sync physics
```

立即同步所有已启用的 GitHub 与 Web 来源，显示各来源状态及可用的变更计数。

### 重新索引

重新索引不是一个 CLI 命令 —— 要从 **Web UI**（Knowledge → 选 KB → **Index versions** 标签页 → **Re-index**）触发。换了 embedding 模型后通常需要这一步。

## `deeptutor skill` —— 技能库与 Hub

`deeptutor skills` 是 `deeptutor skill` 的顶层别名。DeepTutor 已原生内置 **EduHub**（其开放技能仓库），无需任何配置：裸 slug 或 `eduhub:` 前缀都会解析到它（`clawhub:` 同样内置）。

```bash
deeptutor skill list                              # 本地技能列表，含 hub 来源信息
deeptutor skill search "苏格拉底" --hub eduhub --limit 10
deeptutor skill install eduhub:socratic-tutor     # 校验 → 下载 → 注册
deeptutor skill install socratic-tutor@1.2.0      # 裸 slug 默认 eduhub；@ 钉住版本
deeptutor skill install clawhub:gh-release-notes  # 其他 hub 通过前缀解析
deeptutor skill remove socratic-tutor
```

不是 DeepTutor 用户？EduHub 是一个独立、兼容 ClawHub 的注册表 —— 任意支持技能的 agent（Claude Code、Codex…）都能通过 `eduhub` CLI 使用：`npx eduhub skills install socratic-tutor`。

Hub 引用格式为 `<hub>:<slug>[@version]`，也支持带 owner 的 `<hub>:<owner>/<slug>[@version]`。所有安装都过同一道导入门：先查 hub 的安全裁定（被标记的包除非显式传 `--allow-unverified` 否则拒装）、压缩包带 zip-slip / zip-bomb 防护解压、支持文件过文本/脚本后缀白名单（二进制永远进不了工作区）、frontmatter 里的 `always:` 会被剥掉 —— 下载来的包不可能把自己注入每条 system prompt。来源信息（hub、版本、裁定）记录在技能旁边的 `.hub-lock.json` 里。

`install` 的 flag：`--name` 换个本地名字安装，`--force` 覆盖同名技能，`--allow-unverified` 无视可疑裁定继续装。

### 发布你自己的技能

同一个 CLI 也是 hub 的创作端。`login` 打开浏览器完成授权并把令牌存在本地；`publish` 上传一个技能目录；`update` 是后续维护的循环。

```bash
deeptutor skill login --no-browser                 # 只打印授权链接，不自动打开浏览器
deeptutor skill publish ./my-skill --version 1.1.0 --token "$TOKEN" --yes
deeptutor skill update ./my-skill                  # 目录可选；发布或回退
deeptutor skill logout
```

这四个命令都接受 `--hub <name>` 指定默认之外的 hub。`publish` 还接受 `--slug`、`--track`、`--token`、`--yes / -y`；`update [directory]` 接受 `--token`，适合不想把登录态存在本地的场合。

额外的注册表 —— 或覆盖某个内置项，例如把 `eduhub` 指向自建镜像 —— 在 `settings/skill_hubs.json` 里声明：`type: "clawhub"` 指向任意兼容的 HTTP API，`type: "command"` 包一个把包下载到 `{dest}` 的命令行工具，`"default"` 决定裸 slug 使用哪个 hub。在多用户部署里，这套主机 CLI 操作管理员工作区：装好的技能在 grant 分配之前对其他用户不可见。相比之下，已登录用户在 Web 端点 **Install** 会写入调用者自己的私有 skill 库；admin 分配的 skill 仍按 grant 限定且只读。

## `deeptutor session` —— session 查看

### `session list`

```bash
deeptutor session list --limit 20
```

### `session show <id>`

```bash
deeptutor session show sess_abc123                 # Rich
deeptutor session show sess_abc123 --format json   # 完整 JSON
```

JSON 输出（截断版）：

```json
{
  "id": "sess_abc123",
  "title": "Chain rule explanation",
  "capability": "chat",
  "status": "completed",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "preferences": {
    "tools": ["rag", "reason"],
    "knowledge_bases": ["math"],
    "language": "en"
  },
  "created_at": "2026-05-21T14:23:01Z",
  "updated_at": "2026-05-21T14:24:38Z"
}
```

### `session open <id>` / `session delete <id>` / `session rename <id> --title <title>`

```bash
deeptutor session open sess_abc123                    # 在 REPL 里续上
deeptutor session rename sess_abc123 --title "Calculus review"
deeptutor session delete sess_abc123
```

## `deeptutor notebook` —— notebook 记录

```bash
# 创建 notebook —— 成功后打印 8 位 id（例如 a3f9c1e2）
deeptutor notebook create research-notes --description "Daily reading log"

# 想再查一次 id 就列出来
deeptutor notebook list

# 添加 markdown 记录 —— 下面的子命令都传 id，不传名称
deeptutor notebook add-md <notebook-id> paper-summary.md \
  --title "Attention is all you need" --type research

# 替换某条记录的内容
deeptutor notebook replace-md <notebook-id> 7c1b0d45 updated-summary.md

# 删除一条记录
deeptutor notebook remove-record <notebook-id> 7c1b0d45

# 查看
deeptutor notebook show <notebook-id> --format json
```

只有 `create` 接收 notebook 名称，`list` 则不带任何参数；其余四个子命令都需要那个 8 位 id。只有 `add-md` 会把错误藏起来：id 不存在时它会跳过写入，却照样打印绿色的「Added record …」。`replace-md`、`remove-record` 和 `show` 都会以非零码退出——不过 `replace-md` 报的是「Record not found」。

`show --format` 可取 `rich|json`；类型：`chat`、`question`、`research`、`solve`、`co_writer`、`tutorbot`、`reading`、`video_learning`。

## `deeptutor memory` —— 三层记忆

DeepTutor 把用户记忆按三层存（深入说明见 [**Memory**](/zh-cn/explore/memory/)）：

- **L1** —— 每个 surface（chat、notebook、quiz 等）的原始事件轨迹
- **L2** —— 每个 surface 整理过的 markdown 摘要
- **L3** —— 跨 surface 的整体画像（recent、profile、scope、preferences）

### `memory show [target]`

```bash
deeptutor memory show                # 默认：L3 拼接
deeptutor memory show L3
deeptutor memory show L2             # 列出所有 L2 surface
deeptutor memory show profile        # 某个具体的 L3 doc
deeptutor memory show chat           # 某个具体的 L2 surface doc
```

### `memory clear [target]`

```bash
deeptutor memory clear all --force         # --force / -f；⚠️ 清空 L1+L2+L3
deeptutor memory clear trace               # 仅 L1
deeptutor memory clear chat                # 仅 chat surface 的 L1 轨迹
```

### 强制触发一次整理

手动整理不是 CLI 命令——在 Web UI 打开 L2/L3 文档（例如 `/memory/l2/chat`），选择 **Update memory** 并点击 **Run**；或调用 HTTP API：

```bash
curl -X POST http://localhost:8001/api/memory/runs/start \
  -H 'Content-Type: application/json' \
  -d '{"layer":"L2","key":"chat","mode":"update"}'
```

## `deeptutor partner` —— Partner 生命周期

```bash
deeptutor partner list

deeptutor partner create math-tutor \
  -n "Math Mentor" \
  -s "Socratic tutor specializing in algebra and calculus" \
  -m gpt-4o

deeptutor partner stop math-tutor
deeptutor partner start math-tutor
```

子命令：`list`、`create`、`start`、`stop`。`create` 会写入 partner config，并尝试启动该 partner。Web UI 是配置 channel schema、assets、tools 和 secrets 的推荐入口；CLI 适合列表、创建、启动和停止。

Partner 运行在 `data/partners/<partner_id>/workspace/` 作用域里。渠道接入说明见 [**Partners 伙伴与渠道**](/zh-cn/partners/)。

## `deeptutor config show`

```bash
deeptutor config show
```

示例输出：

```json
{
  "ports": {
    "backend": 8001,
    "frontend": 3782
  },
  "llm": {
    "binding_hint": "openai",
    "provider": "openai",
    "provider_mode": "standard",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_version": null,
    "extra_headers": {},
    "api_key": "***"
  },
  "embedding": {
    "status": "configured",
    "binding_hint": "openai",
    "provider": "openai",
    "provider_mode": "standard",
    "model": "text-embedding-3-large",
    "base_url": "https://api.openai.com/v1/embeddings",
    "api_version": null,
    "extra_headers": {},
    "dimension": 3072,
    "api_key": "***"
  },
  "search": {
    "provider": "tavily",
    "requested_provider": "tavily",
    "status": "ok",
    "fallback_reason": null,
    "base_url": "",
    "proxy": null,
    "api_key": "***"
  },
  "language": "en",
  "tools": ["rag", "web_search", "exec", "reason"]
}
```

API key 和 extra_headers 的值都会打码。

## `deeptutor module` —— 可选功能模块

```bash
deeptutor module list
deeptutor module disable solve --dry-run
deeptutor module disable solve
deeptutor module enable solve
# 独立 wheel 环境中：
deeptutor module install solve --wheelhouse dist/modules
deeptutor module uninstall solve --dry-run
```

`list` 分别显示已安装、已启用、已就绪状态。修改模块前停止 DeepTutor。源码支持 enable/disable；install/uninstall 仅用于 wheel 环境，以保护受跟踪源码。依赖关系会约束卸载和禁用，共享部署变更前可先检查 dry-run 计划。功能 wheel 与 core 必须同版本，包变更后运行 `python -m pip check`。

## `deeptutor plugin` —— 注册表查看

```bash
deeptutor plugin list                  # capability、tool 与 plugin package
deeptutor plugin info deep_solve       # 单个 capability
deeptutor plugin info rag              # 单个 tool
deeptutor plugin state                 # Installed/catalog/approval state
deeptutor plugin search                # Vendored catalog (currently empty)
deeptutor plugin show your-plugin      # Full package metadata
# Install a reviewed wheel, inspect its permissions, then approve and enable:
deeptutor plugin install ./plugin.whl --sha256 SHA256
deeptutor plugin approve your-plugin
deeptutor plugin enable your-plugin
deeptutor plugin disable your-plugin
deeptutor plugin rollback your-plugin  # Restore previous managed version
deeptutor plugin uninstall your-plugin
```

`plugin info <capability>` 返回：

```json
{
  "name": "deep_solve",
  "description": "Multi-step problem solving driven by the chat agent loop.",
  "cli_aliases": ["solve"],
  "stages": ["responding"],
  "tools_used": ["solve_plan", "solve_finish_step", "solve_replan", "rag", "exec", "geogebra_analysis", "reason"],
  "config_defaults": {},
  "availability": {
    "available": true,
    "install_hint": ""
  }
}
```

## `deeptutor provider` —— 认证流程

对于走 OAuth 或特殊 token 流程的 provider：

```bash
deeptutor provider login openai-codex       # 浏览器 OAuth，用你自己的 ChatGPT 套餐
deeptutor provider login github-copilot     # GitHub 设备登录 + Copilot 访问检查
deeptutor provider login codebuddy          # 别名：codebuddy-code、workbuddy
```

## `deeptutor book` —— Knowledge Books（引导式学习）

```bash
deeptutor book list

# 给一本 book 做健康检查（KB 漂移 + log 过期检测）
deeptutor book health book_abc123

# 重新快照 fingerprint，消除 "stale page" 警告
deeptutor book refresh-fingerprints book_abc123
```

Book 是 **Guided Learning** 学习路径的存储层。详见 [**交互式书本**](/zh-cn/explore/book/)。

## `deeptutor workspace` —— 内容工作区

```bash
# 它在哪、能不能用、写入边界有多强
deeptutor workspace show

# 把 DeepTutor 指向一个已存在的文件夹（必须已存在）
deeptutor workspace set /absolute/path/to/my-folder

# 恢复内置默认值
deeptutor workspace reset
```

内容工作区是智能体唯一可读的文件夹；它们创建的一切都落在其 `outputs/` 里。`show` 会打印路径、状态和输出安全级别——也就是把执行挡在文件夹其余部分之外的那道边界有多强。在 Docker 与服务器部署下，路径在启动时即固定，`set` 会被拒绝。详见 [**聊天工作区**](/zh-cn/explore/chat-workspace/)。

## 常见输出 schema

### TurnRequest（`run` 内部发送的对象）

```python
class TurnRequest(BaseModel):
    content: str
    capability: str | None = "chat"
    session_id: str | None = None
    tools: list[str] | None = None
    knowledge_bases: list[str] = Field(default_factory=list)
    language: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    notebook_references: list[NotebookReference] = Field(default_factory=list)
    history_references: list[str] = Field(default_factory=list)
    partner_group_references: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[OutgoingAttachment] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
```

### 流事件类型

| 事件 | 触发时机 | 字段 |
|------|----------|------|
| `stage_start` | stage 开始 | `stage`、`metadata` |
| `stage_end` | stage 结束 | `stage` |
| `content` | 内容 | `content` |
| `thinking` | 推理 | `content` |
| `observation` | observation | `content` |
| `progress` | 状态 | `content` |
| `tool_call` | 调用 | `content`、`metadata.args` |
| `tool_result` | 返回 | `content`、`metadata.tool` |
| `sources` | 来源 | `metadata.sources` |
| `result` | 结果 | `metadata` |
| `error` | 出错 | `content` |
| `session` | 身份 | `metadata` |
| `session_meta` | 元数据更新 | `metadata` |
| `done` | 完成 | 顶层 id、`metadata.status` |
| `wait_for_input` | 输入暂停 | `content` |

## 另见

- [**交互式 REPL**](/zh-cn/cli/chat-repl/) —— 日常使用 `deeptutor chat`
- [**代理交接**](/zh-cn/cli/agent-handoff/) —— 让 Claude Code / Codex 来驱动 CLI
- [**服务端 API**](/zh-cn/cli/server-api/) —— `deeptutor serve` 暴露的 HTTP / WebSocket 表面
